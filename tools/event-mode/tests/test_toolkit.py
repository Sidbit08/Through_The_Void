import copy
import json
import os
import stat
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import TOOL
from ctfmode import config, render, storage
from ctfmode.control import PAM_MARKER, nft_signature, policy_changes


@pytest.mark.parametrize('host,expected', [('denied.test', True), ('sub.denied.test', True),
    ('DENIED.TEST.', True), ('notdenied.test', False), ('denied.test.evil.test', False), ('xdenied.test', False)])
def test_domain_boundaries(host, expected):
    assert config.matches(host, 'denied.test') is expected


@pytest.mark.parametrize('host', ['*.example.org', 'example.org;drop', 'http://example.org', '1.1.1.1',
    '../etc/passwd', 'foo..org', '-foo.org', 'foo.org\nbar.org', 'foo.org:443'])
def test_invalid_domain_input(host):
    with pytest.raises(config.Invalid):
        config.domain(host)


def test_validation_prevents_overlap_uid_escape_and_unsafe_addresses(settings):
    value = config.load(settings)
    inventory = json.loads((TOOL / 'examples/inventory.json').read_text())
    assert config.identity(value, inventory) == [1001, (165536, 231071)]
    inventory['proxy_uid'] = 165540
    with pytest.raises(config.Invalid, match='overlaps'):
        config.identity(value, inventory)
    raw = json.loads(settings.read_text())
    for unsafe in ('127.0.0.1', '::1', '0.0.0.0', '::ffff:192.168.1.1'):
        raw['ctf_servers'][0]['address'] = unsafe
        settings.write_text(json.dumps(raw))
        with pytest.raises(config.Invalid):
            config.load(settings)


def test_allow_and_deny_list_conflict_refused(settings):
    (settings.parent / 'allow.txt').write_text('test\n')
    with pytest.raises(config.Invalid):
        config.load(settings)
    (settings.parent / 'allow.txt').write_text('denied.test\n')
    with pytest.raises(config.Invalid, match='overlap'):
        config.load(settings)


def test_nft_is_uid_scoped_inet_and_does_not_flush_or_allow_established_escape(settings):
    value = config.load(settings)
    inventory = json.loads((TOOL / 'examples/inventory.json').read_text())
    result = render.nft(value, inventory)
    assert 'table inet ctf_event_mode' in result and 'flush' not in result
    assert '1001, 165536-231071' in result
    assert 'ct state established' not in result
    assert 'meta skuid 991 jump proxy' in result and 'meta skuid 992 jump resolver' in result
    assert 'policy accept;' in result  # Unrelated system/administrator traffic retained.
    participant = result.split('chain participant {')[1].split('chain proxy {')[0]
    assert '192.168.1.50' not in participant
    assert 'ip6' in result and 'counter drop' in participant
    value['direct_ctf'] = True
    result = render.nft(value, inventory)
    assert 'ip daddr 192.168.1.50 tcp dport { 8080 } accept' in result.split('chain participant {')[1]


def test_proxy_restricts_literals_connect_and_each_ctf_address_port_pair(settings):
    value = config.load(settings)
    value['ctf_servers'].append({'address': '2001:db8::2', 'ports': [8443]})
    result = render.squid(value, '/immutable')
    assert 'ssl_bump' not in result and 'access_log none' in result
    assert 'http_access deny CONNECT !SSL_ports' in result
    assert 'dstdomain -n' in result and 'http_access deny ip_literal' in result
    assert 'acl ctf_port_0 port 8080\n' in result and 'acl ctf_port_1 port 8443\n' in result
    assert result.index('http_access deny denied_domains') < result.index('http_access allow ctf_host_0')
    assert 'http_access allow local_client' not in result
    value['mode'] = 'balanced'
    assert 'http_access allow local_client' in render.squid(value, '/immutable')


def test_browser_policies_keep_source_devtools_and_lock_proxy_and_doh(settings):
    value = config.load(settings)
    ff = render.firefox(value, (144, 0))
    assert ff['DisableDeveloperTools'] is False
    assert ff['DNSOverHTTPS'] == {'Enabled': False, 'Locked': True}
    assert ff['Proxy']['Locked'] and ff['Proxy']['Passthrough'] == ''
    assert ff['GenerativeAI'] == {'Chatbot': False, 'Locked': True}
    assert 'AIControls' not in ff  # Avoid policies documented to delete models.
    chrome = render.chromium(value, (138, 0))
    assert chrome['DeveloperToolsAvailability'] == 1
    assert chrome['ProxySettings']['ProxyBypassList'] == '<-loopback>'
    assert chrome['DnsOverHttpsMode'] == 'off' and chrome['QuicAllowed'] is False
    assert chrome['ExtensionSettings']['*']['installation_mode'] == 'blocked'
    assert 'GenAiDefaultSettings' not in chrome  # Verified cloud-only.
    assert 'GenAILocalFoundationalModelSettings' not in chrome  # Deletes existing models.


