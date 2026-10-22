"""Deterministic generation. No TLS interception, request logging or global flush."""
import ipaddress
import json
import re

from .config import identity

TABLE = 'ctf_event_mode'
STAMP = 'ctf-event-mode-owned-v1'
PRIVATE4 = ['0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8',
            '169.254.0.0/16', '172.16.0.0/12', '192.0.0.0/24', '192.0.2.0/24',
            '192.168.0.0/16', '198.18.0.0/15', '198.51.100.0/24',
            '203.0.113.0/24', '224.0.0.0/4', '240.0.0.0/4']
PRIVATE6 = ['::/128', '::1/128', '::ffff:0:0/96', '64:ff9b::/96', '64:ff9b:1::/48',
            '100::/64', '2001:db8::/32', 'fc00::/7', 'fe80::/10', 'ff00::/8']


def nft(config, inventory):
    identities = identity(config, inventory)
    uids = ', '.join(str(i) if isinstance(i, int) else f'{i[0]}-{i[1]}' for i in identities)
    proxy, dns = inventory['proxy_uid'], inventory['dns_uid']
    pp, dp = config['proxy_port'], config['dns_port']
    ctf_rules = []
    for server in config['ctf_servers']:
        family = 'ip' if ipaddress.ip_address(server['address']).version == 4 else 'ip6'
        ports = ', '.join(map(str, server['ports']))
        ctf_rules.append(f'    {family} daddr {server["address"]} tcp dport {{ {ports} }} accept')
    upstream = []
    ctf_denies = []
    for server in config['ctf_servers']:
        family = 'ip' if ipaddress.ip_address(server['address']).version == 4 else 'ip6'
        ctf_denies.append(f'    {family} daddr {server["address"]} drop')
    for address in config['dns_upstreams']:
        family = 'ip' if ipaddress.ip_address(address).version == 4 else 'ip6'
        upstream.extend([f'    {family} daddr {address} udp dport 53 accept',
                         f'    {family} daddr {address} tcp dport 53 accept'])
    return f'''table inet {TABLE} {{
  comment "{STAMP}"
  set participants {{ type uid; flags interval; elements = {{ {uids} }}; }}
  chain output {{
    type filter hook output priority -20; policy accept;
    meta skuid @participants jump participant
    meta skuid {proxy} jump proxy
    meta skuid {dns} jump resolver
  }}
  chain participant {{
    oifname "lo" ip daddr 127.0.0.1 tcp dport {pp} accept
    oifname "lo" ip daddr 127.0.0.2 udp dport {dp} accept
    oifname "lo" ip daddr 127.0.0.2 tcp dport {dp} accept
{chr(10).join(ctf_rules) if config['direct_ctf'] else ''}
    counter drop
  }}
  chain proxy {{
    oifname "lo" ip saddr 127.0.0.1 tcp sport {pp} accept
    oifname "lo" ip daddr 127.0.0.2 udp dport {dp} accept
    oifname "lo" ip daddr 127.0.0.2 tcp dport {dp} accept
{chr(10).join(ctf_rules)}
{chr(10).join(ctf_denies)}
    ip daddr {{ {', '.join(PRIVATE4)} }} drop
    ip6 daddr {{ {', '.join(PRIVATE6)} }} drop
    tcp dport {{ 80, 443 }} accept
    counter drop
  }}
  chain resolver {{
    oifname "lo" ip saddr 127.0.0.2 udp sport {dp} accept
    oifname "lo" ip saddr 127.0.0.2 tcp sport {dp} accept
{chr(10).join(upstream)}
    counter drop
  }}
}}
'''


