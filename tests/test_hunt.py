import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin

import pytest
from PIL import Image

from conftest import ROOT, admin_login, csrf, login
from void_app import create_app
from void_app.db import connect
from void_app.puzzles import ANSWERS, ASSETS, BINARY_PHRASE, HELPER_BITS, HINTS, STAGES


def progress(app, identity="p1"):
    with connect(app.config["DATABASE"]) as db:
        return db.execute("SELECT * FROM participants WHERE id=?", (identity,)).fetchone()


def set_progress(app, stage):
    with connect(app.config["DATABASE"]) as db:
        db.execute("UPDATE participants SET progress=? WHERE id='p1'", (stage,))


def test_complete_canonical_progression_and_once_only_completion(app, player):
    client, token = player
    assert client.post("/enter-void", data={"csrf": token}).status_code == 302
    for stage in range(2, 9):
        path = STAGES[stage][0]
        gate = client.get(path)
        assert "Transmission locked" in gate.text
        assert STAGES[stage][1] not in gate.text
        user, password = ANSWERS[stage]
        result = client.post(path, data={"csrf": token, "username": f" {user.upper()} ", "password": f" {password.upper()} "})
        assert result.status_code == 302
        assert progress(app)["progress"] == stage
        assert STAGES[stage][1] in client.get(path).text
    finished = progress(app)
    app.clock[0] += 10
    client.post("/thevoid.htm", data={"csrf": token, "username": "taurus", "password": "pleiades"})
    assert progress(app)["completed"] == finished["completed"]
    assert finished["elapsed"] == 100
    assert client.get("/TheWinterSky.png").status_code == 200
    with connect(app.config["DATABASE"]) as db:
        assert db.execute("SELECT count(*) FROM unlocks WHERE participant='p1'").fetchone()[0] == 8


def test_wrong_input_preserves_gate_progress_and_error_background(app, player):
    client, token = player
    client.post("/enter-void", data={"csrf": token})
    result = client.post("/level2.htm", data={"csrf": token, "username": "wrong", "password": "wrong"})
    assert result.status_code == 401
    assert "ERROR 404: Wrong input provided." in result.text
    assert "homepage-background" in result.text and 'href="/level1.htm"' in result.text
    assert 'method="post"' in result.text and "Retry" in result.text
    assert "Shrouded in Dark" not in result.text
    assert progress(app)["progress"] == 1


def test_all_future_assets_and_pages_are_protected_at_every_stage(app, player):
    client, _ = player
    for current in range(9):
        set_progress(app, current)
        for name, needed in ASSETS.items():
            result = client.get("/" + name)
            assert result.status_code == (200 if needed <= current else 404), (current, name)
            if needed > current:
                assert result.data != (ROOT / "instance" / "assets" / name).read_bytes()
        for stage, (path, title, _) in STAGES.items():
            result = client.get(path)
            if stage > current:
                assert title not in result.text
                for clue in HINTS[stage].splitlines():
                    if clue:
                        assert clue not in result.text
            if stage > current + 1:
                assert result.status_code == 404
        assert client.get("/scrambled.htm").status_code == (200 if current >= 7 else 404)


def test_url_guesses_and_cookie_edits_cannot_unlock(app, player):
    client, token = player
    for stage in range(2, 9):
        user, password = ANSWERS[stage]
        assert client.post(STAGES[stage][0], data={"csrf": token, "username": user, "password": password}).status_code == 404
    client.set_cookie("progress", "8")
    client.set_cookie("void_player", "forged-session")
    assert client.get("/thevoid.htm").status_code == 302
    assert progress(app)["progress"] == 0


def test_earlier_audio_and_linux_case_and_aliases(app, player):
    client, _ = player
    set_progress(app, 6)
    for name in ASSETS:
        if name.endswith(".mp3"):
            assert client.get("/" + name).status_code == 200
    assert client.get("/Level6.png").status_code == 200
    assert client.get("/level6.png").status_code == 404
    assert client.get("/Level1.png").status_code == 404
    assert client.get("/Level1.jpeg").mimetype == "image/jpeg"
    for alias, target in (("/Level2.htm", "/level2.htm"), ("/Brightest.htm", "/TheBrightest.htm")):
        assert client.get(alias).location == target
        assert client.get(alias, follow_redirects=True).status_code == 200
    set_progress(app, 0)
    assert client.get("/Brightest.htm", follow_redirects=True).status_code == 404