def test_dns_mode_blocks_subdomains_and_strict_default_deny(settings):
    value = config.load(settings)
    text = render.unbound(value)
    assert 'local-zone: "." refuse' in text
    assert 'local-zone: "denied.test." always_nxdomain' in text
    assert 'local-zone: "approved.test." transparent' in text
    assert 'local-data: "ctf.event. 60 IN A 192.168.1.50"' in text
    value['mode'] = 'balanced'
    assert 'local-zone: "." refuse' not in render.unbound(value)


def test_services_bind_only_loopback_and_fail_closed_dependency():
    proxy = render.unit('proxy')
    assert 'User=ctfproxy' in proxy and 'BindsTo=ctf-event-dns.service' in proxy
    assert 'NoNewPrivileges=yes' in proxy and 'ProtectHome=yes' in proxy
    assert 'User=ctfdns' in render.unit('dns')
    assert 'ExecStop=' not in render.unit('firewall')
    assert 'Before=network-pre.target display-manager.service' in render.unit('firewall')


def test_install_is_inactive_idempotent_and_config_is_protected(lab):
    controller, platform, settings = lab
    assert not controller.read_state()['enabled']
    assert platform.table is None
    assert not any(e[0] == 'nft' for e in platform.events)
    assert not any(e[:2] == ['systemctl', 'enable'] for e in platform.events)
    assert stat.S_IMODE(controller.var.stat().st_mode) == 0o700
    assert stat.S_IMODE((controller.etc / 'event.json').stat().st_mode) == 0o600
    assert controller.install(TOOL, settings)['result'] == 'already installed'


def test_enable_arms_timer_before_firewall_and_requires_explicit_matching_confirmation(lab):
    controller, platform, settings = lab
    result = controller.enable()
    assert result['result'] == 'enabled provisionally'
    timer = next(i for i, e in enumerate(platform.events) if e[0] == 'systemd-run')
    mutation = next(i for i, e in enumerate(platform.events) if e[:2] == ['nft', '--file'])
    assert timer < mutation
    assert controller.read_state()['enabled'] and controller.pending_path.exists()
    pending = json.loads(controller.pending_path.read_text())
    with pytest.raises(RuntimeError, match='token'):
        controller.confirm('wrong-token')
    assert controller.confirm(pending['token'])['result'].startswith('confirmed')
    assert not controller.pending_path.exists()
    assert controller.enable()['result'] == 'already enabled'


def test_disable_restores_original_bytes_mode_xattrs_and_other_policies(lab):
    controller, platform, settings = lab
    target = Path(platform.data['browsers'][0]['policy_paths'][0])
    target.parent.mkdir(parents=True)
    original = b'{"policies":{"Homepage":{"URL":"https://school.test"}}}\n'
    target.write_bytes(original); target.chmod(0o640)
    os.setxattr(target, 'user.ctf-test', b'original-acl-metadata')
    pam = controller.path('/etc/pam.d/common-session')
    pam_before = pam.read_bytes()
    controller.enable()
    assert json.loads(target.read_text())['policies']['Homepage']['URL'] == 'https://school.test'
    assert PAM_MARKER in pam.read_text()
    controller.confirm(json.loads(controller.pending_path.read_text())['token'])
    assert controller.disable()['result'].startswith('disabled')
    assert target.read_bytes() == original and stat.S_IMODE(target.stat().st_mode) == 0o640
    assert os.getxattr(target, 'user.ctf-test') == b'original-acl-metadata'
    assert pam.read_bytes() == pam_before and platform.table is None
    assert controller.disable()['result'] == 'already disabled'


def test_automatic_rollback_and_failed_enable_restore_previous_state(lab):
    controller, platform, settings = lab
    platform.fail = lambda args: args == ['systemctl', 'restart', 'ctf-event-proxy.service']
    with pytest.raises(RuntimeError, match='injected'):
        controller.enable()
    assert not controller.read_state()['enabled'] and platform.table is None
    assert not controller.pending_path.exists()
    assert PAM_MARKER not in controller.path('/etc/pam.d/common-session').read_text()
    controller.enable()
    token = json.loads(controller.pending_path.read_text())['token']
    assert controller.rollback('stale-token')['result'].startswith('stale')
    assert controller.rollback(token)['result'].startswith('previous')
    assert not controller.read_state()['enabled']


