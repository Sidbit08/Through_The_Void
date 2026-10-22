"""Explicit administrator actions. Importing this module changes nothing."""
import base64
import contextlib
import fcntl
import json
import os
import pwd
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from . import config as cfg, preflight, render, storage

SERVICES = ['ctf-event-firewall.service', 'ctf-event-dns.service', 'ctf-event-proxy.service']
PAM_MARKER = '# CTF-EVENT-MODE managed session gate'
PAM_LINE = 'session requisite pam_exec.so quiet seteuid /usr/local/sbin/ctf-event gate-login'


class Platform:
    def run(self, args, check=True):
        code, out, err = preflight.run(args, timeout=40)
        if check and code:
            raise RuntimeError(f'{args[0]} failed ({code}): {err.strip() or out.strip()}')
        return code, out, err

    def inventory(self, config):
        return preflight.inspect(config)

    def root(self):
        if os.geteuid() != 0:
            raise RuntimeError('This action requires an authorized administrator using sudo')

    def paths(self, paths):
        for path in paths:
            storage.secure_ancestors(path)

    def boot_id(self):
        return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def check_files(directory, kernel=False, platform=None, live_delete=False):
    """Use the real daemon parsers. Squid can print FATAL while returning zero."""
    platform = platform or Platform()
    directory = Path(directory)
    checks = []
    for args in [['unbound-checkconf', str(directory / 'unbound.conf')],
                 ['squid', '-k', 'parse', '-f', str(directory / 'squid.conf')]]:
        code, out, err = platform.run(args, check=False)
        if code or 'FATAL:' in out + err or 'ERROR:' in out + err:
            raise RuntimeError('Configuration validation failed: ' + args[0] + '\n' + (err or out)[-3000:])
        checks.append(args[0])
    if kernel:
        raw = (directory / 'nftables.conf').read_text()
        if live_delete:
            raw = f'delete table inet {render.TABLE}\n' + raw
        path = directory / 'nft-check.conf'
        storage.atomic(path, raw, 0o644)
        platform.run(['nft', '--check', '--file', str(path)])
        checks.append('nft --check (kernel)')
    return checks


def write_plan(config, inventory, directory):
    directory = Path(directory).resolve()
    if os.geteuid() == 0:
        storage.secure_ancestors(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in render.files(config, inventory, str(directory)).items():
        storage.atomic(directory / name, text, 0o644)
    policies = []
    for index, browser in enumerate(inventory.get('browsers', [])):
        settings = render.firefox(config, tuple(browser['version'])) if browser['kind'] == 'firefox' else render.chromium(config, tuple(browser['version']))
        storage.json_write(directory / f'browser-{index}.json', {'policies': settings} if browser['kind'] == 'firefox' else settings, 0o644)
        policies.extend(browser['policy_paths'])
    storage.json_write(directory / 'plan.json', {
        'dry_run_only': True, 'mode': config['mode'], 'participants': config['participants'],
        'policy_targets': policies,
        'system_changes': ['/etc/pam.d/common-session (append participant-only safety gate)',
                           '/etc/polkit-1/rules.d/00-ctf-event-mode.rules',
                           '/etc/dbus-1/system.d/00-ctf-event-mode.conf',
                           'three dedicated systemd units', 'one owned inet nftables table'],
        'required_confirmation': '180-second default timer; explicit administrator confirmation',
        'unchanged': ['system DNS/resolv.conf', 'global firewall ruleset', 'router/LAN/DHCP',
                      'participant accounts/files', 'certificate trust stores'],
        'limitations': ['domain blocklists cannot prove zero AI access', 'shared-hostname HTTPS features remain indistinguishable',
                        'same-UID offline code/models require clean accounts/profiles and supervision'],
    }, 0o644)
    return directory


def policy_changes(config, inventory, baseline=None):
    """Merge unrelated policies; refuse conflicting enforcement/extension settings."""
    changes = {}
    targets = []
    for browser in inventory['browsers']:
        version = tuple(browser['version'])
        values = render.firefox(config, version) if browser['kind'] == 'firefox' else render.chromium(config, version)
        for target in browser['policy_paths']:
            targets.append((target, browser['kind'], values))
    for target, kind, values in targets:
        path = Path(target)
        existing = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(existing, dict):
            raise RuntimeError('Not a JSON policy object: ' + target)
        original = baseline.get(target) if baseline else None
        if original:
            existing = json.loads(base64.b64decode(original['data'])) if original['exists'] else {}
        policies = existing.setdefault('policies', {}) if kind == 'firefox' else existing
        if not isinstance(policies, dict):
            raise RuntimeError('Invalid browser policy object: ' + target)
        forbidden = {'AIControls', 'Extensions'} if kind == 'firefox' else {'ProxyMode', 'ProxyServer', 'ProxyPacUrl', 'ProxyBypassList', 'ExtensionInstallForcelist', 'CloudPolicyOverridesPlatformPolicy'}
        if forbidden & set(policies):
            raise RuntimeError('Existing policy requires manual integration: ' + target + ' ' + str(sorted(forbidden & set(policies))))
        for name, value in values.items():
            if name in policies and policies[name] != value:
                raise RuntimeError(f'Existing policy conflicts: {target}: {name}. Preserve it and obtain an administrator-reviewed integration')
        if kind == 'chromium':
            for other in path.parent.glob('*.json'):
                if other == path:
                    continue
                previous = json.loads(other.read_text())
                if forbidden & set(previous) or any(name in previous and previous[name] != value for name, value in values.items()):
                    raise RuntimeError('Other managed Chrome/Chromium policy conflicts: ' + str(other))
        policies.update(values)
        changes[target] = json.dumps(existing, indent=2, sort_keys=True) + '\n'
    return changes


def nft_signature(raw):
    def clean(value):
        if isinstance(value, list):
            return [clean(v) for v in value if not isinstance(v, dict) or 'metainfo' not in v]
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k not in {'handle', 'index', 'position', 'packets', 'bytes'}}
        return value
    return storage.digest(json.dumps(clean(json.loads(raw)), sort_keys=True).encode())


