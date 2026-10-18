"""The local SQLite store.

The schema is the privacy guarantee in its plainest form: an event row has an event
kind, a time, a salted hash of the session id, a scene flag and four integers. A
check-in row has a time, a number from 1 to 5 and which rule asked for it. There is no
column a piece of text could be written into. `tests/test_privacy.py` holds it there.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from . import CHECKIN_TRIGGERS, EVENT_KINDS, paths

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id             INTEGER PRIMARY KEY,
    kind           TEXT    NOT NULL CHECK (kind IN ({", ".join(repr(k) for k in EVENT_KINDS)})),
    ts             REAL    NOT NULL,
    utc_offset_min INTEGER NOT NULL,
    session        TEXT    NOT NULL CHECK (length(session) = 16),
    prompt_words   INTEGER,
    prompt_tokens  INTEGER,
    reply_words    INTEGER,
    reply_tokens   INTEGER,
    scene          INTEGER
);
CREATE INDEX IF NOT EXISTS events_ts ON events (ts);
CREATE TABLE IF NOT EXISTS checkins (
    id             INTEGER PRIMARY KEY,
    answered_at    REAL    NOT NULL,
    utc_offset_min INTEGER NOT NULL,
    local_date     TEXT    NOT NULL,
    drain          INTEGER NOT NULL CHECK (drain BETWEEN 1 AND 5),
    trigger        TEXT    NOT NULL CHECK (trigger IN ({", ".join(repr(k) for k in CHECKIN_TRIGGERS)})),
    asked_at       REAL
);
"""

EVENT_FIELDS = (
    "kind", "ts", "utc_offset_min", "session",
    "prompt_words", "prompt_tokens", "reply_words", "reply_tokens", "scene",
)


@dataclass
class Event:
    kind: str
    ts: float
    utc_offset_min: int
    session: str
    prompt_words: int | None = None
    prompt_tokens: int | None = None
    reply_words: int | None = None
    reply_tokens: int | None = None
    scene: bool | None = None

    def as_dict(self) -> dict:
        return {f: getattr(self, f) for f in EVENT_FIELDS}


def local_offset_min(ts: float | None = None) -> int:
    t = time.localtime(ts if ts is not None else time.time())
    return int((t.tm_gmtoff or 0) // 60)


def local_date_str(ts: float, offset_min: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts + offset_min * 60))


@contextmanager
def connect(path: Path | None = None):
    path = path or paths.db_path()
    paths.ensure_home()
    conn = sqlite3.connect(path, timeout=5)
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()
    try:
        path.chmod(0o600)
    except OSError:
        pass


def get_meta(conn, key: str, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_meta(conn, key: str, value) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )


def del_meta(conn, key: str) -> None:
    conn.execute("DELETE FROM meta WHERE key = ?", (key,))


def salt(conn) -> str:
    """A per-install random salt for hashing session ids. It never leaves this machine."""
    value = get_meta(conn, "salt")
    if value is None:
        value = secrets.token_hex(32)
        set_meta(conn, "salt", value)
    return value


def add_event(conn, event: Event) -> None:
    if event.kind not in EVENT_KINDS:
        raise ValueError(f"unknown event kind {event.kind!r}")
    for name in ("prompt_words", "prompt_tokens", "reply_words", "reply_tokens"):
        value = getattr(event, name)
        if value is not None and not isinstance(value, int):
            raise TypeError(f"{name} must be an integer count")
    conn.execute(
        f"INSERT INTO events ({', '.join(EVENT_FIELDS)}) VALUES ({', '.join('?' * len(EVENT_FIELDS))})",
        (
            event.kind, float(event.ts), int(event.utc_offset_min), event.session,
            event.prompt_words, event.prompt_tokens, event.reply_words, event.reply_tokens,
            None if event.scene is None else int(bool(event.scene)),
        ),
    )


def events(conn, since: float | None = None) -> list[dict]:
    sql = f"SELECT {', '.join(EVENT_FIELDS)} FROM events"
    args: tuple = ()
    if since is not None:
        sql += " WHERE ts >= ?"
        args = (since,)
    rows = conn.execute(sql + " ORDER BY ts, id", args).fetchall()
    out = []
    for row in rows:
        d = dict(zip(EVENT_FIELDS, row, strict=True))
        d["scene"] = None if d["scene"] is None else bool(d["scene"])
        out.append(d)
    return out


def add_checkin(conn, drain: int, trigger: str, asked_at: float | None = None,
                when: float | None = None) -> None:
    if not isinstance(drain, int) or isinstance(drain, bool) or not 1 <= drain <= 5:
        raise ValueError("drain must be an integer from 1 to 5")
    if trigger not in CHECKIN_TRIGGERS:
        raise ValueError(f"unknown trigger {trigger!r}")
    when = when if when is not None else time.time()
    offset = local_offset_min(when)
    conn.execute(
        "INSERT INTO checkins (answered_at, utc_offset_min, local_date, drain, trigger, asked_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (when, offset, local_date_str(when, offset), drain, trigger, asked_at),
    )


def checkins(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT answered_at, utc_offset_min, local_date, drain, trigger, asked_at "
        "FROM checkins ORDER BY answered_at"
    ).fetchall()
    return [
        {"answered_at": a, "utc_offset_min": o, "local_date": d, "drain": v, "trigger": t, "asked_at": q}
        for a, o, d, v, t, q in rows
    ]


def delete_everything() -> list[Path]:
    """Remove the database and every file CalmLab wrote. Returns what was removed."""
    removed = []
    base = paths.home()
    if not base.exists():
        return removed
    for path in sorted(base.rglob("*"), reverse=True):
        if path.is_file() or path.is_symlink():
            path.unlink()
            removed.append(path)
        elif path.is_dir():
            path.rmdir()
    base.rmdir()
    return removed
