"""Real Squid/Unbound/nft tests, ONLY inside a new isolated network namespace.

Example (administrator on a disposable pilot/test host):
  unshare --user --map-current-user --keep-caps --net env CTF_TEST_NETNS=1 \
    python3 tests/namespace_check.py

No host policies, accounts, resolver configuration or systemd services change.
Single mapped UID: full multi-identity/PAM/systemd/reboot tests remain lab checks.
"""
import hashlib
import http.client
import http.server
import ipaddress
import json
import os
import pwd
import shutil
import socket
import socketserver
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
from ctfmode import config, render


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=15)
    if result.returncode or 'FATAL:' in result.stderr:
        raise AssertionError(str(args) + '\n' + result.stdout + result.stderr)
    return result.stdout


def dns_packet(name):
    question = b''.join(bytes([len(s)]) + s.encode() for s in name.split('.')) + b'\0\0\1\0\1'
    return struct.pack('!HHHHHH', 1234, 256, 1, 0, 0, 0) + question


def query(host, port, name):
    packet = dns_packet(name)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.settimeout(1)
        client.sendto(packet, (host, port))
        return client.recv(4096)


class DNS(socketserver.BaseRequestHandler):
    def handle(self):
        packet, server = self.request
        end = 12
        while packet[end]:
            end += packet[end] + 1
        end += 1
        kind = struct.unpack('!H', packet[end:end+2])[0]
        question = packet[12:end+4]
        answer = b'\xc0\x0c\0\1\0\1\0\0\0\x1e\0\4' + socket.inet_aton('93.184.216.34') if kind == 1 else b''
        response = packet[:2] + struct.pack('!HHHHH', 0x8180, 1, int(bool(answer)), 0, 0) + question + answer
        server.sendto(response, self.client_address)


class HTTP(http.server.BaseHTTPRequestHandler):
    payload = b'CTF asset bytes remain unchanged\x00\xff'
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Length', str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)
    def log_message(self, *args):
        pass


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        data = self.request.recv(128)
        self.request.sendall(data)


class EchoUDP(socketserver.BaseRequestHandler):
    def handle(self):
        data, channel = self.request
        channel.sendto(data, self.client_address)


class V6Server(socketserver.ThreadingTCPServer):
    address_family = socket.AF_INET6
    allow_reuse_address = True


class V6UDP(socketserver.ThreadingUDPServer):
    address_family = socket.AF_INET6


