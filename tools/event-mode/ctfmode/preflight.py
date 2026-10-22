"""Read-only inventory. Unknown enforcement conditions are blockers, not passes."""
import grp
import json
import os
import pwd
import re
import shutil
import subprocess
from pathlib import Path

from . import render

DANGEROUS = {'root', 'sudo', 'wheel', 'admin', 'docker', 'lxd', 'incus', 'libvirt',
             'disk', 'shadow', 'ctfproxy', 'ctfdns'}


def run(args, timeout=12):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                                env={**os.environ, 'LC_ALL': 'C'})
        return result.returncode, result.stdout, result.stderr
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, '', str(error)


def read(path):
    try:
        return Path(path).read_text()
    except OSError:
        return ''


def active(service):
    return run(['systemctl', 'is-active', '--quiet', service])[0] == 0


def enabled(service):
    return run(['systemctl', 'is-enabled', '--quiet', service])[0] == 0


def browser_inventory():
    browsers = []
    for binary, kind, directory in [('firefox', 'firefox', '/etc/firefox/policies'),
                                    ('firefox-esr', 'firefox', '/etc/firefox/policies'),
                                    ('chromium', 'chromium', '/etc/chromium/policies/managed'),
                                    ('google-chrome', 'chromium', '/etc/opt/chrome/policies/managed'),
                                    ('google-chrome-stable', 'chromium', '/etc/opt/chrome/policies/managed')]:
        executable = shutil.which(binary)
        if not executable:
            continue
        real = Path(executable).resolve()
        stub = read(executable)[:1000] if real.is_file() and real.stat().st_size < 20000 else ''
        snap = '/snap/' in executable or real.name == 'snap' or 'snap run' in stub or 'snap install' in stub
        code, output, _ = (127, '', '') if snap else run([executable, '--version'])
        version = re.search(r'(\d+)\.(\d+)', output)
        parsed = [int(version[1]), int(version[2])] if version else [0, 0]
        paths = [directory + ('/policies.json' if kind == 'firefox' else '/90-ctf-event-mode.json')]
        if kind == 'firefox':
            candidates = [real.parent / 'distribution/policies.json',
                          Path('/usr/lib/firefox/distribution/policies.json'),
                          Path('/usr/lib/firefox-esr/distribution/policies.json')]
            paths = list(dict.fromkeys([str(p) for p in candidates if p.is_file()] or paths))
        if any(b['executable'] == str(real) for b in browsers):
            continue
        browsers.append({'name': binary, 'kind': kind, 'executable': str(real),
                         'version': parsed, 'packaging': 'snap-unsupported' if snap else 'native',
                         'policy_paths': paths, 'version_readable': code == 0})
    return browsers


