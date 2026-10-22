#!/usr/bin/env python3
"""Build only reviewed toolkit sources; never include CTF solutions or lab state."""
import argparse
import hashlib
import os
import tempfile
import zipfile
from pathlib import Path

FILES = (
    'README.md', 'ctf_event.py', 'install.sh', 'participant-check.py', 'build_bundle.py',
    'ctfmode/__init__.py', 'ctfmode/config.py', 'ctfmode/control.py',
    'ctfmode/preflight.py', 'ctfmode/render.py', 'ctfmode/storage.py',
    'examples/event.json', 'examples/inventory.json',
    'lists/ai-denylist.txt', 'lists/strict-allowlist.txt', 'lists/domain-sources.json',
    'docs/SECURITY.md', 'docs/POLICIES.md', 'docs/VERIFICATION.md', 'docs/policy-sources.json',
    'tests/conftest.py', 'tests/test_toolkit.py', 'tests/namespace_check.py', 'tests/browser_policy_check.py',
)


def build(output):
    root = Path(__file__).resolve().parent
    payloads = {}
    for name in FILES:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise RuntimeError('Missing/non-regular release source: ' + name)
        payloads[name] = path.read_bytes()
    payloads['MANIFEST.sha256'] = ''.join(hashlib.sha256(raw).hexdigest() + '  ' + name + '\n' for name, raw in payloads.items()).encode()
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as temporary:
        staged = Path(temporary.name)
    try:
        with zipfile.ZipFile(staged, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, raw in payloads.items():
                info = zipfile.ZipInfo('ctf-event-mode/' + name, date_time=(2026, 10, 22, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o100755 if name in ('install.sh', 'ctf_event.py', 'participant-check.py', 'build_bundle.py') else 0o100644) << 16
                archive.writestr(info, raw)
        with zipfile.ZipFile(staged) as archive:
            if archive.testzip() is not None:
                raise RuntimeError('Bundle CRC validation failed')
        os.replace(staged, output)
    finally:
        staged.unlink(missing_ok=True)
    print(f'{output}: {len(payloads)} files, {output.stat().st_size} bytes')
    print('SHA256: ' + hashlib.sha256(output.read_bytes()).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    build(parser.parse_args().output)