def main():
    if os.environ.get('CTF_TEST_NETNS') != '1' or {name for _, name in socket.if_nameindex()} != {'lo'}:
        raise SystemExit('REFUSED: run only inside a fresh unshare --net namespace with CTF_TEST_NETNS=1')
    output=Path(os.environ.get('CTF_TEST_RESULT',str(TOOL/'test-results/namespace.json')))
    output.parent.mkdir(parents=True,exist_ok=True)
    output.unlink(missing_ok=True)
    command('ip', 'link', 'set', 'lo', 'up')
    for address in ['93.184.216.34/32', '93.184.216.35/32', '2001:db8::20/128']:
        command('ip', 'addr', 'add', address, 'dev', 'lo')
    binary_root = Path(os.environ.get('CTF_TEST_DEB_ROOT', '/'))
    squid = shutil.which('squid')
    unbound = shutil.which('unbound')
    if not squid or not unbound or not shutil.which('nft'):
        raise SystemExit('Install squid, unbound and nftables in the test environment first')
    results = []
    def passed(name):
        results.append(name)
        print('PASS:', name, flush=True)
    servers = [socketserver.ThreadingUDPServer(('127.0.0.10', 53), DNS),
               http.server.ThreadingHTTPServer(('0.0.0.0', 80), HTTP),
               http.server.ThreadingHTTPServer(('0.0.0.0', 8080), HTTP),
               V6Server(('2001:db8::20', 8080), Echo),
               socketserver.ThreadingTCPServer(('93.184.216.34', 443), Echo),
               socketserver.ThreadingTCPServer(('93.184.216.34', 853), Echo),
               socketserver.ThreadingTCPServer(('127.0.0.10', 53), Echo),
               socketserver.ThreadingUDPServer(('93.184.216.34', 443), EchoUDP),
               V6Server(('2001:db8::20', 53), Echo),
               V6Server(('2001:db8::20', 853), Echo),
               V6UDP(('2001:db8::20', 443), EchoUDP),
               V6UDP(('2001:db8::20', 53), EchoUDP)]
    for server in servers:
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix='ctf-isolated-') as temporary:
            directory = Path(temporary)
            cfg = json.loads((TOOL / 'examples/event.json').read_text())
            cfg.update(participants=['ctfplayer'], denylist=str(directory/'deny.txt'), allowlist=str(directory/'allow.txt'),
                       dns_upstreams=['9.9.9.9'], ctf_servers=[{'address': '93.184.216.35', 'ports': [8080], 'hostname': 'ctf.event'},
                                                             {'address': '2001:db8::20', 'ports': [8080]}])
            (directory/'deny.txt').write_text('denied.test\nchatgpt.com\nopenai.com\nclaude.ai\n')
            (directory/'allow.txt').write_text('approved.test\n')
            source = directory/'event.json';source.write_text(json.dumps(cfg))
            cfg = config.load(source)
            inventory = {'users': {'ctfplayer': {'uid': os.getuid(), 'subuids': []}}, 'proxy_uid': 991, 'dns_uid': 992}
            if os.getuid() in (0, 991, 992):
                raise AssertionError('Use --map-current-user and a normal test UID >= 1000')
            live = []
            def terminate():
                while live:
                    process = live.pop()
                    process.terminate()
                    try: process.wait(timeout=8)
                    except subprocess.TimeoutExpired: process.kill();process.wait()
            try:
                for mode in ['balanced', 'strict']:
                    cfg['mode'] = mode
                    cfg['dns_upstreams'] = ['127.0.0.10']  # Isolated fixture only, never a production upstream.
                    for name, text in render.files(cfg, inventory, str(directory)).items():
                        (directory/name).write_text(text)
                    ub = directory/'unbound.conf'
                    ub.write_text(ub.read_text().replace('do-not-query-localhost: yes', 'do-not-query-localhost: no\n    local-zone: "test." nodefault').replace('/run/ctf-event-dns/unbound.pid', str(directory/'dns.pid')))
                    sq = directory/'squid.conf'
                    account = pwd.getpwuid(os.getuid())
                    content = sq.read_text().replace('cache_effective_user ctfproxy', 'cache_effective_user '+account.pw_name).replace('cache_effective_group ctfproxy', 'cache_effective_group '+account.pw_name).replace('/run/ctf-event-proxy/squid.pid', str(directory/'squid.pid')).replace('coredump_dir /run/ctf-event-proxy', 'coredump_dir '+str(directory))
                    content += f'mime_table {binary_root}/usr/share/squid/mime.conf\nicon_directory {binary_root}/usr/share/squid/icons\nunlinkd_program {binary_root}/usr/lib/squid/unlinkd\nerror_directory {binary_root}/usr/share/squid-langpack/en\n'
                    sq.write_text(content)
                    command('unbound-checkconf', str(ub))
                    command(squid, '-k', 'parse', '-f', str(sq))
                    dns_log = (directory/f'{mode}-dns.log').open('w')
                    proxy_log = (directory/f'{mode}-proxy.log').open('w')
                    live.append(subprocess.Popen([unbound, '-d', '-c', str(ub)], stdout=dns_log, stderr=dns_log))
                    live.append(subprocess.Popen([squid, '-N', '-f', str(sq)], stdout=proxy_log, stderr=proxy_log))
                    end = time.monotonic()+8
                    while True:
                        try:
                            with socket.create_connection(('127.0.0.1', cfg['proxy_port']), timeout=.2):pass
                            response = query('127.0.0.2', cfg['dns_port'], 'approved.test')
                            assert response[3] & 15 == 0, ('fixture DNS',mode,response[:12].hex(),(directory/f'{mode}-dns.log').read_text())
                            break
                        except OSError:
                            if time.monotonic()>end:
                                raise AssertionError('Daemons failed to start: '+(directory/f'{mode}-proxy.log').read_text()+(directory/f'{mode}-dns.log').read_text())
                            time.sleep(.05)
                    def request(url):
                        client = http.client.HTTPConnection('127.0.0.1', cfg['proxy_port'], timeout=5)
                        client.request('GET', url)
                        response = client.getresponse(); body = response.read(); status=response.status
                        client.close();return status,body
                    assert request('http://approved.test/')[0] == 200
                    passed(mode+': approved website through real Squid and filtering DNS')
                    for host in ['denied.test', 'sub.denied.test', 'chatgpt.com', 'sub.chatgpt.com', 'api.openai.com', 'claude.ai']:
                        assert request('http://'+host+'/')[0] == 403
                        assert query('127.0.0.2',cfg['dns_port'],host)[3] & 15 == 3
                    passed(mode+': denied domain and subdomain blocked by both proxy and DNS')
                    ordinary = request('http://ordinary.test/')[0]
                    assert ordinary == (200 if mode=='balanced' else 403)
                    passed(mode+': ordinary unlisted website '+('allowed' if mode=='balanced' else 'denied'))
                    if mode=='strict':
                        assert query('127.0.0.2',cfg['dns_port'],'ordinary.test')[3] & 15 == 5
                        passed('strict: DNS refuses unlisted hostname')
                    for host in ['http://93.184.216.34/', 'http://127.0.0.10/', 'http://0x5db8d822/']:
                        assert request(host)[0] == 403
                    passed(mode+': literal-IP HTTP and local resolver/proxy relay destinations rejected')
                    status, body = request('http://93.184.216.35:8080/asset.mp3')
                    assert status==200 and hashlib.sha256(body).digest()==hashlib.sha256(HTTP.payload).digest()
                    assert request('http://ctf.event:8080/image.png')[0]==200
                    assert request('http://ctf.event:80/')[0]==403
                    assert request('http://approved.test:8080/')[0]==403
                    passed(mode+': exact CTF address/hostname and port; binary media unmodified')
                    for destination, expected in [('approved.test:443',200),('denied.test:443',403),('approved.test:22',403),('93.184.216.34:443',403),('127.0.0.10:53',403),('[2001:db8::20]:8080',200)]:
                        with socket.create_connection(('127.0.0.1',cfg['proxy_port']),timeout=3) as client:
                            client.settimeout(3)
                            client.sendall(f'CONNECT {destination} HTTP/1.1\r\nHost: {destination}\r\n\r\n'.encode())
                            response=client.recv(8192)
                            assert int(response.split()[1])==expected,(mode,destination,response[:200])
                            if expected == 200:
                                client.sendall(b'CTF-transparent-tunnel')
                                assert client.recv(128) == b'CTF-transparent-tunnel'
                    passed(mode+': CONNECT ports, literal rejection, approved TLS tunnel, explicit IPv6 CTF exception')
                    terminate();dns_log.close();proxy_log.close()
                # The namespace has one mapped UID. Kernel tests exercise participant
                # egress; real multi-UID exemption behavior remains a lab test.
                cfg['dns_upstreams']=['9.9.9.9']
                rules=directory/'kernel.nft';rules.write_text(render.nft(cfg,inventory))
                command('nft','--check','--file',str(rules))
                command('nft','add','table','inet','ctf_test_existing')
                endpoints = [('93.184.216.34',80),('93.184.216.34',443),('93.184.216.34',853),('127.0.0.10',53),('2001:db8::20',8080),('2001:db8::20',53),('2001:db8::20',853)]
                for address,port in endpoints:
                    with socket.create_connection((address,port),timeout=1):pass
                udp_endpoints = [('93.184.216.34',443,b'quic-fixture'),('127.0.0.10',53,dns_packet('ordinary.test')),('2001:db8::20',443,b'quic-fixture'),('2001:db8::20',53,dns_packet('ordinary.test'))]
                for address,port,payload in udp_endpoints:
                    family = socket.AF_INET6 if ':' in address else socket.AF_INET
                    with socket.socket(family,socket.SOCK_DGRAM) as client:
                        client.settimeout(1);client.sendto(payload,(address,port));assert client.recv(1024)
                passed('kernel fixtures: IPv4, IPv6 and DNS/DoT endpoints reachable before restrictions')
                command('nft','--file',str(rules))
                for address,port in endpoints:
                    try:
                        client=socket.create_connection((address,port),timeout=.4);client.close()
                    except OSError:pass
                    else:raise AssertionError('Direct participant TCP bypass: '+str((address,port)))
                passed('kernel: direct participant IPv4/IPv6 HTTP, TLS, DNS and DoT blocked')
                for address,port,payload in udp_endpoints:
                    family = socket.AF_INET6 if ':' in address else socket.AF_INET
                    with socket.socket(family,socket.SOCK_DGRAM) as client:
                        client.settimeout(.3)
                        try:client.sendto(payload,(address,port));client.recv(128)
                        except OSError:pass
                        else:raise AssertionError('Direct UDP bypass')
                passed('kernel: direct alternate DNS and UDP/QUIC path blocked')
                assert not live
                with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as client:
                    client.settimeout(.3)
                    assert client.connect_ex(('93.184.216.34',443)) != 0
                passed('kernel: stopped proxy/resolver do not restore direct participant egress')
                command('nft','delete','table','inet',render.TABLE)
                for address,port in [('93.184.216.34',80),('2001:db8::20',8080)]:
                    with socket.create_connection((address,port),timeout=1):pass
                command('nft','list','table','inet','ctf_test_existing')
                passed('kernel rollback: IPv4/IPv6 restored; pre-existing sentinel table preserved')
            finally:
                terminate()
                subprocess.run(['nft','delete','table','inet',render.TABLE],capture_output=True)
                subprocess.run(['nft','delete','table','inet','ctf_test_existing'],capture_output=True)
    finally:
        for server in servers:server.shutdown();server.server_close()
    output.write_text(json.dumps({'passed':results,'limits':['single mapped UID; actual multi-identity, systemd, PAM, browser policy UI, AppArmor and reboot require a real lab PC']},indent=2)+'\n')
    print(f'{len(results)} isolated integration checks passed')


if __name__=='__main__':
    main()
