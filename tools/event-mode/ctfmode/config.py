"""Strict input validation; input files never become shell commands."""
import hashlib
import ipaddress
import json
import re
from pathlib import Path


class Invalid(ValueError):
    pass


def domain(value):
    value = value.strip().lower().rstrip('.')
    if value.startswith('.'):
        value = value[1:]
    if len(value) > 253 or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', value):
        raise Invalid(f'Invalid ASCII hostname (use IDNA/punycode): {value!r}')
    if '.' not in value or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in value.split('.')):
        raise Invalid(f'Invalid hostname: {value!r}')
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise Invalid('Literal IP addresses belong in ctf_servers, not domain lists')


def matches(host, base):
    host, base = host.lower().rstrip('.'), base.lower().rstrip('.')
    return host == base or host.endswith('.' + base)


def domains(path):
    result = []
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.split('#', 1)[0].strip()
        if line:
            try:
                result.append(domain(line))
            except Invalid as error:
                raise Invalid(f'{path}:{number}: {error}') from error
    return sorted(set(result))


def load(path, mode=None):
    path = Path(path).resolve()
    config = json.loads(path.read_text())
    allowed = {'mode', 'participants', 'proxy_port', 'dns_port', 'dns_upstreams',
               'ctf_servers', 'direct_ctf', 'denylist', 'allowlist', 'extensions'}
    if not isinstance(config, dict) or set(config) - allowed:
        raise Invalid('Unknown configuration keys')
    config['mode'] = mode or config.get('mode', 'strict')
    if config['mode'] not in ('balanced', 'strict'):
        raise Invalid('mode must be balanced or strict')
    users = config.get('participants', [])
    if not isinstance(users, list) or not users or any(not isinstance(u, str) or not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', u) for u in users):
        raise Invalid('participants must name at least one existing standard Linux account')
    if len(users) != len(set(users)) or any(u in ('root', 'ctfproxy', 'ctfdns') for u in users):
        raise Invalid('Duplicate or privileged participant identity')
    config['participants'] = sorted(users)
    for key, default in [('proxy_port', 3129)]:
        value = config.setdefault(key, default)
        if type(value) is not int or not 1024 <= value <= 65535:
            raise Invalid(f'{key} must be an unprivileged TCP/UDP port')
    if config.setdefault('dns_port', 53) != 53:
        raise Invalid('dns_port must be 53 on dedicated loopback 127.0.0.2; Squid requires a standard-port nameserver')
    upstreams = config.setdefault('dns_upstreams', ['9.9.9.9', '149.112.112.112'])
    if not isinstance(upstreams, list) or not upstreams:
        raise Invalid('At least one explicit DNS upstream IP is required')
    for address in upstreams:
        if not isinstance(address, str) or '%' in address:
            raise Invalid('DNS upstreams must be plain IP address strings without interface scopes')
        ip = ipaddress.ip_address(address)
        mapped = isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped
        if ip.is_loopback or ip.is_unspecified or ip.is_multicast or mapped:
            raise Invalid('DNS upstream must be a real unicast address, not a local stub')
    config['dns_upstreams'] = sorted(set(str(ipaddress.ip_address(a)) for a in upstreams))
    servers = config.setdefault('ctf_servers', [])
    if not isinstance(servers, list) or not servers:
        raise Invalid('Configure at least one exact CTF server address and its ports')
    for server in servers:
        if not isinstance(server, dict) or set(server) - {'address', 'ports', 'hostname'}:
            raise Invalid('CTF servers accept only address, ports, and optional hostname')
        if not isinstance(server.get('address'), str) or '%' in server['address']:
            raise Invalid('CTF addresses must be plain IP strings without interface scopes')
        ip = ipaddress.ip_address(server['address'])
        if ip.is_loopback or ip.is_unspecified or ip.is_multicast or (isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped):
            raise Invalid('CTF server must be an exact non-loopback unicast IP')
        server['address'] = str(ip)
        ports = server.get('ports')
        if not isinstance(ports, list) or not ports or any(type(p) is not int or not 1 <= p <= 65535 for p in ports):
            raise Invalid('CTF server needs explicit valid TCP ports')
        server['ports'] = sorted(set(ports))
        if server.get('hostname'):
            if not isinstance(server['hostname'], str):
                raise Invalid('CTF hostname must be a string')
            server['hostname'] = domain(server['hostname'])
    direct = config.setdefault('direct_ctf', False)
    if type(direct) is not bool:
        raise Invalid('direct_ctf must be a boolean')
    for key, default in [('denylist', '../lists/ai-denylist.txt'), ('allowlist', '../lists/strict-allowlist.txt')]:
        name = config.setdefault(key, default)
        if not isinstance(name, str):
            raise Invalid(f'{key} must be a filename')
        config[key] = str((path.parent / name).resolve())
    config['deny_domains'] = domains(config['denylist'])
    config['allow_domains'] = domains(config['allowlist'])
    if not config['deny_domains']:
        raise Invalid('An empty AI denylist is not an event-mode configuration')
    for allow in config['allow_domains']:
        for deny in config['deny_domains']:
            if matches(allow, deny) or matches(deny, allow):
                raise Invalid(f'Allowlist/denylist overlap: {allow}, {deny}')
    extensions = config.setdefault('extensions', {'firefox': [], 'chromium': []})
    if not isinstance(extensions, dict) or set(extensions) - {'firefox', 'chromium'}:
        raise Invalid('extensions supports firefox and chromium ID lists only')
    for browser in ('firefox', 'chromium'):
        ids = extensions.setdefault(browser, [])
        pattern = r'[a-z]{32}' if browser == 'chromium' else r'[A-Za-z0-9_.@{}-]{1,160}'
        if not isinstance(ids, list) or any(not isinstance(i, str) or not re.fullmatch(pattern, i) for i in ids):
            raise Invalid(f'Invalid {browser} extension ID')
    return config


def identity(config, inventory):
    users = inventory['users']
    uids = []
    for name in config['participants']:
        if name not in users:
            raise Invalid(f'Participant account does not exist: {name}')
        uid = users[name]['uid']
        if type(uid) is not int or uid < 1000 or uid >= 2**32 - 1:
            raise Invalid(f'Not a standard participant UID: {name}')
        uids.append(uid)
        for start, count in users[name].get('subuids', []):
            if start < 1000 or count < 1 or start + count >= 2**32 - 1:
                raise Invalid('Invalid subordinate UID mapping')
            uids.append((start, start + count - 1))
    for role in ('proxy_uid', 'dns_uid'):
        uid = inventory.get(role)
        if type(uid) is not int or uid <= 0 or any(uid == item if isinstance(item, int) else item[0] <= uid <= item[1] for item in uids):
            raise Invalid(f'Dedicated {role} is missing or overlaps a participant identity')
    if inventory['proxy_uid'] == inventory['dns_uid']:
        raise Invalid('Proxy and DNS must use separate service identities')
    return uids


def fingerprint(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