def test_gif_original_and_relative_audio_url(app, player):
    client, _ = player
    set_progress(app, 5)
    for name in ("Level5.png", "Level5.gif", "music1.mp3"):
        result = client.get("/" + name)
        assert result.data == (ROOT / "instance" / "assets" / name).read_bytes()
    gif = Image.open(ROOT / "instance" / "assets" / "Level5.gif")
    assert gif.n_frames == 16
    for relative in ("./music1.mp3", "../music1.mp3"):
        url = urljoin("http://lan/Level5.gif", relative)
        assert url == "http://lan/music1.mp3"
        assert client.get("/music1.mp3").status_code == 200


def test_binary_pattern_and_no_plaintext_in_response(app, player):
    client, _ = player
    set_progress(app, 4)
    page = client.get("/Orion.htm").text
    bits = "".join(re.findall(r'class="bit b([01])"', page))
    assert len(bits) == len(BINARY_PHRASE) * 8
    assert "".join(chr(int(bits[i:i+8], 2)) for i in range(0, len(bits), 8)) == "The Hunter's Red Shoulder"
    assert BINARY_PHRASE not in page
    assert "Betelgeuse" not in page
    assert "As the stars emerge,\nSun dims down\nCompared to the vastness,\nIncomprehensible lengths\nIt falters greatly" in page


def test_helper_cipher_exact_and_decodes_as_specified(app, player):
    decoded = "".join(chr(int(byte, 2)) for byte in HELPER_BITS.split())
    assert decoded == "rgw awcwb vwtibs rgw vykka wtw"
    rows = ["qwertyuiop", "asdfghjkl", "zxcvbnm"]
    mapping = {a: b for row in rows for a, b in zip(row, row[1:])}
    assert "".join(mapping.get(c, c) for c in decoded) == "the seven beyond the bulls eye"
    client, _ = player
    set_progress(app, 7)
    page = client.get("/scrambled.htm").text
    assert HELPER_BITS in page
    assert decoded not in page
    assert "Pleiades" not in page


def test_css_hints_only_and_page_specific(app, player):
    client, _ = player
    for stage in range(9):
        set_progress(app, stage)
        page = client.get(STAGES[stage][0]).text
        styles = "\n".join(re.findall(r"<style>(.*?)</style>", page, re.S))
        non_styles = re.sub(r"<style>.*?</style>", "", page, flags=re.S)
        for line in HINTS[stage].splitlines():
            if line:
                assert line in styles
                if not line.startswith("/"):
                    assert line not in non_styles
        assert "<!--" not in page
        for _, answer in ANSWERS.values():
            assert answer not in page.casefold()
        for extra in ("The Bull's bright eye", "the seven beyond", "rgw awcwb"):
            assert extra not in page
    static = client.get("/static/site.css").text + client.get("/static/sound.js").text
    assert "Procyon" not in static and "Seek the name" not in static


def test_event_start_and_deadline_authoritative(app, player):
    client, token = player
    with connect(app.config["DATABASE"]) as db:
        db.execute("UPDATE event SET start=NULL,deadline=NULL")
    assert client.get("/index.htm").status_code == 403
    assert client.get("/Level1.jpeg").status_code == 403
    assert client.post("/enter-void", data={"csrf": token}).status_code == 403
    with connect(app.config["DATABASE"]) as db:
        db.execute("UPDATE event SET start=?,deadline=?", (app.clock[0]-21600, app.clock[0]))
    set_progress(app, 7)
    assert client.get("/brightside.htm").status_code == 200
    result = client.post("/thevoid.htm", data={"csrf": token, "username": "Taurus", "password": "Pleiades", "browser_time": "0"})
    assert result.status_code == 403
    assert progress(app)["completed"] is None
    assert client.get("/TheWinterSky.png").status_code == 404


