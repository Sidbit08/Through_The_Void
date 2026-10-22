"""Atomic root-managed files and lossless metadata-aware snapshots."""
import base64
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, data, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeError('Refusing a symlink target: ' + str(path))
    if isinstance(data, str):
        data = data.encode()
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        name = temporary.name
        os.fchmod(temporary.fileno(), mode)
        temporary.write(data)
        temporary.flush()
        os.fsync(temporary.fileno())
    try:
        os.replace(name, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        Path(name).unlink(missing_ok=True)


def snapshot(path):
    path = Path(path)
    if path.is_symlink():
        raise RuntimeError('Refusing to replace an existing symlink: ' + str(path))
    if not path.exists():
        return {'exists': False}
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError('Expected a regular configuration file: ' + str(path))
    return {'exists': True, 'data': base64.b64encode(path.read_bytes()).decode(),
            'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid,
            'atime_ns': info.st_atime_ns, 'mtime_ns': info.st_mtime_ns,
            'xattrs': {name: base64.b64encode(os.getxattr(path, name)).decode() for name in os.listxattr(path)}}


def restore(path, record):
    path = Path(path)
    if not record['exists']:
        if path.is_symlink():
            raise RuntimeError('Refusing to remove changed symlink: ' + str(path))
        path.unlink(missing_ok=True)
        return
    atomic(path, base64.b64decode(record['data']), record['mode'])
    if os.geteuid() == 0:
        os.chown(path, record['uid'], record['gid'])
    for name, data in record.get('xattrs', {}).items():
        os.setxattr(path, name, base64.b64decode(data))
    os.utime(path, ns=(record['atime_ns'], record['mtime_ns']))


def json_write(path, value, mode=0o600):
    atomic(path, json.dumps(value, indent=2, sort_keys=True) + '\n', mode)


def secure_ancestors(path):
    """Production checks; root must never follow participant-writable ancestors."""
    path = Path(path)
    for parent in [path] + list(path.parents):
        if not parent.exists():
            continue
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
            raise RuntimeError('Root-owned, non-writable, non-symlink path required: ' + str(parent))
