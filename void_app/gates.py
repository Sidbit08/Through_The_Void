"""Persistent participant/destination limits. Call inside a write transaction."""
import math

FAILURE_LIMIT = 5
COOLDOWN_SECONDS = 60


def record(db, participant, gate, stamp, event, failures, cooldown_until=None):
    db.execute("INSERT INTO gate_events(participant,gate,timestamp,event,failures,cooldown_until) VALUES(?,?,?,?,?,?)",
               (participant, gate, stamp, event, failures, cooldown_until))


def state(db, participant, gate, stamp):
    row = db.execute("SELECT failures,cooldown_until FROM gate_attempts WHERE participant=? AND gate=?",
                     (participant, gate)).fetchone()
    if row is None:
        return {"failures": 0, "cooldown_until": None}
    if row["cooldown_until"] is not None and row["cooldown_until"] <= stamp:
        db.execute("DELETE FROM gate_attempts WHERE participant=? AND gate=?", (participant, gate))
        record(db, participant, gate, stamp, "cooldown-expired", 0)
        return {"failures": 0, "cooldown_until": None}
    return dict(row)


def remaining(current, stamp):
    return max(0, math.ceil((current["cooldown_until"] or stamp) - stamp))


def fail(db, participant, gate, stamp, current):
    failures = current["failures"] + 1
    until = stamp + COOLDOWN_SECONDS if failures == FAILURE_LIMIT else None
    db.execute("INSERT INTO gate_attempts VALUES(?,?,?,?) ON CONFLICT(participant,gate) DO UPDATE SET failures=excluded.failures,cooldown_until=excluded.cooldown_until",
               (participant, gate, failures, until))
    record(db, participant, gate, stamp, "failure", failures, until)
    if until is not None:
        record(db, participant, gate, stamp, "cooldown-start", failures, until)
    return {"failures": failures, "cooldown_until": until}


def clear(db, participant, gate, stamp, event):
    db.execute("DELETE FROM gate_attempts WHERE participant=? AND gate=?", (participant, gate))
    record(db, participant, gate, stamp, event, 0)