def test_organizer_start_once_preflight_and_persistent_deadline(app):
    client = app.test_client()
    token = admin_login(client)
    with connect(app.config["DATABASE"]) as db:
        db.execute("UPDATE event SET start=NULL,deadline=NULL")
    hotspot = Path(app.config["DATA_DIR"]) / "hotspots.json"
    saved = hotspot.read_text()
    hotspot.unlink()
    assert client.post("/organizer", data={"csrf": token, "action": "start"}).status_code == 409
    hotspot.write_text(saved)
    assert client.post("/organizer", data={"csrf": token, "action": "start"}).status_code == 302
    app.clock[0] += 60
    assert client.post("/organizer", data={"csrf": token, "action": "start"}).status_code == 409
    with connect(app.config["DATABASE"]) as db:
        record = db.execute("SELECT * FROM event").fetchone()
        assert record["deadline"] - record["start"] == 21600
        assert record["start"] == app.clock[0] - 60


def test_ai_ledger_concurrency_and_auditable_correction(app):
    admin = app.test_client()
    token = admin_login(admin)
    cookie = admin.get_cookie("void_organizer").value
    def use(_):
        client = app.test_client()
        client.set_cookie("void_organizer", cookie)
        return client.post("/organizer", data={"csrf": token, "action": "use-ai", "participant": "p1"}).status_code
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(use, range(12)))
    assert results.count(302) == 3
    assert results.count(409) == 9
    assert progress(app)["ai_used"] == 3
    assert admin.post("/organizer", data={"csrf": token, "action": "correct-ai", "participant": "p1"}).status_code == 400
    assert admin.post("/organizer", data={"csrf": token, "action": "correct-ai", "participant": "p1", "reason": "Duplicate recorded by operator"}).status_code == 302
    assert progress(app)["ai_used"] == 2
    with connect(app.config["DATABASE"]) as db:
        logs = db.execute("SELECT * FROM audit WHERE participant='p1'").fetchall()
        assert sum(row["delta"] for row in logs) == 2
        assert logs[-1]["detail"] == "Duplicate recorded by operator"
        assert all(row["organizer"] == "astronomer" for row in logs)


def test_identity_isolation_restart_logout_and_csrf(app, player):
    one, token = player
    one.post("/enter-void", data={"csrf": token})
    two = app.test_client()
    login(two, "p2")
    assert two.get("/Level1.jpeg").status_code == 404
    cookie = one.get_cookie("void_player").value
    assert one.post("/level2.htm", data={"username": "TheLesser", "password": "Procyon"}).status_code == 400
    restarted = create_app({"TESTING": True, "DATA_DIR": app.config["DATA_DIR"], "CLOCK": lambda: app.clock[0]})
    restored = restarted.test_client()
    restored.set_cookie("void_player", cookie)
    assert restored.get("/level1.htm").status_code == 200
    assert progress(app)["progress"] == 1
    assert restored.post("/logout", data={"csrf": token}).status_code == 302
    assert restored.get("/level1.htm").status_code == 302
    stolen = app.test_client()
    stolen.set_cookie("void_player", cookie)
    assert stolen.get("/level1.htm").status_code == 302


def test_organizer_separation_recovery_block_and_csv(app, player):
    player_client, token = player
    assert player_client.get("/organizer").status_code == 302
    assert player_client.post("/organizer", data={"csrf": token, "action": "use-ai", "participant": "p1"}).status_code == 400
    player_client.post("/enter-void", data={"csrf": token})
    organizer = app.test_client()
    admin_token = admin_login(organizer)
    for action in ("block", "unblock"):
        assert organizer.post("/organizer", data={"csrf": admin_token, "action": action, "participant": "p1", "reason": "Supervised policy decision"}).status_code == 302
        page = player_client.get("/level1.htm")
        if action == "block":
            assert page.status_code == 403
            assert "ERROR: A.I. will cook your Brain. Don&#39;t try this." in page.text
            assert player_client.get("/ThroughTheVoid.png").status_code == 200
            assert player_client.get("/Level1.jpeg").status_code == 403
        else:
            assert page.status_code == 200
    result = organizer.post("/organizer", data={"csrf": admin_token, "action": "recover", "participant": "p1", "reason": "Lost access code"})
    code = re.search(r"<code>([^<]+)</code>", result.text).group(1)
    assert player_client.get("/level1.htm").status_code == 302
    login_csrf = csrf(player_client.get("/entry"))
    assert player_client.post("/entry", data={"csrf": login_csrf, "identity": "p1", "password": code}).status_code == 302
    assert progress(app)["progress"] == 1
    export = organizer.get("/organizer/results.csv")
    assert export.status_code == 200 and "unlock_8_utc" in export.text
    audit = organizer.get("/organizer/audit.csv").text
    assert "Lost access code" in audit and code not in audit


