#!/usr/bin/env python3
"""Source/installed entry point; no changes occur without a named command."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
# Installed wrapper uses Python -I, so explicitly load only this root-owned tree.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ctfmode import config, preflight
from ctfmode.control import Controller, check_files, policy_changes, write_plan


def main(argv=None):
    parser = argparse.ArgumentParser(description='Reversible CTF participant mode; preflight and plan are read-only')
    commands = parser.add_subparsers(dest='command', required=True)
    inspect = commands.add_parser('preflight', help='Read-only machine and privilege inventory')
    inspect.add_argument('--config', type=Path)
    for name in ('plan', 'validate'):
        command = commands.add_parser(name)
        command.add_argument('--config', type=Path, required=True)
        command.add_argument('--inventory', type=Path, help='Offline inventory; never accepted by enable')
        command.add_argument('--mode', choices=['balanced', 'strict'])
        command.add_argument('--output', type=Path, required=True)
        if name == 'validate':
            command.add_argument('--kernel', action='store_true', help='Also run nft --check (root/CAP_NET_ADMIN required)')
    install = commands.add_parser('install', help='Install files/accounts only; no restrictions enabled')
    install.add_argument('--config', type=Path, required=True)
    enable = commands.add_parser('enable', help='Activate provisionally with an explicit timed rollback')
    enable.add_argument('--config', type=Path)
    enable.add_argument('--mode', choices=['balanced', 'strict'])
    enable.add_argument('--rollback-seconds', type=int, default=180)
    confirm = commands.add_parser('confirm', help='Administrator confirms tested activation; cancels rollback')
    confirm.add_argument('token')
    rollback = commands.add_parser('rollback', help='Restore configuration preceding the pending activation')
    rollback.add_argument('--token')
    for name in ('status', 'diagnose', 'disable', 'boot', 'gate-login'):
        commands.add_parser(name)
    uninstall = commands.add_parser('uninstall', help='Restore/remove toolkit; retain private records at a new archive path')
    uninstall.add_argument('--archive', type=Path, required=True)
    export = commands.add_parser('export-backups', help='Export readable original files for administrator recovery review')
    export.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args(argv)
    controller = Controller()
    try:
        if args.command == 'preflight':
            result = preflight.inspect(config.load(args.config) if args.config else None)
        elif args.command in ('plan', 'validate'):
            settings = config.load(args.config, args.mode)
            inventory = json.loads(args.inventory.read_text()) if args.inventory else preflight.inspect(settings)
            config.identity(settings, inventory)
            directory = write_plan(settings, inventory, args.output)
            result = {'result': 'dry-run files generated; no system settings changed', 'output': str(directory),
                      'mode': settings['mode'], 'scope': settings['participants'],
                      'note': 'IP/UID/account/browser values must be re-inspected on the target before enable'}
            if args.command == 'validate':
                result['checks'] = check_files(directory, args.kernel, live_delete=controller.nft_exists() if args.kernel else False)
        elif args.command == 'install':
            result = controller.install(Path(__file__).resolve().parent, args.config)
        elif args.command == 'enable':
            result = controller.enable(args.config, args.mode, args.rollback_seconds)
        elif args.command == 'confirm':
            result = controller.confirm(args.token)
        elif args.command == 'rollback':
            result = controller.rollback(args.token)
        elif args.command in ('status', 'diagnose'):
            controller.platform.root()
            result = controller.status()
            if args.command == 'diagnose':
                result['inventory'] = preflight.inspect(config.load(controller.etc / 'event.json'))
                result['participant_checks'] = 'Run participant-check.py as the actual participant; inspect about:policies / chrome://policy before confirmation'
        elif args.command == 'disable':
            result = controller.disable()
        elif args.command == 'uninstall':
            result = controller.uninstall(args.archive)
        elif args.command == 'export-backups':
            result = controller.export_backups(args.destination)
        elif args.command == 'boot':
            result = controller.boot()
        elif args.command == 'gate-login':
            return 0 if controller.gate_login(os.environ.get('PAM_USER', '')) else 1
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        print('CTF event mode: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