def squid(config, directory):
    pp, dp = config['proxy_port'], config['dns_port']
    ports = sorted({80, 443} | {port for server in config['ctf_servers'] for port in server['ports']})
    lines = [f'http_port 127.0.0.1:{pp}', 'visible_hostname ctf-event-proxy',
             'cache_effective_user ctfproxy', 'cache_effective_group ctfproxy',
             'pid_filename /run/ctf-event-proxy/squid.pid',
             'coredump_dir /run/ctf-event-proxy', 'pinger_enable off',
             'access_log none', 'cache_log /dev/null', 'cache_store_log none',
             'cache deny all', 'cache_mem 0 MB', 'maximum_object_size 0 KB',
             'forwarded_for delete', 'via off', 'host_verify_strict on', 'shutdown_lifetime 1 seconds',
             'dns_nameservers 127.0.0.2',
             'acl local_client src 127.0.0.1/32',
             'acl CONNECT method CONNECT', 'acl SSL_ports port 443',
             'acl Web_ports port 80 443',
             'acl Safe_ports port ' + ' '.join(map(str, ports)),
             'acl ip_literal dstdom_regex -n -i ^[0-9.]+$ ^0x[0-9a-f.x]+$ ^\\[?[0-9a-f:.]*:[0-9a-f:.]+\\]?$',
             'acl private_destination dst ' + ' '.join(PRIVATE4 + PRIVATE6),
             f'acl denied_domains dstdomain -n "{directory}/deny.domains"',
             'http_access deny !local_client', 'http_access deny !Safe_ports',
             'http_access deny denied_domains']
    for index, server in enumerate(config['ctf_servers']):
        address = server['address']
        literal = r'\[?' + re.escape(address) + r'\]?' if ':' in address else re.escape(address)
        hosts = '^' + literal + '$' + (' ^' + re.escape(server['hostname']) + '$' if server.get('hostname') else '')
        lines.extend([f'acl ctf_host_{index} dstdom_regex -n -i {hosts}',
                      f'acl ctf_ip_{index} dst {address}',
                      f'acl ctf_port_{index} port ' + ' '.join(map(str, server['ports'])),
                      f'http_access allow ctf_host_{index} ctf_ip_{index} ctf_port_{index}'])
    lines.extend(f'http_access deny ctf_ip_{index}' for index, _ in enumerate(config['ctf_servers']))
    lines.extend(['http_access deny !Web_ports', 'http_access deny CONNECT !SSL_ports', 'http_access deny ip_literal',
                  'http_access deny private_destination'])
    if config['mode'] == 'strict':
        if config['allow_domains']:
            lines.extend([f'acl approved_domains dstdomain -n "{directory}/allow.domains"',
                          'http_access allow approved_domains'])
    else:
        lines.append('http_access allow local_client')
    lines.append('http_access deny all')
    return '\n'.join(lines) + '\n'


def unbound(config):
    lines = ['server:', '    interface: 127.0.0.2', f'    port: {config["dns_port"]}',
             '    access-control: 127.0.0.1/32 allow', '    do-daemonize: no',
             '    username: ""', '    chroot: ""', '    directory: "/"',
             '    pidfile: "/run/ctf-event-dns/unbound.pid"',
             '    use-syslog: no', '    verbosity: 0', '    log-queries: no',
             '    log-replies: no', '    hide-identity: yes', '    hide-version: yes',
             '    module-config: "iterator"', '    do-not-query-localhost: yes',
             '    unblock-lan-zones: yes']
    if config['mode'] == 'strict':
        lines.append('    local-zone: "." refuse')
        for host in config['allow_domains']:
            lines.append(f'    local-zone: "{host}." transparent')
    for host in config['deny_domains']:
        lines.append(f'    local-zone: "{host}." always_nxdomain')
    for server in config['ctf_servers']:
        if server.get('hostname'):
            host = server['hostname']
            rr = 'A' if ipaddress.ip_address(server['address']).version == 4 else 'AAAA'
            lines.extend([f'    local-zone: "{host}." static',
                          f'    local-data: "{host}. 60 IN {rr} {server["address"]}"'])
    lines.extend(['forward-zone:', '    name: "."'])
    lines.extend(f'    forward-addr: {address}' for address in config['dns_upstreams'])
    return '\n'.join(lines) + '\n'