@pytest.mark.parametrize("path", ["/../instance/void.sqlite3", "/instance/void.sqlite3", "/private/answers", "/void_app/puzzles.py", "/static/../puzzles.py", "/static/site.css.map", "/asset-report.json", "/requirements.txt", "/docs/ORGANIZER.md", "/Through%2F..%2Fvoid.sqlite3"])
def test_no_arbitrary_files_or_directory_listing(app, path):
    response = app.test_client().get(path)
    assert response.status_code == 404
    assert b"Traceback" not in response.data and b"SQLite format" not in response.data


def test_rate_limit_and_security_headers(app, player):
    client, token = player
    client.post("/enter-void", data={"csrf": token})
    for _ in range(15):
        assert client.post("/level2.htm", data={"csrf": token, "username": "a", "password": "b"}).status_code == 401
    response = client.post("/level2.htm", data={"csrf": token, "username": "TheLesser", "password": "Procyon"})
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    app.clock[0] += 61
    assert client.post("/level2.htm", data={"csrf": token, "username": "TheLesser", "password": "Procyon"}).status_code == 302
    response = client.get("/level2.htm")
    assert "no-store" in response.headers["Cache-Control"]
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_no_external_runtime_references_and_logout_cookie(app, player):
    client, token = player
    for stage in range(9):
        set_progress(app, stage)
        text = client.get(STAGES[stage][0]).text
        assert not re.search(r'(?:src|href)=["\'](?:https?:)?//', text)
    response = app.test_client().get("/entry")
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_archived_asset_checksums_and_hotspot_geometry():
    report = json.loads((ROOT / "instance" / "asset-report.json").read_text())
    assert set(report) == set(ASSETS)
    for name, info in report.items():
        assert hashlib.sha256((ROOT / "instance" / "assets" / name).read_bytes()).hexdigest() == info["sha256"]
    spots = json.loads((ROOT / "instance" / "hotspots.json").read_text())
    # Actual white star center identified in the supplied 1536×1024 JPEG.
    x, y, w, h = spots["white_spot"]
    assert x <= 902/1536 <= x+w and y <= 331/1024 <= y+h


def test_modified_asset_prevents_event_launch(app):
    client = app.test_client()
    token = admin_login(client)
    with connect(app.config["DATABASE"]) as db:
        db.execute("UPDATE event SET start=NULL,deadline=NULL")
    (Path(app.config["DATA_DIR"]) / "assets" / "hint.mp3").write_bytes(b"changed")
    result = client.post("/organizer", data={"csrf": token, "action": "start"})
    assert result.status_code == 409
    assert "checksum mismatch" in result.text


def test_concurrent_completion_recorded_once(app, player):
    client, token = player
    set_progress(app, 7)
    cookie = client.get_cookie("void_player").value
    def finish(_):
        other = app.test_client()
        other.set_cookie("void_player", cookie)
        return other.post("/thevoid.htm", data={"csrf": token, "username": "Taurus", "password": "Pleiades"}).status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(finish, range(8)))
    assert all(status in (200, 302) for status in results)
    assert progress(app)["completed"] == app.clock[0]
    with connect(app.config["DATABASE"]) as db:
        assert db.execute("SELECT count(*) FROM unlocks WHERE participant='p1' AND stage=8").fetchone()[0] == 1


def test_non_ascii_forged_csrf_is_rejected_without_server_error(app, player):
    client, _ = player
    assert client.post("/logout", data={"csrf": "☄"}).status_code == 400


def test_anonymous_cannot_read_any_asset(app):
    client = app.test_client()
    for name in ASSETS:
        assert client.get("/" + name).status_code == 302


def test_safe_import_rejects_traversal_duplicates_and_format_spoof(tmp_path):
    import zipfile
    from void_app.assets import import_archive
    for index, names in enumerate((["../Level2.png"], ["a/Level2.png", "b/Level2.png"], ["Level2.png"])):
        archive = tmp_path / f"bad-{index}.zip"
        with zipfile.ZipFile(archive, "w") as z:
            for name in names:
                z.writestr(name, b"not an image")
        with pytest.raises((ValueError, OSError)):
            import_archive(archive, tmp_path / f"dest-{index}")