def test_mode_update_rollback_restores_prior_enforcement(lab):
    controller, platform, settings = lab
    controller.enable(mode='balanced')
    controller.confirm(json.loads(controller.pending_path.read_text())['token'])
    before = platform.table
    controller.enable(mode='strict')
    assert controller.read_state()['mode'] == 'strict'
    controller.rollback()
    assert controller.read_state()['mode'] == 'balanced' and platform.table == before
    controller.disable()


def test_conflicting_policy_or_foreign_firewall_refuses_before_activation(lab):
    controller, platform, settings = lab
    target = Path(platform.data['browsers'][0]['policy_paths'][0])
    target.parent.mkdir(parents=True)
    target.write_text('{"policies":{"DisableDeveloperTools":true}}')
    with pytest.raises(RuntimeError, match='conflicts'):
        controller.enable()
    assert platform.table is None and not controller.pending_path.exists()
    target.unlink()
    platform.data['blockers'] = ['ufw manages this firewall']
    with pytest.raises(RuntimeError, match='ufw'):
        controller.enable()
    assert platform.table is None


def test_external_changes_are_preserved_and_reported_on_disable(lab):
    controller, platform, settings = lab
    controller.enable()
    controller.confirm(json.loads(controller.pending_path.read_text())['token'])
    pam = controller.path('/etc/pam.d/common-session')
    pam.write_text(pam.read_text() + '# administrator edit during event\n')
    with pytest.raises(RuntimeError, match='Externally changed'):
        controller.disable()
    assert '# administrator edit during event' in pam.read_text()


def test_unconfirmed_reboot_rolls_back_and_confirmed_boot_reloads_scoped_table(lab, monkeypatch):
    controller, platform, settings = lab
    controller.enable()
    platform.boot = 'different-boot'
    assert controller.boot()['result'].startswith('previous')
    assert not controller.read_state()['enabled']
    controller.enable()
    controller.confirm(json.loads(controller.pending_path.read_text())['token'])
    platform.table = None
    monkeypatch.setattr('ctfmode.control.pwd.getpwnam', lambda name: SimpleNamespace(pw_uid=1001))
    assert controller.boot()['result'].startswith('firewall restored')
    assert platform.table is not None


def test_missing_or_modified_firewall_blocks_participant_login_but_not_admin(lab, monkeypatch):
    controller, platform, settings = lab
    controller.enable()
    monkeypatch.setattr('ctfmode.control.pwd.getpwnam', lambda name: SimpleNamespace(pw_uid=1001))
    assert controller.gate_login('ctfplayer')
    platform.table = 'tampered rules'
    assert not controller.gate_login('ctfplayer') and controller.gate_login('administrator')
    platform.table = None
    assert not controller.gate_login('ctfplayer') and controller.gate_login('root')
    assert not controller.gate_login('')


def test_expired_confirmation_rolls_back(lab):
    controller, platform, settings = lab
    controller.enable()
    pending = json.loads(controller.pending_path.read_text())
    pending['deadline_monotonic'] = time.monotonic() - 1
    storage.json_write(controller.pending_path, pending)
    assert controller.confirm(pending['token'])['result'].startswith('confirmation window expired')
    assert not controller.read_state()['enabled']


def test_uninstall_archives_private_records_and_removes_only_toolkit(lab, tmp_path):
    controller, platform, settings = lab
    unrelated = controller.path('/etc/keep-me')
    unrelated.write_text('existing administrator configuration')
    controller.enable(); controller.rollback()
    archive = tmp_path / 'archive'
    assert controller.uninstall(archive)['result'].startswith('uninstalled')
    assert unrelated.read_text() == 'existing administrator configuration'
    assert not controller.etc.exists() and not controller.var.exists()
    assert (archive / 'state/installed.json').exists()
    assert stat.S_IMODE(archive.stat().st_mode) == 0o700
    assert 'ctfproxy' not in platform.data['users']


def test_nft_signature_ignores_live_counters_but_detects_rule_changes():
    before = {'nftables': [{'metainfo': {'version': '1'}}, {'rule': {'expr': [{'counter': {'packets': 1, 'bytes': 10}}, {'accept': None}], 'handle': 3}}]}
    after = copy.deepcopy(before)
    after['nftables'][1]['rule']['expr'][0]['counter']['packets'] = 55
    after['nftables'][1]['rule']['handle'] = 90
    assert nft_signature(json.dumps(before)) == nft_signature(json.dumps(after))
    after['nftables'][1]['rule']['expr'][1] = {'drop': None}
    assert nft_signature(json.dumps(before)) != nft_signature(json.dumps(after))


