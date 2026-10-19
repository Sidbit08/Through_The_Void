import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import time
from pathlib import Path

from flask import (Flask, Response, abort, g, redirect, render_template, request,
                   send_file)
from werkzeug.security import check_password_hash, generate_password_hash

from .assets import read_hotspots, readiness
from .db import connect, initialize, transaction
from .puzzles import ANSWERS, ASSETS, BINARY_PHRASE, HELPER_BITS, HINTS, STAGES


def create_app(config=None):
    app = Flask(__name__, static_folder=None)
    app.config.update(
        DATA_DIR=os.environ.get("VOID_DATA_DIR", str(Path(__file__).resolve().parent.parent / "instance")),
        SECURE_COOKIES=os.environ.get("VOID_HTTPS", "0") == "1",
        CLOCK=time.time, MAX_CONTENT_LENGTH=16 * 1024,
    )
    if config:
        app.config.update(config)
    data = Path(app.config["DATA_DIR"]).resolve()
    public = Path(__file__).parent / "static"
    if data == public or public in data.parents:
        raise ValueError("DATA_DIR must be outside the public directory")
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    app.config["DATABASE"] = data / "void.sqlite3"
    initialize(app.config["DATABASE"])

    def now():
        return app.config["CLOCK"]()

    def new_session(role="guest", subject=None):
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        ttl = 8 * 3600 if role == "admin" else 7 * 86400
        g.db.execute("INSERT INTO sessions VALUES(?,?,?,?,?)",
                     (hashlib.sha256(token.encode()).hexdigest(), role, subject, csrf, now() + ttl))
        g.session = dict(token_hash=hashlib.sha256(token.encode()).hexdigest(),
                         role=role, subject=subject, csrf=csrf)
        g.new_token = token

    @app.before_request
    def prepare():
        g.db = connect(app.config["DATABASE"])
        g.cookie_name = "void_organizer" if request.path.startswith("/organizer") else "void_player"
        token = request.cookies.get(g.cookie_name, "")
        g.session = g.db.execute("SELECT * FROM sessions WHERE token_hash=? AND expires>?",
                                 (hashlib.sha256(token.encode()).hexdigest(), now())).fetchone()
        g.new_token = None
        if not g.session:
            new_session()
        g.player = None
        if g.session["role"] == "participant":
            g.player = g.db.execute("SELECT * FROM participants WHERE id=?", (g.session["subject"],)).fetchone()
        if request.method == "POST":
            if not hmac.compare_digest(request.form.get("csrf", "").encode(), g.session["csrf"].encode()):
                abort(400)

    @app.after_request
    def headers(response):
        response.headers.update({
            "Cache-Control": "no-store, private, max-age=0",
            "Pragma": "no-cache", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'none'; img-src 'self'; media-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'none'; font-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
        })
        if getattr(g, "new_token", None):
            response.set_cookie(g.cookie_name, g.new_token, httponly=True,
                                secure=app.config["SECURE_COOKIES"], samesite="Lax", max_age=7 * 86400)
        return response

    @app.teardown_request
    def close(_error):
        if hasattr(g, "db"):
            g.db.close()

    @app.context_processor
    def context():
        return {"csrf": g.session["csrf"], "admin": request.path.startswith("/organizer")}

    @app.errorhandler(404)
    @app.errorhandler(400)
    @app.errorhandler(405)
    @app.errorhandler(403)
    @app.errorhandler(413)
    @app.errorhandler(500)
    def generic(error):
        return render_template("message.html", title="Transmission unavailable",
                               message="This transmission is unavailable."), error.code

    def event():
        return g.db.execute("SELECT * FROM event WHERE id=1").fetchone()

    def active(record):
        return record["start"] is not None and record["start"] <= now() < record["deadline"]

    def player_guard():
        if not g.player:
            return redirect("/entry")
        if g.player["blocked"]:
            return render_template("message.html", title="Access blocked", backdrop=True,
                                   message="ERROR: A.I. will cook your Brain. Don't try this."), 403
        if event()["start"] is None or now() < event()["start"]:
            return render_template("message.html", title="Awaiting transmission",
                                   message="The event has not started."), 403
        return None

    def admin_guard():
        if g.session["role"] != "admin":
            return redirect("/organizer/login")
        return None

    def rotate(role="guest", subject=None):
        g.db.execute("DELETE FROM sessions WHERE token_hash=?", (g.session["token_hash"],))
        new_session(role, subject)

    def throttle(scope, limit):
        # Count attempts atomically; never record supplied credentials.
        key = hashlib.sha256((scope + ":" + (request.remote_addr or "unknown")).encode()).hexdigest()
        with transaction(g.db):
            row = g.db.execute("SELECT * FROM attempts WHERE key=?", (key,)).fetchone()
            if row is None or now() - row["window"] >= 60:
                g.db.execute("INSERT OR REPLACE INTO attempts VALUES(?,?,1)", (key, now()))
                return False
            if row["count"] >= limit:
                return True
            g.db.execute("UPDATE attempts SET count=count+1 WHERE key=?", (key,))
            return False

    @app.route("/entry", methods=["GET", "POST"])
    def entry():
        error = None
        if request.method == "POST":
            if throttle("entry", 15):
                return render_template("login.html", title="Participant entry", error="Please retry in one minute."), 429
            participant = g.db.execute("SELECT * FROM participants WHERE id=?", (request.form.get("identity", "").strip(),)).fetchone()
            # Run the same expensive hash check even for an unknown ID.
            password_hash = participant["code_hash"] if participant else app.config["DUMMY_HASH"]
            valid = check_password_hash(password_hash, request.form.get("password", "").strip())
            if participant and valid:
                rotate("participant", participant["id"])
                return redirect(STAGES[participant["progress"]][0])
            error = "Unable to sign in with those details."
        return render_template("login.html", title="Participant entry", error=error)

    @app.post("/logout")
    def logout():
        rotate()
        return redirect("/entry")

    @app.route("/organizer/login", methods=["GET", "POST"])
    def organizer_login():
        error = None
        if request.method == "POST":
            if throttle("organizer-login", 8):
                return render_template("login.html", title="Organizer access", error="Please retry in one minute."), 429
            account = g.db.execute("SELECT * FROM organizers WHERE username=?", (request.form.get("identity", "").strip(),)).fetchone()
            valid = check_password_hash(account["password_hash"] if account else app.config["DUMMY_HASH"], request.form.get("password", ""))
            if account and valid:
                rotate("admin", account["username"])
                return redirect("/organizer")
            error = "Unable to sign in with those details."
        return render_template("login.html", title="Organizer access", error=error)

    @app.post("/organizer/logout")
    def organizer_logout():
        rotate()
        return redirect("/organizer/login")

    @app.get("/static/<name>")
    def static_file(name):
        if name not in ("site.css", "sound.js"):
            abort(404)
        return send_file(public / name)

    @app.get("/")
    def root():
        return redirect("/index.htm")

    @app.route("/Level2.htm", methods=["GET", "POST"])
    def alias_level2():
        return redirect("/level2.htm", code=307)

    @app.route("/Brightest.htm", methods=["GET", "POST"])
    def alias_brightest():
        return redirect("/TheBrightest.htm", code=307)

    @app.post("/enter-void")
    def enter_void():
        denied = player_guard()
        if denied:
            return denied
        with transaction(g.db):
            record = event()
            if not active(record):
                return render_template("message.html", title="Event closed", message="The event has ended."), 403
            if g.player["progress"] == 0:
                g.db.execute("UPDATE participants SET progress=1 WHERE id=? AND progress=0", (g.player["id"],))
                g.db.execute("INSERT OR IGNORE INTO unlocks VALUES(?,?,?)", (g.player["id"], 1, now()))
        return redirect("/level1.htm")

    def puzzle(stage):
        denied = player_guard()
        if denied:
            return denied
        progress = g.player["progress"]
        if stage > progress + 1:
            abort(404)
        if stage == 1 and progress == 0:
            return redirect("/index.htm")
        if stage > progress:
            error = False
            if not active(event()):
                return render_template("message.html", title="Event closed", message="The event has ended."), 403
            if request.method == "POST":
                if throttle("gate:" + g.player["id"], 15):
                    response = render_template("gate.html", title="Transmission locked", limited=True,
                                               current=STAGES[progress][0])
                    return response, 429, {"Retry-After": "60"}
                expected = ANSWERS[stage]
                supplied = (request.form.get("username", "").strip().casefold(), request.form.get("password", "").strip().casefold())
                correct = hmac.compare_digest(supplied[0].encode(), expected[0].encode()) & hmac.compare_digest(supplied[1].encode(), expected[1].encode())
                if correct:
                    with transaction(g.db):
                        # Re-read under the write lock: races cannot skip a stage,
                        # submit after expiry, or overwrite a completion time.
                        fresh = g.db.execute("SELECT * FROM participants WHERE id=?", (g.player["id"],)).fetchone()
                        stamp = now()
                        record = event()
                        if not active(record) or fresh["blocked"]:
                            abort(403)
                        if fresh["progress"] == stage - 1:
                            g.db.execute("UPDATE participants SET progress=? WHERE id=?", (stage, fresh["id"]))
                            g.db.execute("INSERT OR IGNORE INTO unlocks VALUES(?,?,?)", (fresh["id"], stage, stamp))
                            if stage == 8:
                                g.db.execute("UPDATE participants SET completed=?,elapsed=? WHERE id=? AND completed IS NULL", (stamp, stamp - record["start"], fresh["id"]))
                    return redirect(STAGES[stage][0])
                error = True
            return render_template("gate.html", title="Transmission locked", error=error, current=STAGES[progress][0]), 401 if error else 200
        path, title, image = STAGES[stage]
        if not (data / "assets" / image).is_file():
            return render_template("message.html", title="Transmission unavailable", message="The artwork is unavailable. Please contact the organizer."), 503
        hotspots = read_hotspots(data)
        box = hotspots.get("door" if stage == 0 else "white_spot", [0, 0, 0, 0])
        with (data / "asset-report.json").open() as report_file:
            image_info = json.load(report_file)[image]
        return render_template("puzzle.html", stage=stage, title=title, image=image,
                               image_ratio=image_info["width"] / image_info["height"],
                               hint=HINTS[stage], box=[n * 100 for n in box],
                               bits=[f"{ord(c):08b}" for c in BINARY_PHRASE] if stage == 4 else [])

    for stage, (path, _title, _image) in STAGES.items():
        app.add_url_rule(path, f"stage_{stage}", lambda stage=stage: puzzle(stage), methods=["GET", "POST"])

    @app.get("/scrambled.htm")
    def helper():
        denied = player_guard()
        if denied:
            return denied
        if g.player["progress"] < 7:
            abort(404)
        return render_template("helper.html", title="Seven In The Void", binary=HELPER_BITS)

    @app.get("/<name>")
    def asset(name):
        if name not in ASSETS:
            abort(404)
        # A blocked participant may still retrieve ONLY the homepage background
        # needed by the policy block panel.
        if g.player and g.player["blocked"] and name == "ThroughTheVoid.png" and event()["start"] is not None:
            pass
        else:
            denied = player_guard()
            if denied:
                return denied
            if ASSETS[name] > g.player["progress"]:
                abort(404)
        file = data / "assets" / name
        if not file.is_file():
            abort(404)
        return send_file(file, conditional=True, etag=False)

    def audit(participant, action, detail="", delta=0):
        g.db.execute("INSERT INTO audit(participant,organizer,timestamp,action,detail,delta) VALUES(?,?,?,?,?,?)",
                     (participant, g.session["subject"], now(), action, detail, delta))

    def dashboard(message=None, code=None, identity=None, status=200):
        participants = g.db.execute("SELECT * FROM participants ORDER BY id").fetchall()
        unlocks = g.db.execute("SELECT * FROM unlocks ORDER BY timestamp").fetchall()
        logs = g.db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 200").fetchall()
        return render_template("organizer.html", title="Event control", participants=participants,
                               unlocks=unlocks, logs=logs, event=event(), problems=readiness(data),
                               message=message, code=code, identity=identity, clock=now()), status

    @app.route("/organizer", methods=["GET", "POST"])
    def organizer():
        denied = admin_guard()
        if denied:
            return denied
        if request.method == "GET":
            return dashboard()
        action = request.form.get("action")
        identity = request.form.get("participant", "").strip()
        reason = request.form.get("reason", "").strip()[:500]
        if action == "start":
            problems = readiness(data)
            if problems:
                return dashboard("Cannot start: assets or hotspots are incomplete.", status=409)
            with transaction(g.db):
                record = event()
                if record["start"] is not None:
                    return dashboard("The event has already been started.", status=409)
                stamp = now()
                g.db.execute("UPDATE event SET start=?,deadline=? WHERE id=1", (stamp, stamp + 21600))
                audit(None, "start", "Six-hour event started")
            return redirect("/organizer")
        if action == "create":
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", identity):
                return dashboard("Use an ID of 1–40 letters, digits, underscores or hyphens.", status=400)
            code = secrets.token_urlsafe(18)
            code_hash = generate_password_hash(code)
            with transaction(g.db):
                if g.db.execute("SELECT 1 FROM participants WHERE id=?", (identity,)).fetchone():
                    return dashboard("That participant ID already exists.", status=409)
                g.db.execute("INSERT INTO participants(id,code_hash) VALUES(?,?)", (identity, code_hash))
                audit(identity, "create")
            return dashboard("Access code shown once. Deliver it privately.", code, identity)
        if action not in ("recover", "use-ai", "correct-ai", "block", "unblock"):
            abort(400)
        if action in ("correct-ai", "block", "unblock", "recover") and not reason:
            return dashboard("An audit reason is required.", status=400)
        code = secrets.token_urlsafe(18) if action == "recover" else None
        code_hash = generate_password_hash(code) if code else None
        with transaction(g.db):
            participant = g.db.execute("SELECT * FROM participants WHERE id=?", (identity,)).fetchone()
            if not participant:
                abort(404)
            if action == "use-ai":
                if not active(event()) or participant["blocked"]:
                    return dashboard("Prompt use requires an active event and an unblocked participant.", status=409)
                result = g.db.execute("UPDATE participants SET ai_used=ai_used+1 WHERE id=? AND ai_used<3", (identity,))
                if result.rowcount != 1:
                    return dashboard("All three AI prompts have been used.", status=409)
                audit(identity, action, "Supervised prompt recorded", 1)
            elif action == "correct-ai":
                result = g.db.execute("UPDATE participants SET ai_used=ai_used-1 WHERE id=? AND ai_used>0", (identity,))
                if result.rowcount != 1:
                    return dashboard("There is no prompt use to correct.", status=409)
                audit(identity, action, reason, -1)
            elif action == "recover":
                g.db.execute("UPDATE participants SET code_hash=? WHERE id=?", (code_hash, identity))
                g.db.execute("DELETE FROM sessions WHERE role='participant' AND subject=?", (identity,))
                audit(identity, action, reason)
            else:
                g.db.execute("UPDATE participants SET blocked=? WHERE id=?", (int(action == "block"), identity))
                audit(identity, action, reason)
        if code:
            return dashboard("Replacement access code shown once. Existing sessions revoked; progress retained.", code, identity)
        return redirect("/organizer")

    @app.get("/organizer/results.csv")
    def export():
        denied = admin_guard()
        if denied:
            return denied
        out = io.StringIO(newline="")
        writer = csv.writer(out)
        writer.writerow(["participant", "progress", "ai_used", "blocked", "completed_utc", "elapsed_seconds"] + [f"unlock_{i}_utc" for i in range(1, 9)])
        for row in g.db.execute("SELECT * FROM participants ORDER BY id"):
            stamps = {r["stage"]: r["timestamp"] for r in g.db.execute("SELECT * FROM unlocks WHERE participant=?", (row["id"],))}
            writer.writerow([csv_safe(row["id"]), row["progress"], row["ai_used"], row["blocked"], utc(row["completed"]), row["elapsed"] if row["elapsed"] is not None else ""] + [utc(stamps.get(i)) for i in range(1, 9)])
        return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": 'attachment; filename="void-results.csv"'})

    @app.get("/organizer/audit.csv")
    def export_audit():
        denied = admin_guard()
        if denied:
            return denied
        out = io.StringIO(newline="")
        writer = csv.writer(out)
        writer.writerow(["id", "participant", "organizer", "timestamp_utc", "action", "detail", "delta"])
        for row in g.db.execute("SELECT * FROM audit ORDER BY id"):
            writer.writerow([row["id"], csv_safe(row["participant"] or ""), csv_safe(row["organizer"]), utc(row["timestamp"]), row["action"], csv_safe(row["detail"]), row["delta"]])
        return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": 'attachment; filename="void-audit.csv"'})

    app.jinja_env.filters["utc"] = utc
    app.config["DUMMY_HASH"] = generate_password_hash(secrets.token_urlsafe(24))
    return app


def utc(stamp):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if stamp is not None else "—"


def csv_safe(value):
    return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value
