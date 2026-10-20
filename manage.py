"""Offline organizer setup and production server entry point."""
import argparse
import getpass
import json
import os
import sqlite3
from pathlib import Path

from werkzeug.security import generate_password_hash

from void_app import create_app
from void_app.assets import import_archive, read_hotspots, readiness, sync_clue_audio, validate_box
from void_app.db import connect

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Through the Void event server")
    parser.add_argument("--data-dir", default=os.environ.get("VOID_DATA_DIR", str(ROOT / "instance")))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Create the database without creating an account")
    commands.add_parser("status", help="Show the active database path and organizer names; no secrets")
    commands.add_parser("sync-assets", help="Update the four clue clips in an existing data directory safely")
    account = commands.add_parser("organizer", help="Create an organizer or reset its password interactively")
    account.add_argument("username")
    importer = commands.add_parser("import-assets", help="Safely import original assets, preserving original bytes")
    importer.add_argument("archive", type=Path)
    hotspot = commands.add_parser("hotspot", help="Calibrate a normalized x,y,width,height box")
    hotspot.add_argument("name", choices=["door", "white_spot"])
    hotspot.add_argument("box", type=float, nargs=4)
    commands.add_parser("check", help="Check required assets and hotspot calibration")
    serve = commands.add_parser("serve", help="Run Waitress (never Flask debug mode)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--threads", type=int, default=8)
    backup = commands.add_parser("backup", help="Create a consistent SQLite backup; never copy a live WAL database alone")
    backup.add_argument("destination", type=Path)
    args = parser.parse_args()
    data = Path(args.data_dir).resolve()
    app = create_app({"DATA_DIR": data})
    if args.command == "init":
        print(f"Database initialized: {app.config['DATABASE']}")
    elif args.command == "organizer":
        args.username = args.username.strip()
        if not args.username.strip() or len(args.username) > 80:
            parser.error("Organizer username must contain 1–80 characters")
        password = getpass.getpass("Organizer password (minimum 14 characters): ")
        if len(password) < 14 or password != getpass.getpass("Confirm password: "):
            parser.error("Password too short or confirmation does not match")
        with connect(app.config["DATABASE"]) as db:
            db.execute("INSERT INTO organizers(username,password_hash) VALUES(?,?) ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash", (args.username, generate_password_hash(password)))
            db.execute("DELETE FROM sessions WHERE role='admin' AND subject=?", (args.username,))
        print(f"Organizer {args.username!r} saved in {app.config['DATABASE']}. Existing organizer sessions revoked.")
    elif args.command == "status":
        print(f"Database: {app.config['DATABASE']}")
        with connect(app.config['DATABASE']) as db:
            names = [row[0] for row in db.execute('SELECT username FROM organizers ORDER BY username')]
            count = db.execute('SELECT count(*) FROM participants').fetchone()[0]
        print('Organizers: ' + (', '.join(names) if names else '(none; run organizer USERNAME)'))
        print(f'Participants: {count}')
    elif args.command == "sync-assets":
        try:
            names = sync_clue_audio(ROOT / 'instance', data)
        except (OSError, ValueError, KeyError) as error:
            parser.error(str(error))
        print(f"Updated/verified {len(names)} clue clips in {data}; event database retained.")
    elif args.command == "import-assets":
        result = import_archive(args.archive, data)
        print(json.dumps(result, indent=2))
        for problem in readiness(data):
            print(problem)
    elif args.command == "hotspot":
        if not validate_box(args.box):
            parser.error("Box must fit inside normalized image bounds 0–1")
        spots = read_hotspots(data)
        spots[args.name] = args.box
        (data / "hotspots.json").write_text(json.dumps(spots, indent=2))
        print("Hotspot saved. Verify against the unmodified artwork at multiple window sizes.")
    elif args.command == "check":
        problems = readiness(data)
        for problem in problems:
            print(problem)
        if problems:
            raise SystemExit(1)
        print("All 16 required assets and both calibrated hotspots are present.")
    elif args.command == "backup":
        destination = args.destination.resolve()
        if destination.exists():
            parser.error("Refusing to overwrite an existing backup")
        if destination == ROOT / "void_app" / "static" or ROOT / "void_app" / "static" in destination.parents:
            parser.error("Backup destination cannot be public")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with connect(app.config["DATABASE"]) as source, sqlite3.connect(destination) as target:
            source.backup(target)
        if os.name != "nt":
            destination.chmod(0o600)
        print(f"Consistent backup created: {destination}")
    elif args.command == "serve":
        from waitress import serve
        print(f"Database: {app.config['DATABASE']}", flush=True)
        print(f"Through the Void: binding {args.host}:{args.port} with {args.threads} threads", flush=True)
        serve(app, host=args.host, port=args.port, threads=args.threads,
              expose_tracebacks=False, max_request_body_size=16384,
              clear_untrusted_proxy_headers=True, ident="Void")


if __name__ == "__main__":
    main()
