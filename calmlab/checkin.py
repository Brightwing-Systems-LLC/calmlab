"""The one check-in question: how drained are you right now, 1 to 5.

It is asked when an agent hands control back (the Stop hook), as a one-line message
under the reply. The rules are fixed here rather than in settings, so every check-in
means the same thing on every day and for every person:

- **end_of_day**: the first hand-back after 16:00 on a day you worked.
- **long_session**: the first hand-back once one session has run for 90 minutes without
  a 30-minute break.
- at most two a day, at least three hours apart, end of day first when both are due.

You answer by typing `calm 3` as your next prompt. The UserPromptSubmit hook records the
digit and blocks the prompt, so it never reaches the model. Anything else is a prompt
like any other and the question counts as skipped. `calm N` with nothing pending is
still recorded, as a check-in you started yourself.
"""

from __future__ import annotations

import re

from . import store

END_OF_DAY_HOUR = 16
LONG_SESSION_S = 90 * 60
SESSION_BREAK_S = 30 * 60
MAX_PER_DAY = 2
MIN_SPACING_S = 3 * 3600
PENDING_FOR_S = 2 * 3600

QUESTION = "CalmLab · How drained are you right now? Type calm 1 (not at all) to calm 5 (completely)."
RECORDED = "CalmLab · Drain {n} recorded. Ctrl+U clears the line."

DRAIN_LABELS = {1: "Not at all", 2: "A little", 3: "Moderately", 4: "Very", 5: "Completely"}

_ANSWER = re.compile(r"\s*calm\s+([1-5])\s*", re.IGNORECASE)


def parse_answer(prompt) -> int | None:
    """The digit from an exact `calm N` prompt, else None. Nothing else is read."""
    if not isinstance(prompt, str) or len(prompt) > 16:
        return None
    m = _ANSWER.fullmatch(prompt)
    return int(m.group(1)) if m else None


def _asks(conn) -> list[dict]:
    return store.get_meta(conn, "checkin_asks", [])


def _session_run_s(conn, session: str, now: float) -> float:
    """How long this session has been going without a break of SESSION_BREAK_S."""
    rows = conn.execute(
        "SELECT ts FROM events WHERE session = ? AND ts >= ? ORDER BY ts DESC",
        (session, now - 24 * 3600),
    ).fetchall()
    start = now
    for (ts,) in rows:
        if start - ts >= SESSION_BREAK_S:
            break
        start = ts
    return now - start


def due(conn, session: str, now: float) -> str | None:
    """Which check-in to ask at this hand-back, if any."""
    offset = store.local_offset_min(now)
    today = store.local_date_str(now, offset)
    asks = _asks(conn)
    today_asks = [a for a in asks if a["local_date"] == today]
    if len(today_asks) >= MAX_PER_DAY:
        return None
    if asks and now - max(a["asked_at"] for a in asks) < MIN_SPACING_S:
        return None
    asked = {a["trigger"] for a in today_asks}
    hour = int(((now + offset * 60) % 86400) // 3600)
    if hour >= END_OF_DAY_HOUR and "end_of_day" not in asked:
        return "end_of_day"
    if "long_session" not in asked and _session_run_s(conn, session, now) >= LONG_SESSION_S:
        return "long_session"
    return None


def mark_asked(conn, trigger: str, now: float) -> None:
    offset = store.local_offset_min(now)
    asks = _asks(conn)[-20:]
    asks.append({"asked_at": now, "trigger": trigger, "local_date": store.local_date_str(now, offset)})
    store.set_meta(conn, "checkin_asks", asks)
    store.set_meta(conn, "checkin_pending", {"asked_at": now, "trigger": trigger})


def pending(conn, now: float) -> dict | None:
    p = store.get_meta(conn, "checkin_pending")
    if p and now - p["asked_at"] <= PENDING_FOR_S:
        return p
    return None


def answer(conn, drain: int, now: float) -> str:
    """Record an answer. Returns the trigger it was filed under."""
    p = pending(conn, now)
    trigger, asked_at = (p["trigger"], p["asked_at"]) if p else ("self", None)
    store.add_checkin(conn, drain, trigger, asked_at=asked_at, when=now)
    store.del_meta(conn, "checkin_pending")
    return trigger
