import copy
import json
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
from ctfmode import config
from ctfmode.control import Controller


@pytest.fixture
def settings(tmp_path):
    (tmp_path / 'deny.txt').write_text('denied.test\napi.ai.test\n')
    (tmp_path / 'allow.txt').write_text('approved.test\n')
    value = json.loads((TOOL / 'examples/event.json').read_text())
    value.update(denylist='deny.txt', allowlist='allow.txt')
    path = tmp_path / 'event.json'
    path.write_text(json.dumps(value))
    return path


class FakePlatform:
    """Models systemd/nft operations; no system configuration is touched."""
    def __init__(self, root):
        self.root_path = root
        self.events = []
        self.table = None
        self.fail = None
        self.boot = 'test-boot-one'
        self.data = json.loads((TOOL / 'examples/inventory.json').read_text())
        self.data.update(blockers=[], warnings=[], distribution={'ID': 'ubuntu', 'VERSION_ID': '24.04'}, systemd=True,
                         dependencies={name: '/usr/bin/' + name for name in ['nft', 'squid', 'unbound', 'unbound-checkconf']})
        self.data['users'] = {'root': {'uid': 0}, 'ctfplayer': {'uid': 1001, 'groups': [], 'subuids': [[165536, 65536]]}}
        for browser in self.data['browsers']:
            browser['policy_paths'] = [str(root / path.lstrip('/')) for path in browser['policy_paths']]

    def root(self):
        pass

    def paths(self, paths):
        pass

    def boot_id(self):
        return self.boot

    def inventory(self, config):
        return copy.deepcopy(self.data)

    def run(self, args, check=True):
        self.events.append(args)
        if self.fail and self.fail(args):
            self.fail = None
            if check:
                raise RuntimeError('injected service failure')
            return 1, '', 'injected failure'
        if args[:2] == ['useradd', '--system']:
            name = args[-1]
            self.data['users'][name] = {'uid': 991 if name == 'ctfproxy' else 992}
        elif args[0] == 'userdel':
            self.data['users'].pop(args[1], None)
        elif args[:2] == ['nft', '-j']:
            if not self.table:
                return 1, '', 'No such file or directory'
            return 0, json.dumps({'nftables': [
                {'table': {'family': 'inet', 'name': 'ctf_event_mode', 'comment': 'ctf-event-mode-owned-v1'}},
                {'rule': {'expr': self.table, 'handle': 123, 'counter': {'packets': 12, 'bytes': 500}}}]}), ''
        elif args[:2] == ['nft', '--file']:
            self.table = Path(args[-1]).read_text().removeprefix('delete table inet ctf_event_mode\n')
        elif args[:3] == ['nft', 'delete', 'table']:
            self.table = None
        return 0, 'active\n', ''


@pytest.fixture
def lab(tmp_path, settings):
    root = tmp_path / 'root'
    root.mkdir()
    pam = root / 'etc/pam.d/common-session'
    pam.parent.mkdir(parents=True)
    pam.write_text('# original PAM\nsession required pam_unix.so\n')
    pam.chmod(0o640)
    (pam.parent / 'common-session-noninteractive').write_text('# original noninteractive PAM\nsession required pam_unix.so\n')
    platform = FakePlatform(root)
    controller = Controller(root, platform)
    controller.install(TOOL, settings)
    return controller, platform, settings
