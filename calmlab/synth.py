"""A made-up developer, for trying CalmLab before you have data of your own.

`calmlab demo` writes eight weeks of one moderate persona into a throwaway data folder and
opens the web view on it, with a banner saying it is demo data. Each simulated day is a
developer juggling Claude Code sessions: reading a finished reply, thinking, sending the
next prompt, sometimes starting another session while one is still running. Drain
answers come from the day's own numbers, so any finding on the demo comes from the data
rather than being painted on.
"""

from __future__ import annotations

import math
import random
import statistics
from datetime import date, datetime, timedelta

from . import metrics, store

PERSONA = dict(max_sessions=3, spawn=0.32, prompts=(8, 18), turn_med=180, think_med=30,
               wpm=240, reply_med=180, day_h=(6.5, 10.0), break_per_h=0.25)


def _lognormal(rng: random.Random, median: float, sigma: float = 0.6) -> float:
    return median * math.exp(rng.gauss(0, sigma))


def _hash(rng: random.Random) -> str:
    return "".join(rng.choice("0123456789abcdef") for _ in range(16))


def simulate_day(rng: random.Random, persona: dict, day: date, offset_min: int, scene_on: bool) -> list[dict]:
    eff = dict(spawn=0.8, read=1.12, breaks=1.4) if scene_on else dict(spawn=1.0, read=1.0, breaks=1.0)
    spawn = persona["spawn"] * eff["spawn"]
    max_sessions = persona["max_sessions"]

    t0 = _local_ts(day, 0.0, offset_min)
    t = t0 + rng.uniform(8.3, 10.0) * 3600
    day_end = t + rng.uniform(*persona["day_h"]) * 3600
    lunch_at = t0 + rng.uniform(12.0, 13.2) * 3600
    lunch_done = False

    events: list[dict] = []
    # A small share of events lose the scene heartbeat (game closed, laptop lid), as in life.
    def emit(kind, ts, sid, **counts):
        scene_flag = scene_on and rng.random() > 0.02
        events.append({"kind": kind, "ts": round(ts, 3), "utc_offset_min": offset_min, "session": sid,
                       "prompt_words": counts.get("pw"), "prompt_tokens": counts.get("pt"),
                       "reply_words": counts.get("rw"), "reply_tokens": counts.get("rt"),
                       "scene": scene_flag})

    sessions: dict[str, dict] = {}

    def start_session(at):
        sid = _hash(rng)
        sessions[sid] = {"until": None, "ended": at, "left": rng.randint(*persona["prompts"]), "reply": 0}
        emit("session_start", at, sid)
        return sid

    def submit(sid, at):
        s = sessions[sid]
        words = max(3, int(_lognormal(rng, 28, 0.8)))
        emit("prompt_submit", at, sid, pw=words, pt=int(words * 1.35))
        emit("turn_start", at, sid)
        dur = min(_lognormal(rng, persona["turn_med"], 0.85), 2400)
        if rng.random() < 0.08:
            emit("tool_fail", at + dur * rng.uniform(0.2, 0.8), sid)
        if rng.random() < 0.10:
            emit("needs_input", at + dur * rng.uniform(0.1, 0.6), sid)
            dur += _lognormal(rng, 20, 0.5)
        end = at + dur
        reply = max(5, int(_lognormal(rng, persona["reply_med"], 0.7)))
        emit("turn_end", end, sid, rw=reply, rt=int(reply * 1.4))
        s["until"], s["reply"] = end, reply
        s["left"] -= 1

    start_session(t)
    first = next(iter(sessions))
    t += rng.uniform(20, 90)
    submit(first, t)

    while t < day_end:
        if not lunch_done and t >= lunch_at:
            t += rng.uniform(30, 55) * 60
            lunch_done = True
        if rng.random() < persona["break_per_h"] * eff["breaks"] * (5 / 60):
            t += rng.uniform(10, 25) * 60

        running = {k: s for k, s in sessions.items() if s["until"] and s["until"] > t}
        waiting = {k: s for k, s in sessions.items() if s["until"] and s["until"] <= t}

        if waiting:
            sid = min(waiting, key=lambda k: waiting[k]["until"])
            s = sessions[sid]
            if s["left"] <= 0:
                emit("session_end", max(t, s["until"]) + rng.uniform(5, 60), sid)
                del sessions[sid]
                continue
            read = s["reply"] / persona["wpm"] * 60 * eff["read"] * rng.uniform(0.6, 1.3)
            think = _lognormal(rng, persona["think_med"], 0.9)
            # Juggling slows the response to each one.
            t = max(t, s["until"]) + (read + think) * (1 + 0.12 * len(running))
            submit(sid, t)
            continue

        if len(sessions) < max_sessions and rng.random() < spawn:
            t += rng.uniform(10, 120)
            sid = start_session(t)
            t += rng.uniform(15, 90)
            submit(sid, t)
            continue

        if running:
            t = min(s["until"] for s in running.values()) + rng.uniform(0, 5)
        else:
            t += rng.uniform(60, 600)
            sid = start_session(t)
            t += rng.uniform(15, 60)
            submit(sid, t)

    for sid, s in list(sessions.items()):
        emit("session_end", max(t, s["until"] or t) + rng.uniform(5, 120), sid)
    events.sort(key=lambda e: e["ts"])
    return events


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _local_ts(day: date, hour: float, offset_min: int) -> float:
    local = datetime(day.year, day.month, day.day) + timedelta(hours=hour)
    return (local - timedelta(minutes=offset_min) - datetime(1970, 1, 1)).total_seconds()