def inspect(config=None):
    report = {'blockers': [], 'warnings': [], 'users': {}, 'browsers': browser_inventory()}
    errors, warnings = report['blockers'], report['warnings']
    os_release = dict(re.findall(r'^([A-Z_]+)="?([^"\n]+)"?$', read('/etc/os-release'), re.M))
    report['distribution'] = os_release
    if os_release.get('ID') not in ('ubuntu', 'debian'):
        errors.append('Unsupported distribution: pilot support is limited to Ubuntu/Debian with systemd')
    report['systemd'] = Path('/run/systemd/system').is_dir()
    if not report['systemd']:
        errors.append('An active systemd system is required; containers without it cannot enable event mode')
    report['services'] = {name: {'active': active(name), 'enabled': enabled(name)} for name in
                          ['NetworkManager', 'systemd-networkd', 'systemd-resolved', 'dnsmasq',
                           'ufw', 'firewalld', 'nftables', 'netfilter-persistent', 'docker', 'libvirtd', 'incus']}
    report['resolver'] = {'resolv_conf_target': str(Path('/etc/resolv.conf').resolve()),
                          'nameservers': re.findall(r'^nameserver\s+(\S+)', read('/etc/resolv.conf'), re.M),
                          'nss_hosts': next((s for s in read('/etc/nsswitch.conf').splitlines() if s.startswith('hosts:')), '')}
    for manager in ('ufw', 'firewalld', 'nftables', 'netfilter-persistent'):
        if any(report['services'][manager].values()) or (manager == 'ufw' and 'ENABLED=yes' in read('/etc/ufw/ufw.conf')):
            errors.append(f'{manager} manages this firewall. Automatic integration is unsupported; do not disable/flush it blindly')
    report['legacy_firewalls'] = {}
    for binary, table_path in [('iptables-legacy-save', '/proc/net/ip_tables_names'),
                               ('ip6tables-legacy-save', '/proc/net/ip6_tables_names')]:
        if shutil.which(binary):
            code, rules, stderr = run([binary])
            meaningful = [line for line in rules.splitlines() if line.startswith('-A ') or (line.startswith(':') and ' ACCEPT ' not in line)]
            report['legacy_firewalls'][binary] = {'readable': code == 0, 'nontrivial_lines': len(meaningful)}
            if code:
                errors.append('Cannot inspect legacy firewall: ' + binary)
            elif meaningful:
                errors.append('Existing legacy firewall rules require reviewed integration: ' + binary)
        elif read(table_path).strip():
            errors.append('Legacy firewall tables present but inspection command is unavailable: ' + binary)
    code, raw, stderr = run(['nft', '-j', 'list', 'ruleset'])
    report['firewall_readable'] = code == 0
    report['firewall_tables'] = []
    if code:
        errors.append('Cannot inspect nftables (root/CAP_NET_ADMIN and nft are required)')
    else:
        try:
            tables = [x['table'] for x in json.loads(raw).get('nftables', []) if 'table' in x]
            report['firewall_tables'] = tables
            for table in tables:
                if table.get('family') != 'inet' or table.get('name') != render.TABLE:
                    errors.append('Existing foreign nftables table: ' + str(table.get('family')) + ' ' + str(table.get('name')) + '. Safe integration requires administrator review')
                elif table.get('comment') != render.STAMP:
                    errors.append('The ctf_event_mode table exists without our ownership marker')
        except (ValueError, TypeError):
            errors.append('Could not parse nftables inventory')
    report['dependencies'] = {p: shutil.which(p) for p in ['python3', 'nft', 'squid', 'unbound',
                              'unbound-checkconf', 'systemctl', 'systemd-run', 'useradd', 'userdel']}
    for name, executable in report['dependencies'].items():
        if not executable:
            errors.append('Missing prerequisite: ' + name)
    report['apparmor'] = {'enabled': read('/sys/module/apparmor/parameters/enabled').strip() == 'Y', 'integrations': []}
    if report['apparmor']['enabled']:
        for kind, filename in [('dns', 'usr.sbin.unbound'), ('proxy', 'usr.sbin.squid'), ('proxy', 'usr.sbin.squid-gnutls')]:
            profile = Path('/etc/apparmor.d') / filename
            if not profile.exists():
                continue
            text = read(profile)
            local = 'local/' + filename
            if not re.search(r'#include\s+(?:if\s+exists\s+)?<' + re.escape(local) + r'>', text):
                errors.append('AppArmor profile has no supported local include: ' + str(profile))
            elif not shutil.which('apparmor_parser'):
                errors.append('apparmor_parser is needed to validate/reload the existing service profile')
            else:
                report['apparmor']['integrations'].append({'kind': kind, 'profile': str(profile), 'local': '/etc/apparmor.d/' + local})
    subordinate = {}
    for line in read('/etc/subuid').splitlines():
        try:
            name, start, count = line.split(':')
            subordinate.setdefault(name, []).append([int(start), int(count)])
        except ValueError:
            errors.append('Invalid /etc/subuid entry; manual review required')
    for user in pwd.getpwall():
        groups = []
        for gid in os.getgrouplist(user.pw_name, user.pw_gid):
            try:
                groups.append(grp.getgrgid(gid).gr_name)
            except KeyError:
                groups.append(str(gid))
        report['users'][user.pw_name] = {'uid': user.pw_uid, 'gid': user.pw_gid,
                                        'groups': sorted(groups), 'shell': user.pw_shell,
                                        'subuids': subordinate.get(user.pw_name, subordinate.get(str(user.pw_uid), []))}
    report['candidate_participants'] = [n for n, u in report['users'].items()
                                        if 1000 <= u['uid'] < 60000 and u['shell'] not in ('/bin/false', '/usr/sbin/nologin')]
    report['offline_assistants'] = {
        'executables': {name: shutil.which(name) for name in ['ollama', 'llama-server', 'local-ai', 'gpt4all', 'lmstudio', 'llm'] if shutil.which(name)},
        'services': [name for name in ['ollama', 'local-ai', 'llama-server'] if active(name)],
        'note': 'Metadata-only candidates; no user files are searched or deleted. Absence is not proof of no offline AI.',
    }
    for name, key in [('ctfproxy', 'proxy_uid'), ('ctfdns', 'dns_uid')]:
        report[key] = report['users'].get(name, {}).get('uid')
    if config:
        for name in config['participants']:
            user = report['users'].get(name)
            if not user:
                errors.append('Participant does not exist: ' + name)
                continue
            if user['uid'] < 1000:
                errors.append('Participant is not a standard unprivileged account: ' + name)
            if any(other != name and record['uid'] == user['uid'] for other, record in report['users'].items()):
                errors.append('Participant UID aliases another account: ' + name)
            dangerous = sorted(set(user['groups']) & DANGEROUS)
            if dangerous:
                errors.append(f'{name} belongs to root-equivalent groups {dangerous}; use a separate standard event account')
            if os.geteuid() == 0 and shutil.which('sudo'):
                code, out, err = run(['sudo', '-n', '-l', '-U', name])
                if code == 0:
                    errors.append(f'{name} has sudo rights; reliable enforcement is unavailable until an administrator removes them or selects another account')
                elif 'not allowed to run sudo' not in out + err and 'may not run sudo' not in out + err:
                    errors.append('Cannot establish sudo rights for ' + name)
            elif os.geteuid() != 0:
                warnings.append('Sudo rights require a root preflight: ' + name)
            for start, count in user['subuids']:
                for other, value in report['users'].items():
                    if other not in config['participants'] and start <= value['uid'] < start + count:
                        errors.append(f'{name} subordinate UIDs overlap {other}; unsafe identity scope')
    if Path('/etc/doas.conf').exists():
        errors.append('doas configuration requires manual privilege review; automatic integration unsupported')
    for policy in Path('/etc/polkit-1/rules.d').glob('*.rules'):
        if policy.name < '00-ctf-event-mode.rules':
            errors.append('A preceding custom polkit rule requires review: ' + str(policy))
    if not all(Path('/etc/pam.d/' + name).is_file() for name in ('common-session', 'common-session-noninteractive')):
        errors.append('Debian/Ubuntu common-session PAM layout is required for the participant-only boot safety gate')
    for path in ['/var/run/docker.sock', '/run/podman/podman.sock', '/var/snap/lxd/common/lxd/unix.socket', '/run/libvirt/libvirt-sock']:
        if Path(path).exists():
            warnings.append('Privileged local broker present; administrator must check participant ACL access: ' + path)
            if config and os.geteuid() == 0:
                for name in config['participants']:
                    if name in report['users']:
                        uid = report['users'][name]['uid']
                        # getfacl is diagnostic; groups above are mandatory blockers.
                        code, acl, _ = run(['getfacl', '-cp', path])
                        if code or re.search(r'^user:' + re.escape(name) + r':[rw]', acl, re.M) or re.search(r'^other::.*[rw]', acl, re.M):
                            errors.append(f'Cannot exclude {name} from privileged broker {path}; review its ACL')
    if not report['browsers']:
        errors.append('No supported native Firefox/Chromium/Chrome browser detected')
    for browser in report['browsers']:
        if browser['packaging'] != 'native' or not browser['version_readable']:
            errors.append(browser['name'] + ': unsupported Snap/unreadable browser. Install a supported native browser or obtain a reviewed packaging integration')
        elif browser['version'][0] < 128:
            errors.append(browser['name'] + ': update to version 128 or later before the pilot')
    report['existing_policy_files'] = []
    for directory in ['/etc/opt/chrome/policies/enrollment', '/etc/chromium/policies/enrollment']:
        if Path(directory).exists() and any(Path(directory).iterdir()):
            errors.append('Enterprise cloud enrollment requires an IT-reviewed policy integration: ' + directory)
    for root in ['/etc/firefox/policies', '/usr/lib/firefox/distribution', '/usr/lib/firefox-esr/distribution',
                 '/etc/chromium/policies', '/etc/opt/chrome/policies']:
        if Path(root).exists():
            report['existing_policy_files'].extend(str(p) for p in Path(root).rglob('*.json'))
    warnings.extend([
        'No scan proves absence of offline models, unknown AI services, or administrator credentials',
        'NSS/Varlink system resolver brokers may still resolve names; proxy destination ACLs independently enforce web access. This toolkit does not replace the system resolver',
        'AppArmor, enterprise policies, local sockets and existing assistants need one-PC pilot review',
    ])
    report['safe_to_enable'] = not errors
    return report
