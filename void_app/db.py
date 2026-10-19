import sqlite3
import os
from pathlib import Path
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS event (
 id INTEGER PRIMARY KEY CHECK(id=1), start REAL, deadline REAL
);
INSERT OR IGNORE INTO event(id) VALUES(1);
CREATE TABLE IF NOT EXISTS organizers (
 id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS participants (
 id TEXT PRIMARY KEY, code_hash TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
 ai_used INTEGER NOT NULL DEFAULT 0 CHECK(ai_used BETWEEN 0 AND 3),
 blocked INTEGER NOT NULL DEFAULT 0, completed REAL, elapsed REAL
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, role TEXT NOT NULL, subject TEXT,
 csrf TEXT NOT NULL, expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS unlocks (
 participant TEXT NOT NULL REFERENCES participants(id), stage INTEGER NOT NULL,
 timestamp REAL NOT NULL, PRIMARY KEY(participant,stage)
);
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY, participant TEXT REFERENCES participants(id),
 organizer TEXT NOT NULL, timestamp REAL NOT NULL, action TEXT NOT NULL,
 detail TEXT NOT NULL, delta INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS attempts (
 key TEXT PRIMARY KEY, window REAL NOT NULL, count INTEGER NOT NULL
);
"""


def connect(path):
    db = sqlite3.connect(path, timeout=20, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=20000")
    return db


def initialize(path):
    Path(path).touch(mode=0o600, exist_ok=True)
    if os.name != "nt":
        Path(path).chmod(0o600)
    with connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA)


@contextmanager
def transaction(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
    except BaseException:
        db.rollback()
        raise
    else:
        db.commit()