def firefox(config, version):
    port = config['proxy_port']
    result = {
        'DNSOverHTTPS': {'Enabled': False, 'Locked': True},
        'Proxy': {'Mode': 'manual', 'Locked': True, 'HTTPProxy': f'127.0.0.1:{port}',
                  'SSLProxy': f'127.0.0.1:{port}', 'UseHTTPProxyForAllProtocols': True,
                  'Passthrough': ''},
        'ExtensionSettings': {'*': {'installation_mode': 'blocked'}},
        'DisableDeveloperTools': False,
    }
    for extension in config['extensions']['firefox']:
        result['ExtensionSettings'][extension] = {'installation_mode': 'allowed'}
    # Verified policy. AIControls is deliberately not used: it may delete models.
    if version >= (144, 0) or (140, 4) <= version < (141, 0):
        result['GenerativeAI'] = {'Chatbot': False, 'Locked': True}
    else:
        # Documented locked preference, for older ESR. Not a claim about all AI.
        result['Preferences'] = {'browser.ml.chat.enabled': {'Value': False, 'Status': 'locked'}}
    return result


def chromium(config, version):
    result = {
        'DnsOverHttpsMode': 'off', 'QuicAllowed': False,
        'ProxySettings': {'ProxyMode': 'fixed_servers',
                          'ProxyServer': f'http=127.0.0.1:{config["proxy_port"]};https=127.0.0.1:{config["proxy_port"]}',
                          'ProxyBypassList': '<-loopback>'},
        'ExtensionSettings': {'*': {'installation_mode': 'blocked'}},
        'DeveloperToolsAvailability': 1,
    }
    for extension in config['extensions']['chromium']:
        result['ExtensionSettings'][extension] = {'installation_mode': 'allowed'}
    # GenAiDefaultSettings is cloud_only; do not pretend a local JSON enforces it.
    # AIModeSettings is supported in local policy from Chromium/Chrome 138.
    if version >= (138, 0):
        result['AIModeSettings'] = 1
    return result


def files(config, inventory, directory):
    return {'nftables.conf': nft(config, inventory),
            'squid.conf': squid(config, directory), 'unbound.conf': unbound(config),
            'deny.domains': ''.join('.' + d + '\n' for d in config['deny_domains']),
            'allow.domains': ''.join('.' + d + '\n' for d in config['allow_domains']),
            'effective.json': json.dumps(config, indent=2) + '\n'}


def unit(kind):
    if kind == 'firewall':
        return '''[Unit]
Description=CTF participant egress firewall (owned table only)
DefaultDependencies=no
After=local-fs.target
Before=network-pre.target display-manager.service
Wants=network-pre.target
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/ctf-event boot
[Install]
WantedBy=multi-user.target
'''
    proxy = kind == 'proxy'
    identity = 'ctfproxy' if proxy else 'ctfdns'
    executable = '/usr/sbin/squid -N -f /etc/ctf-event-mode/runtime/current/squid.conf' if proxy else '/usr/sbin/unbound -d -c /etc/ctf-event-mode/runtime/current/unbound.conf'
    dependency = 'ctf-event-dns.service' if proxy else 'ctf-event-firewall.service'
    return f'''[Unit]
Description=CTF event {'web proxy' if proxy else 'filtering DNS'}
Requires={dependency}
BindsTo={dependency}
After={dependency}
[Service]
Type=simple
User={identity}
Group={identity}
ExecStart={executable}
Restart=on-failure
RestartSec=2
RuntimeDirectory=ctf-event-{kind}
RuntimeDirectoryMode=0750
NoNewPrivileges=yes
LimitCORE=0
CapabilityBoundingSet={'CAP_NET_BIND_SERVICE' if not proxy else ''}
{'AmbientCapabilities=CAP_NET_BIND_SERVICE' if not proxy else ''}
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictNamespaces=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
LockPersonality=yes
[Install]
WantedBy=multi-user.target
'''
