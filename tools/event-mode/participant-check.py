#!/usr/bin/env python3
"""Run as the real participant. Prints status only, never response page contents."""
import argparse
import errno
import http.client
import json
import os
import socket
import ssl
from pathlib import Path
from urllib.parse import urlsplit


def proxied(url, proxy):
    target = urlsplit(url)
    if target.scheme not in ('http', 'https') or not target.hostname or target.username:
        raise ValueError('Use an http/https URL without credentials')
    port = target.port or (443 if target.scheme == 'https' else 80)
    if target.scheme == 'https':
        connection = http.client.HTTPSConnection(proxy[0], proxy[1], timeout=8, context=ssl.create_default_context())
        connection.set_tunnel(target.hostname, port)
        path = (target.path or '/') + ('?' + target.query if target.query else '')
    else:
        connection = http.client.HTTPConnection(proxy[0], proxy[1], timeout=8)
        path = url
    try:
        connection.request('GET', path)
        response = connection.getresponse()
        return response.status
    except OSError as error:
        if 'Tunnel connection failed: 403' in str(error):
            return 403
        raise
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['balanced', 'strict'], required=True)
    parser.add_argument('--ctf-url', required=True)
    parser.add_argument('--approved-url', required=True)
    parser.add_argument('--unlisted-url', default='https://example.net/')
    parser.add_argument('--denied-host', default='chatgpt.com')
    parser.add_argument('--proxy-port', type=int, default=3129)
    args = parser.parse_args()
    if os.geteuid() < 1000:
        raise SystemExit('Run as the actual standard participant, not root')
    results = []
    def record(check, status, detail):
        results.append({'check': check, 'status': status, 'detail': detail})
    for name, url, expected in [('CTF entry', args.ctf_url, 'allow'),
                              ('approved website', args.approved_url, 'allow'),
                              ('denied AI hostname', 'https://' + args.denied_host + '/', 'deny'),
                              ('denied AI subdomain', 'https://ctf-probe.' + args.denied_host + '/', 'deny'),
                              ('unlisted website', args.unlisted_url, 'deny' if args.mode == 'strict' else 'allow'),
                              ('literal IP through proxy', 'https://1.1.1.1/', 'deny')]:
        try:
            status = proxied(url, ('127.0.0.1', args.proxy_port))
            success = status == 403 if expected == 'deny' else 200 <= status < 400
            record(name, 'PASS' if success else 'FAIL', 'HTTP status ' + str(status))
        except (OSError, ValueError, http.client.HTTPException) as error:
            record(name, 'INCONCLUSIVE', type(error).__name__ + ': check service status, certificate trust and connectivity')
    for name, address, port in [('direct IPv4 TLS', '1.1.1.1', 443),
                               ('direct IPv6 TLS', '2606:4700:4700::1111', 443),
                               ('alternate DNS TCP', '1.1.1.1', 53),
                               ('direct DNS-over-TLS', '1.1.1.1', 853)]:
        try:
            connection = socket.create_connection((address, port), timeout=2)
            connection.close()
            record(name, 'FAIL', 'Direct connection succeeded')
        except OSError as error:
            if error.errno in (errno.ENETUNREACH, errno.EADDRNOTAVAIL):
                record(name, 'INCONCLUSIVE', 'No usable route/address; repeat on an enabled network')
            else:
                record(name, 'NO CONNECTION', 'Observed failure; administrator must corroborate nft counters/status')
    for name in ['/etc/ctf-event-mode/event.json', '/etc/ctf-event-mode/ai-denylist.txt',
                 '/usr/local/sbin/ctf-event', '/etc/polkit-1/rules.d/00-ctf-event-mode.rules']:
        path = Path(name)
        if not path.exists():
            record('configuration protection', 'INCONCLUSIVE', 'Missing ' + name)
        else:
            record('configuration protection', 'FAIL' if os.access(path, os.W_OK) else 'PASS', name)
    print(json.dumps({'checks': results, 'manual_remaining': [
        'Inspect about:policies or chrome://policy, including errors and extension state',
        'Test DevTools, View Source, image/audio saving and puzzle tools',
        'Admin stops services: repeat denied/direct checks, then recover services',
        'Repeat after reboot and inspect actual firewall counters',
        'No failed connection or domain test proves all AI is inaccessible']}, indent=2))
    if any(item['status']=='FAIL' for item in results):
        return 1
    return 2 if any(item['status']=='INCONCLUSIVE' for item in results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
