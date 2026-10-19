import json
import shutil
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

from void_app import create_app
from void_app.db import connect

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def app(tmp_path):
    shutil.copytree(ROOT / "instance" / "assets", tmp_path / "assets")
    for name in ("hotspots.json", "asset-report.json"):
        shutil.copy(ROOT / "instance" / name, tmp_path / name)
    clock = [1800000000.0]
    application = create_app({"TESTING": True, "DATA_DIR": tmp_path, "CLOCK": lambda: clock[0]})
    application.clock = clock
    with connect(application.config["DATABASE"]) as db:
        db.execute("INSERT INTO organizers(username,password_hash) VALUES(?,?)", ("astronomer", generate_password_hash("tests-only-organizer-passphrase")))
        for identity in ("p1", "p2"):
            db.execute("INSERT INTO participants(id,code_hash) VALUES(?,?)", (identity, generate_password_hash("tests-only-access")))
        db.execute("UPDATE event SET start=?,deadline=?", (clock[0] - 100, clock[0] + 21500))
    return application


def csrf(response):
    import re
    match = re.search(r'name="csrf" value="([^"]+)"', response.get_data(as_text=True))
    assert match, response.get_data(as_text=True)
    return match.group(1)


def login(client, identity="p1"):
    token = csrf(client.get("/entry"))
    result = client.post("/entry", data={"csrf": token, "identity": identity, "password": "tests-only-access"})
    assert result.status_code == 302
    return csrf(client.get("/index.htm"))


def admin_login(client):
    token = csrf(client.get("/organizer/login"))
    result = client.post("/organizer/login", data={"csrf": token, "identity": "astronomer", "password": "tests-only-organizer-passphrase"})
    assert result.status_code == 302
    return csrf(client.get("/organizer"))


@pytest.fixture
def player(app):
    client = app.test_client()
    token = login(client)
    return client, token