def test_staged_configuration_commits_and_rollback_restores_prior_lists(lab, tmp_path):
    controller, platform, settings = lab
    controller.enable(mode='balanced')
    controller.confirm(json.loads(controller.pending_path.read_text())['token'])
    old = (controller.etc / 'ai-denylist.txt').read_bytes()
    staged = config.load(settings)
    raw = {k: v for k, v in staged.items() if k not in ('allow_domains', 'deny_domains')}
    (settings.parent/'deny.txt').write_text('denied.test\napi.ai.test\nnew-ai.test\n')
    settings.write_text(json.dumps(raw))
    controller.enable(settings, mode='strict')
    assert 'new-ai.test' in (controller.etc/'ai-denylist.txt').read_text()
    assert config.load(controller.etc/'event.json')['mode'] == 'strict'
    controller.rollback()
    assert (controller.etc/'ai-denylist.txt').read_bytes() == old
    assert config.load(controller.etc/'event.json')['mode'] == 'balanced'


def test_backups_export_without_changing_live_pam(lab, tmp_path):
    controller, platform, settings = lab
    pam = controller.path('/etc/pam.d/common-session')
    before = pam.read_bytes()
    controller.enable()
    live = pam.read_bytes()
    destination = tmp_path/'private-originals'
    controller.export_backups(destination)
    assert pam.read_bytes() == live
    assert (destination/'etc/pam.d/common-session').read_bytes() == before
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700
    with pytest.raises(RuntimeError, match='new private'):
        controller.export_backups(destination)


def test_supported_apparmor_local_fragment_is_validated_before_timer_and_restored(lab):
    controller, platform, settings = lab
    profile = controller.path('/etc/apparmor.d/usr.sbin.unbound')
    profile.parent.mkdir(parents=True)
    profile.write_text('profile unbound /usr/sbin/unbound {\n#include <local/usr.sbin.unbound>\n}\n')
    local = profile.parent/'local/usr.sbin.unbound'
    local.parent.mkdir()
    local.write_text('# existing local policy\n/etc/unbound/** r,\n')
    before = local.read_bytes()
    platform.data['apparmor'] = {'enabled': True, 'integrations': [{'kind':'dns','profile':'/etc/apparmor.d/usr.sbin.unbound','local':'/etc/apparmor.d/local/usr.sbin.unbound'}]}
    controller.enable()
    assert '/run/ctf-event-dns/** rwk,' in local.read_text()
    validation = next(i for i,e in enumerate(platform.events) if e[:2]==['apparmor_parser','--skip-kernel-load'])
    timer = next(i for i,e in enumerate(platform.events) if e[0]=='systemd-run')
    assert validation < timer
    controller.confirm(json.loads(controller.pending_path.read_text())['token'])
    controller.disable()
    assert local.read_bytes() == before


@pytest.mark.parametrize('address', ['fe80::1%eth0', 'fe80::1%evil;flush ruleset', 'fe80::1%evil\nflush ruleset'])
def test_scoped_addresses_cannot_inject_generated_config(settings, address):
    raw = json.loads(settings.read_text());raw['ctf_servers'][0]['address']=address
    settings.write_text(json.dumps(raw))
    with pytest.raises(config.Invalid, match='without interface scopes'):
        config.load(settings)


def test_write_ahead_snapshot_recovers_a_failure_before_atomic_policy_write(lab, monkeypatch):
    controller, platform, settings = lab
    pam = controller.path('/etc/pam.d/common-session')
    before = pam.read_bytes()
    original_atomic = storage.atomic
    fail = [True]
    def atomic(path, data, mode=0o600):
        if Path(path) == pam and fail[0]:
            fail[0] = False
            raise OSError('injected before file replacement')
        return original_atomic(path, data, mode)
    monkeypatch.setattr(storage, 'atomic', atomic)
    with pytest.raises(OSError, match='injected'):
        controller.enable()
    assert pam.read_bytes() == before and platform.table is None
    assert not controller.read_state()['enabled'] and not controller.pending_path.exists()


def test_confirmation_refuses_a_modified_firewall(lab):
    controller, platform, settings = lab
    controller.enable()
    token = json.loads(controller.pending_path.read_text())['token']
    platform.table = 'modified firewall content'
    with pytest.raises(RuntimeError, match='firewall content'):
        controller.confirm(token)
    assert controller.pending_path.exists()


def test_repeated_disable_cleans_a_table_left_after_interrupted_disable(lab):
    controller, platform, settings = lab
    controller.enable()
    controller.confirm(json.loads(controller.pending_path.read_text())['token'])
    previous_table = platform.table
    controller.disable()
    platform.table = previous_table
    assert controller.disable()['result'] == 'already disabled'
    assert platform.table is None