def generate(days: int = 56, end: date | None = None, seed: int = 7) -> tuple[list[dict], list[dict]]:
    """(events, check-ins) for the `days` days up to yesterday: weekdays, and the odd
    short Saturday. Parallel work creeps up over the period, so the trends have a shape."""
    rng = random.Random(seed)
    end = end or date.today() - timedelta(days=1)
    offset = store.local_offset_min()
    events: list[dict] = []
    for i in range(days - 1, -1, -1):
        day = end - timedelta(days=i)
        progress = 1 - i / max(1, days - 1)
        saturday = day.weekday() == 5 and rng.random() < 0.3
        if day.weekday() < 5 or saturday:
            persona = dict(PERSONA, max_sessions=rng.choice([1, 1, 2, 2, 3] if progress > 0.5 else [1, 1, 1, 2, 2, 3]),
                           spawn=PERSONA["spawn"] * rng.uniform(0.3, 1.0) * (0.6 + 0.6 * progress))
            if saturday:
                persona["day_h"] = (1.5, 3.5)
            events.extend(simulate_day(rng, persona, day, offset, scene_on=False))
    checkins = []
    days = metrics.daily(events)
    ps = [m["parallel_starts"] for m in days.values()]
    mean_ps, sd_ps = statistics.fmean(ps), (statistics.pstdev(ps) or 1)
    for d, m in days.items():
        # Busier-than-usual days feel worse, plus noise: relative to this person's own days.
        drain = (2.9 + 0.9 * (m["parallel_starts"] - mean_ps) / sd_ps
                 + 0.25 * (m["day_length_h"] - 8) + rng.gauss(0, 0.5))
        drain = int(_clamp(round(drain), 1, 5))
        if rng.random() < 0.9:
            checkins.append({"drain": drain, "trigger": "end_of_day",
                             "when": _local_ts(d, rng.uniform(16.2, 18.5), offset)})
        if m["longest_stretch_min"] > 120 and rng.random() < 0.4:
            checkins.append({"drain": int(_clamp(drain + rng.choice([-1, 0, 0]), 1, 5)), "trigger": "long_session",
                             "when": _local_ts(d, rng.uniform(11.0, 15.0), offset)})
    return events, checkins


def load(conn, days: int = 56, end: date | None = None) -> None:
    events, checkins = generate(days, end)
    for e in events:
        store.add_event(conn, store.Event(**e))
    for c in checkins:
        store.add_checkin(conn, c["drain"], c["trigger"], asked_at=c["when"] - 30, when=c["when"])