class Controller:
    def __init__(self, root=Path('/'), platform=None):
        self.root = Path(root)
        self.platform = platform or Platform()
        self.etc = self.path('/etc/ctf-event-mode')
        self.var = self.path('/var/lib/ctf-event-mode')
        self.state_path = self.var / 'state.json'
        self.pending_path = self.var / 'pending.json'

    def path(self, absolute):
        return self.root / absolute.lstrip('/')

    def read_state(self):
        return json.loads(self.state_path.read_text()) if self.state_path.exists() else {'enabled': False, 'originals': {}, 'applied': {}}

    @contextlib.contextmanager
    def lock(self):
        self.platform.root()
        self.platform.paths([self.var])
        self.var.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.var, 0o700)
        with (self.var / 'lock').open('a') as lock:
            os.chmod(self.var / 'lock', 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def nft_exists(self):
        code, out, err = self.platform.run(['nft', '-j', 'list', 'table', 'inet', render.TABLE], check=False)
        if code:
            if 'No such file' in err or 'does not exist' in err:
                return False
            raise RuntimeError('Cannot determine firewall table ownership: ' + err)
        tables = [x['table'] for x in json.loads(out).get('nftables', []) if 'table' in x]
        if len(tables) != 1 or tables[0].get('comment') != render.STAMP:
            raise RuntimeError('Refusing to alter an unowned firewall table')
        return True

    def firewall(self, directory):
        raw = (Path(directory) / 'nftables.conf').read_text()
        if self.nft_exists():
            raw = f'delete table inet {render.TABLE}\n' + raw
        batch = self.var / 'apply.nft'
        storage.atomic(batch, raw)
        self.platform.run(['nft', '--check', '--file', str(batch)])
        # One nft transaction replaces only our named table. No global flush.
        self.platform.run(['nft', '--file', str(batch)])

    def signature(self):
        return nft_signature(self.platform.run(['nft', '-j', 'list', 'table', 'inet', render.TABLE])[1])

    def install(self, source, configuration):
        with self.lock():
            if (self.var / 'installed.json').exists():
                return {'result': 'already installed', 'next': 'validate then enable'}
            config = cfg.load(configuration)
            inventory = self.platform.inventory(config)
            if inventory['distribution'].get('ID') not in ('debian', 'ubuntu') or not inventory['systemd']:
                raise RuntimeError('Installation requires a real Ubuntu/Debian systemd host; no restrictions were enabled')
            missing = [name for name, path in inventory['dependencies'].items() if not path]
            if missing:
                raise RuntimeError('Install prerequisites first: ' + ', '.join(missing))
            for name in ('ctfproxy', 'ctfdns'):
                if name in inventory['users']:
                    raise RuntimeError('Dedicated identity already exists without toolkit ownership: ' + name)
            package = self.path('/usr/local/lib/ctf-event-mode')
            wrapper = self.path('/usr/local/sbin/ctf-event')
            unit_paths = [self.path('/etc/systemd/system/' + s) for s in SERVICES]
            self.platform.paths([package, wrapper, self.etc] + unit_paths)
            for path in [package, wrapper, self.etc] + unit_paths:
                if path.exists():
                    raise RuntimeError('Refusing to overwrite an existing installation path: ' + str(path))
            installed = {'accounts': {}, 'files': [], 'version': 1}
            # The install record is updated after each created item for recovery.
            storage.json_write(self.var / 'installing.json', installed)
            try:
                for name in ('ctfproxy', 'ctfdns'):
                    self.platform.run(['useradd', '--system', '--user-group', '--no-create-home', '--home-dir', '/nonexistent', '--shell', '/usr/sbin/nologin', name])
                    installed['accounts'][name] = self.platform.inventory(config)['users'][name]['uid']
                    storage.json_write(self.var / 'installing.json', installed)
                package.mkdir(parents=True)
                for name in ('ctf_event.py', 'ctfmode'):
                    src, dst = Path(source) / name, package / name
                    if src.is_dir():
                        shutil.copytree(src, dst, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
                    else:
                        shutil.copyfile(src, dst)
                for path in package.rglob('*'):
                    if path.is_symlink():
                        raise RuntimeError('Source package may not contain symlinks')
                    os.chmod(path, 0o755 if path.is_dir() else 0o644)
                    if os.geteuid() == 0:
                        os.chown(path, 0, 0)
                installed['files'].append(str(package))
                storage.atomic(wrapper, '#!/bin/sh\nexec /usr/bin/python3 -I /usr/local/lib/ctf-event-mode/ctf_event.py "$@"\n', 0o755)
                installed['files'].append(str(wrapper))
                self.etc.mkdir(mode=0o755)
                for key, filename in [('denylist', 'ai-denylist.txt'), ('allowlist', 'strict-allowlist.txt')]:
                    storage.atomic(self.etc / filename, Path(config[key]).read_bytes())
                    config[key] = str(self.etc / filename)
                config.pop('allow_domains'); config.pop('deny_domains')
                storage.json_write(self.etc / 'event.json', config)
                for relative, filename in [('lists/domain-sources.json', 'starter-domain-sources.json'),
                                           ('docs/policy-sources.json', 'policy-sources.json')]:
                    metadata = Path(source) / relative
                    if metadata.is_file():
                        storage.atomic(self.etc / filename, metadata.read_bytes())
                installed['files'].append(str(self.etc))
                for service, path in zip(SERVICES, unit_paths):
                    storage.atomic(path, render.unit(service.split('-')[-1].split('.')[0]), 0o644)
                    installed['files'].append(str(path))
                storage.json_write(self.var / 'installed.json', installed)
                storage.json_write(self.state_path, self.read_state())
                (self.var / 'installing.json').unlink()
                self.platform.run(['systemctl', 'daemon-reload'])
            except BaseException:
                storage.json_write(self.var / 'installing.json', installed)
                raise RuntimeError('Installation interrupted; no firewall was enabled. Preserve /var/lib/ctf-event-mode/installing.json and use uninstall --archive PATH for cleanup')
            return {'result': 'installed; inactive', 'config': str(self.etc / 'event.json')}

    def enable(self, configuration=None, mode=None, seconds=180):
        if not 60 <= seconds <= 600:
            raise RuntimeError('Rollback interval must be 60–600 seconds')
        with self.lock():
            if not (self.var / 'installed.json').exists():
                raise RuntimeError('Install the toolkit before enabling')
            if self.pending_path.exists():
                raise RuntimeError('An activation is awaiting confirmation; confirm or rollback it first')
            config = cfg.load(configuration or self.etc / 'event.json', mode)
            list_contents = {key: Path(config[key]).read_text() for key in ('allowlist', 'denylist')}
            config['allowlist'] = str(self.etc / 'strict-allowlist.txt')
            config['denylist'] = str(self.etc / 'ai-denylist.txt')
            inventory = self.platform.inventory(config)
            if inventory['blockers']:
                raise RuntimeError('Preflight refused activation:\n' + '\n'.join(inventory['blockers']))
            cfg.identity(config, inventory)
            original_state = self.read_state()
            if original_state['enabled'] and original_state.get('fingerprint') == cfg.fingerprint(config):
                return {'result': 'already enabled', 'mode': config['mode']}
            token = secrets.token_hex(12)
            generation = self.etc / 'runtime' / token
            write_plan(config, inventory, generation)
            # Daemons read immutable generation paths, never participant-writable inputs.
            changes = policy_changes(config, inventory, original_state.get('originals'))
            persisted = {key: value for key, value in config.items() if key not in ('allow_domains', 'deny_domains')}
            sources = {str(self.etc / 'event.json'): json.dumps(persisted, indent=2) + '\n',
                       config['allowlist']: list_contents['allowlist'], config['denylist']: list_contents['denylist']}
            changes.update(sources)
            apparmor_profiles = []
            for integration in inventory.get('apparmor', {}).get('integrations', []):
                target = self.path(integration['local'])
                text = target.read_text() if target.exists() else ''
                original = original_state.get('originals', {}).get(str(target))
                if original:
                    text = base64.b64decode(original['data']).decode() if original['exists'] else ''
                kind = integration['kind']
                text = text.rstrip('\n') + '\n# CTF-EVENT-MODE bounded service paths\n'
                text += '/etc/ctf-event-mode/runtime/ r,\n/etc/ctf-event-mode/runtime/** r,\n'
                text += f'/run/ctf-event-{kind}/ rw,\n/run/ctf-event-{kind}/** rwk,\n'
                changes[str(target)] = text
                apparmor_profiles.append(str(self.path(integration['profile'])))
            users = config['participants']
            quoted = json.dumps(users)
            changes[str(self.path('/etc/polkit-1/rules.d/00-ctf-event-mode.rules'))] = (
                '// CTF event mode: participants have no polkit administrative actions.\n'
                'polkit.addRule(function(action, subject) {\n'
                f'  if ({quoted}.indexOf(subject.user) !== -1) return polkit.Result.NO;\n'
                '});\n')
            broker_names = ['org.freedesktop.resolve1', 'org.freedesktop.NetworkManager',
                            'org.freedesktop.systemd1', 'org.freedesktop.machine1',
                            'org.freedesktop.UDisks2', 'org.freedesktop.Flatpak.SystemHelper',
                            'org.freedesktop.PackageKit']
            xml = ['<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN" "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">', '<busconfig>']
            for user in users:
                xml.append(f'  <policy user="{user}">')
                xml.extend(f'    <deny send_destination="{name}"/>' for name in broker_names)
                xml.append('  </policy>')
            xml.append('</busconfig>')
            changes[str(self.path('/etc/dbus-1/system.d/00-ctf-event-mode.conf'))] = '\n'.join(xml) + '\n'
            for filename in ('common-session', 'common-session-noninteractive'):
                pam = self.path('/etc/pam.d/' + filename)
                pam_text = pam.read_text()
                if PAM_MARKER not in pam_text:
                    pam_text = pam_text.rstrip('\n') + '\n' + PAM_MARKER + '\n' + PAM_LINE + '\n'
                changes[str(pam)] = pam_text
            changes[str(self.etc / 'login-users')] = '\n'.join(users) + '\n'
            owned = original_state.get('applied', {})
            for path in changes:
                actual = Path(path)
                self.platform.paths([actual])
                if path in owned:
                    if not actual.exists() or storage.digest(actual.read_bytes()) != owned[path]:
                        raise RuntimeError('Managed configuration changed externally: ' + path)
                elif actual.exists() and ('00-ctf-event-mode' in actual.name or actual.name == 'login-users'):
                    raise RuntimeError('Refusing to overwrite an unowned policy: ' + path)
            check_files(generation, kernel=True, platform=self.platform, live_delete=self.nft_exists())
            for index, integration in enumerate(inventory.get('apparmor', {}).get('integrations', [])):
                profile = self.path(integration['profile'])
                replacement = changes[str(self.path(integration['local']))]
                pattern = r'(?m)^\s*#include\s+(?:if\s+exists\s+)?<' + re.escape('local/' + Path(integration['profile']).name) + r'>\s*$'
                proposed, count = re.subn(pattern, lambda _: replacement, profile.read_text())
                if count != 1:
                    raise RuntimeError('Cannot safely stage the AppArmor local include: ' + str(profile))
                staged = generation / f'apparmor-{index}.profile'
                storage.atomic(staged, proposed, 0o644)
                self.platform.run(['apparmor_parser', '--skip-kernel-load', '--skip-read-cache', '--base', '/etc/apparmor.d', str(staged)])
            before = {path: storage.snapshot(path) for path in changes}
            pending = {'token': token, 'boot_id': self.platform.boot_id(), 'deadline_monotonic': time.monotonic() + seconds, 'before_state': original_state,
                       'before_files': before, 'written': {}}
            storage.json_write(self.pending_path, pending)
            # A persistent pending record also rolls back an unconfirmed reboot.
            try:
                self.platform.run(['systemd-run', '--collect', '--unit=ctf-event-rollback', f'--on-active={seconds}s',
                                   '--timer-property=AccuracySec=1s', '/usr/local/sbin/ctf-event', 'rollback', '--token', token])
                state = {**original_state, 'enabled': True, 'generation': str(generation),
                         'fingerprint': cfg.fingerprint(config), 'mode': config['mode'],
                         'identities': {name: inventory['users'][name]['uid'] for name in users},
                         'apparmor_profiles': apparmor_profiles,
                         'originals': {**{path: value for path, value in before.items() if path not in sources}, **original_state.get('originals', {})},
                         'applied': dict(original_state.get('applied', {}))}
                storage.json_write(self.state_path, state)
                self.firewall(generation)
                state['nft_signature'] = self.signature()
                for path, value in changes.items():
                    old = before[path]
                    digest = storage.digest(value.encode())
                    # Write intent first: rollback also accepts unchanged originals
                    # if a crash occurs before this individual atomic replacement.
                    pending['written'][path] = digest
                    storage.json_write(self.pending_path, pending)
                    permissions = old['mode'] if old['exists'] else 0o644
                    storage.atomic(path, value, permissions)
                    if old['exists']:
                        if os.geteuid() == 0:
                            os.chown(path, old['uid'], old['gid'])
                        for name, data in old.get('xattrs', {}).items():
                            os.setxattr(path, name, base64.b64decode(data))
                    if path not in sources:
                        state['applied'][path] = digest
                storage.json_write(self.state_path, state)
                self.switch_generation(generation)
                self.platform.run(['systemctl', 'daemon-reload'])
                self.platform.run(['systemctl', 'reload', 'dbus'])
                self.reload_apparmor(apparmor_profiles)
                self.platform.run(['systemctl', 'enable'] + SERVICES)
                self.platform.run(['systemctl', 'restart', 'ctf-event-dns.service'])
                self.platform.run(['systemctl', 'restart', 'ctf-event-proxy.service'])
                self.health()
                if time.monotonic() >= pending['deadline_monotonic']:
                    raise RuntimeError('Activation exceeded the rollback window')
            except BaseException:
                self._rollback(pending)
                raise
            return {'result': 'enabled provisionally', 'mode': config['mode'], 'rollback_seconds': seconds,
                    'next': 'Test as the participant, check browser policy pages, then sudo ctf-event confirm ' + token}

    def switch_generation(self, generation):
        current = self.etc / 'runtime/current'
        temporary = current.with_name('next-' + secrets.token_hex(4))
        temporary.symlink_to(Path(generation).name)
        os.replace(temporary, current)

    def health(self):
        for service in SERVICES[1:]:
            self.platform.run(['systemctl', 'is-active', '--quiet', service])
        if not self.nft_exists():
            raise RuntimeError('The participant firewall table is missing')
        state = self.read_state()
        if state.get('nft_signature') != self.signature():
            raise RuntimeError('The participant firewall content differs from the activated configuration')
        for path, digest in state.get('applied', {}).items():
            if not Path(path).is_file() or storage.digest(Path(path).read_bytes()) != digest:
                raise RuntimeError('Managed policy differs from activated configuration: ' + path)

    def reload_apparmor(self, profiles):
        for profile in profiles:
            self.platform.run(['apparmor_parser', '--replace', profile])

    def confirm(self, token):
        with self.lock():
            if not self.pending_path.exists():
                return {'result': 'no activation awaiting confirmation'}
            pending = json.loads(self.pending_path.read_text())
            if not secrets.compare_digest(token, pending['token']):
                raise RuntimeError('Confirmation token does not match this activation')
            if pending['boot_id'] != self.platform.boot_id() or time.monotonic() >= pending['deadline_monotonic']:
                self._rollback(pending)
                return {'result': 'confirmation window expired; previous configuration restored'}
            self.health()
            # Timer already queued? Its handler checks the same pending token under lock.
            self.pending_path.unlink()
            self.platform.run(['systemctl', 'stop', 'ctf-event-rollback.timer'], check=False)
            self.platform.run(['systemctl', 'reset-failed', 'ctf-event-rollback.service'], check=False)
            return {'result': 'confirmed; reboot persistence enabled'}

    def _restore_files(self, originals, expected):
        restore_paths = []
        for path, digest in expected.items():
            actual = Path(path)
            before = originals[path]
            if not before['exists'] and not actual.exists():
                continue
            current = storage.digest(actual.read_bytes()) if actual.is_file() else None
            original_digest = storage.digest(base64.b64decode(before['data'])) if before['exists'] else None
            if current is None or current not in (digest, original_digest):
                raise RuntimeError('Externally changed policy requires review: ' + path + '. Original backup is in /var/lib/ctf-event-mode; administrator recovery required')
            restore_paths.append(path)
        for path in restore_paths:
            storage.restore(path, originals[path])

    def _rollback(self, pending):
        self.platform.run(['systemctl', 'stop', 'ctf-event-proxy.service', 'ctf-event-dns.service'], check=False)
        self._restore_files(pending['before_files'], pending['written'])
        state = pending['before_state']
        current_profiles = self.read_state().get('apparmor_profiles', [])
        self.reload_apparmor(sorted(set(current_profiles + state.get('apparmor_profiles', []))))
        storage.json_write(self.state_path, state)
        if state['enabled']:
            self.switch_generation(state['generation'])
            self.firewall(state['generation'])
            self.platform.run(['systemctl', 'enable'] + SERVICES)
            self.platform.run(['systemctl', 'restart', 'ctf-event-dns.service', 'ctf-event-proxy.service'])
        else:
            if self.nft_exists():
                self.platform.run(['nft', 'delete', 'table', 'inet', render.TABLE])
            self.platform.run(['systemctl', 'disable'] + SERVICES, check=False)
        self.platform.run(['systemctl', 'reload', 'dbus'], check=False)
        self.pending_path.unlink(missing_ok=True)
        self.platform.run(['systemctl', 'stop', 'ctf-event-rollback.timer'], check=False)
        return {'result': 'previous configuration restored'}

    def rollback(self, token=None):
        with self.lock():
            if not self.pending_path.exists():
                return {'result': 'no pending activation; no changes'}
            pending = json.loads(self.pending_path.read_text())
            if token is not None and not secrets.compare_digest(token, pending['token']):
                return {'result': 'stale rollback token; no changes'}
            return self._rollback(pending)

    def disable(self):
        with self.lock():
            if self.pending_path.exists():
                self._rollback(json.loads(self.pending_path.read_text()))
            state = self.read_state()
            if not state['enabled']:
                if (self.var / 'installed.json').exists():
                    self.platform.run(['systemctl', 'stop', 'ctf-event-proxy.service', 'ctf-event-dns.service'], check=False)
                    self.platform.run(['systemctl', 'disable'] + SERVICES, check=False)
                    if self.nft_exists():
                        self.platform.run(['nft', 'delete', 'table', 'inet', render.TABLE])
                    self.platform.run(['systemctl', 'reload', 'dbus'], check=False)
                return {'result': 'already disabled'}
            # Verify all snapshots first, including a partially completed restore.
            self._restore_files(state['originals'], state['applied'])
            self.reload_apparmor(state.get('apparmor_profiles', []))
            storage.json_write(self.state_path, {'enabled': False, 'originals': {}, 'applied': {}})
            self.platform.run(['systemctl', 'stop', 'ctf-event-proxy.service', 'ctf-event-dns.service'], check=False)
            self.platform.run(['systemctl', 'disable'] + SERVICES, check=False)
            if self.nft_exists():
                self.platform.run(['nft', 'delete', 'table', 'inet', render.TABLE])
            self.platform.run(['systemctl', 'reload', 'dbus'], check=False)
            return {'result': 'disabled; original policies and permissions restored'}

    def boot(self):
        # Invoked by systemd while enable may hold the administrative lock.
        self.platform.root()
        if self.pending_path.exists():
            pending = json.loads(self.pending_path.read_text())
            if pending['boot_id'] != self.platform.boot_id():
                return self.rollback(pending['token'])
        state = self.read_state()
        if not state['enabled']:
            return {'result': 'inactive'}
        for name, expected_uid in state['identities'].items():
            try:
                actual = pwd.getpwnam(name).pw_uid
            except KeyError:
                raise RuntimeError('Participant identity changed; refuse participant sessions until reviewed')
            if actual != expected_uid:
                raise RuntimeError('Participant UID changed: ' + name)
        self.firewall(state['generation'])
        return {'result': 'firewall restored before participant sessions'}

    def gate_login(self, user):
        required = self.etc / 'login-users'
        if required.exists() and not user:
            return False
        if not required.exists() or user not in required.read_text().splitlines():
            return True  # Administrator sessions never depend on the event firewall.
        state = self.read_state()
        try:
            return (state['enabled'] and self.nft_exists() and
                    state.get('nft_signature') == self.signature() and
                    pwd.getpwnam(user).pw_uid == state['identities'][user])
        except (KeyError, OSError, RuntimeError):
            return False

    def status(self):
        state = self.read_state()
        result = {'installed': (self.var / 'installed.json').exists(), 'enabled': state['enabled'],
                  'mode': state.get('mode'), 'pending_confirmation': self.pending_path.exists()}
        result['services'] = {service: self.platform.run(['systemctl', 'is-active', service], check=False)[1].strip() for service in SERVICES}
        try:
            result['firewall_present'] = self.nft_exists()
            result['firewall_intact'] = result['firewall_present'] and state.get('nft_signature') == self.signature()
        except RuntimeError as error:
            result['firewall_error'] = str(error)
        result['configuration_intact'] = all(Path(path).exists() and storage.digest(Path(path).read_bytes()) == digest for path, digest in state.get('applied', {}).items())
        return result

    def export_backups(self, destination):
        with self.lock():
            destination = Path(destination).resolve()
            self.platform.paths([destination.parent])
            if destination.exists():
                raise RuntimeError('Use a new private export directory')
            destination.mkdir(mode=0o700, parents=True)
            originals = self.read_state().get('originals', {})
            if self.pending_path.exists():
                pending = json.loads(self.pending_path.read_text())
                originals = {**pending['before_files'], **originals}
            storage.json_write(destination / 'manifest.json', originals)
            for path, record in originals.items():
                if record['exists']:
                    relative = Path(path).relative_to(self.root)
                    storage.restore(destination / relative, record)
            return {'result': 'private backups exported; live files unchanged', 'destination': str(destination)}

    def uninstall(self, archive):
        self.disable()
        with self.lock():
            path = self.var / 'installed.json'
            if not path.exists():
                path = self.var / 'installing.json'
            if not path.exists():
                return {'result': 'already uninstalled'}
            installed = json.loads(path.read_text())
            archive = Path(archive).resolve()
            self.platform.paths([archive.parent])
            if archive.exists() or self.var == archive or self.var in archive.parents or self.etc == archive or self.etc in archive.parents:
                raise RuntimeError('Use a new private archive path outside toolkit directories')
            archive.mkdir(mode=0o700, parents=True)
            shutil.copytree(self.var, archive / 'state')
            if self.etc.exists():
                shutil.copytree(self.etc, archive / 'configuration', symlinks=True)
            for name, uid in installed['accounts'].items():
                inventory = self.platform.inventory(None)
                record = inventory['users'].get(name)
                if record and record['uid'] != uid:
                    raise RuntimeError('Dedicated account changed; refusing removal: ' + name)
                if record:
                    self.platform.run(['userdel', name])
                    self.platform.run(['groupdel', name], check=False)
            for name in reversed(installed['files']):
                target = Path(name)
                if target.is_symlink():
                    raise RuntimeError('Installation path changed to a symlink; refusing: ' + name)
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink(missing_ok=True)
            self.platform.run(['systemctl', 'daemon-reload'])
            shutil.rmtree(self.var)
            return {'result': 'uninstalled; system configuration restored', 'private_archive': str(archive)}
