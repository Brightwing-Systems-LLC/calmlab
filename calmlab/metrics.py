"""Derived metrics, from event rows to one record per local day.

Definitions (also in README.md):

- **turn**: `turn_start` to the next `turn_end` in the same session. A turn with no end is
  closed by the session's next event, and capped at MAX_TURN_S.
- **wait-for-human**: `turn_end` to the next `prompt_submit` in the same session. Gaps
  over MAX_WAIT_S are breaks, not waits, and are left out.
- **concurrency**: how many sessions have a turn running at once.
- **parallel start**: a `session_start` or `prompt_submit` in one session while a turn is
  running in another session.
- **reading load**: the size of each final reply, and how long until the next prompt.
- **prompts per hour**: prompts over the length of the day.
- **longest stretch**: the longest run of activity (events and running turns) with no
  gap of GAP_S or more.
- **day length**: first to last event of the local day.
- **busy by level**: seconds with 1, 2, 3, or 4 or more turns running at once.
"""

from __future__ import annotations

import bisect
import itertools
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

MAX_TURN_S = 2 * 3600
MAX_WAIT_S = 2 * 3600
GAP_S = 10 * 60
UNCLOSED_TURN_S = 60


def local_dt(ts: float, offset_min: int) -> datetime:
    return datetime.fromtimestamp(ts, UTC).replace(tzinfo=None) + timedelta(minutes=offset_min)


def local_date(ts: float, offset_min: int) -> date:
    return local_dt(ts, offset_min).date()


@dataclass
class Turn:
    session: str
    start: float
    end: float
    offset: int
    prompt_words: int | None = None
    prompt_tokens: int | None = None
    reply_words: int | None = None
    reply_tokens: int | None = None
    scene: bool | None = None
    closed: bool = True
    wait_s: float | None = None
    parallel_start: bool = False

    @property
    def duration_s(self) -> float:
        return self.end - self.start


@dataclass
class Analysis:
    events: list[dict]
    turns: list[Turn]
    parallel_starts: list[dict] = field(default_factory=list)


def _sorted(events: list[dict]) -> list[dict]:
    return sorted(events, key=lambda e: (e["ts"], e["kind"] != "prompt_submit"))


def build_turns(events: list[dict]) -> list[Turn]:
    events = _sorted(events)
    by_session: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        by_session[e["session"]].append(e)

    turns: list[Turn] = []
    for session, evs in by_session.items():
        open_turn: Turn | None = None
        last_prompt: dict | None = None
        session_turns: list[Turn] = []
        for e in evs:
            kind = e["kind"]
            if open_turn is not None and kind in ("turn_start", "session_end", "session_start"):
                open_turn.end = min(e["ts"], open_turn.start + MAX_TURN_S)
                open_turn.closed = False
                session_turns.append(open_turn)
                open_turn = None
            if kind == "prompt_submit":
                last_prompt = e
            elif kind == "turn_start":
                open_turn = Turn(
                    session=session, start=e["ts"], end=e["ts"], offset=e["utc_offset_min"],
                    scene=e.get("scene"),
                )
                if last_prompt is not None and abs(last_prompt["ts"] - e["ts"]) < 5:
                    open_turn.prompt_words = last_prompt.get("prompt_words")
                    open_turn.prompt_tokens = last_prompt.get("prompt_tokens")
            elif kind == "turn_end" and open_turn is not None:
                open_turn.end = min(e["ts"], open_turn.start + MAX_TURN_S)
                open_turn.reply_words = e.get("reply_words")
                open_turn.reply_tokens = e.get("reply_tokens")
                session_turns.append(open_turn)
                open_turn = None
        if open_turn is not None:
            open_turn.end = open_turn.start + UNCLOSED_TURN_S
            open_turn.closed = False
            session_turns.append(open_turn)

        prompts = [e["ts"] for e in evs if e["kind"] == "prompt_submit"]
        for turn in session_turns:
            if not turn.closed:
                continue
            i = bisect.bisect_left(prompts, turn.end)
            nxt = prompts[i] if i < len(prompts) else None
            if nxt is not None and nxt - turn.end <= MAX_WAIT_S:
                turn.wait_s = nxt - turn.end
        turns.extend(session_turns)
    turns.sort(key=lambda t: t.start)
    return turns


def find_parallel_starts(events: list[dict], turns: list[Turn]) -> list[dict]:
    ordered = sorted(turns, key=lambda t: t.start)
    starts = [t.start for t in ordered]
    out = []
    for e in events:
        if e["kind"] not in ("session_start", "prompt_submit"):
            continue
        hi = bisect.bisect_left(starts, e["ts"])
        lo = bisect.bisect_left(starts, e["ts"] - MAX_TURN_S)
        busy_elsewhere = any(
            t.session != e["session"] and t.start < e["ts"] < t.end for t in ordered[lo:hi]
        )
        if busy_elsewhere:
            out.append(e)
    return out


def analyse(events: list[dict]) -> Analysis:
    events = _sorted(events)
    turns = build_turns(events)
    parallel = find_parallel_starts(events, turns)
    parallel_ts = {(p["session"], p["ts"]) for p in parallel}
    for t in turns:
        if (t.session, t.start) in parallel_ts:
            t.parallel_start = True
    return Analysis(events=events, turns=turns, parallel_starts=parallel)


def concurrency_steps(turns: list[Turn], lo: float | None = None, hi: float | None = None):
    """[(ts, busy_sessions)] — a step function, value holds until the next point."""
    edges = []
    for t in turns:
        s, e = t.start, t.end
        if lo is not None:
            s = max(s, lo)
        if hi is not None:
            e = min(e, hi)
        if e > s:
            edges.append((s, 1))
            edges.append((e, -1))
    edges.sort()
    steps, level = [], 0
    for ts, delta in edges:
        level += delta
        if steps and steps[-1][0] == ts:
            steps[-1] = (ts, level)
        else:
            steps.append((ts, level))
    return steps


def _concurrency_stats(steps) -> tuple[int, float, float]:
    peak, busy, weighted, multi = 0, 0.0, 0.0, 0.0
    for (t0, level), (t1, _) in itertools.pairwise(steps):
        span = t1 - t0
        peak = max(peak, level)
        if level >= 1:
            busy += span
            weighted += span * level
        if level >= 2:
            multi += span
    if busy == 0:
        return peak, 0.0, 0.0
    return peak, weighted / busy, multi / busy


def _longest_stretch(intervals: list[tuple[float, float]]) -> float:
    if not intervals:
        return 0.0
    intervals = sorted(intervals)
    best = 0.0
    cur_s, cur_e = intervals[0]
    for s, e in intervals[1:]:
        if s - cur_e < GAP_S:
            cur_e = max(cur_e, e)
        else:
            best = max(best, cur_e - cur_s)
            cur_s, cur_e = s, e
    return max(best, cur_e - cur_s)


def _median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def _quantile(values, q):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    idx = min(len(values) - 1, max(0, round(q * (len(values) - 1))))
    return values[idx]


def daily(events: list[dict]) -> dict[date, dict]:
    """One metrics record per local date."""
    analysis = analyse(events)
    by_day_events: dict[date, list[dict]] = defaultdict(list)
    for e in analysis.events:
        by_day_events[local_date(e["ts"], e["utc_offset_min"])].append(e)
    by_day_turns: dict[date, list[Turn]] = defaultdict(list)
    for t in analysis.turns:
        by_day_turns[local_date(t.start, t.offset)].append(t)
    by_day_parallel: dict[date, list[dict]] = defaultdict(list)
    for p in analysis.parallel_starts:
        by_day_parallel[local_date(p["ts"], p["utc_offset_min"])].append(p)

    out = {}
    for day, evs in sorted(by_day_events.items()):
        turns = by_day_turns.get(day, [])
        parallel = by_day_parallel.get(day, [])
        first, last = evs[0]["ts"], evs[-1]["ts"]
        for t in turns:
            last = max(last, t.end)
        day_length_h = (last - first) / 3600
        prompts = [e for e in evs if e["kind"] == "prompt_submit"]
        steps = concurrency_steps(turns)
        peak, mean_conc, multi_share = _concurrency_stats(steps)
        busy_by_level: dict[int, float] = defaultdict(float)
        for (t0, level), (t1, _) in itertools.pairwise(steps):
            if level >= 1:
                busy_by_level[min(level, 4)] += t1 - t0
        waits = [t.wait_s for t in turns if t.wait_s is not None]
        replies = [t.reply_words for t in turns if t.reply_words is not None]
        reading_wpm = [
            t.reply_words / (t.wait_s / 60)
            for t in turns
            if t.reply_words and t.wait_s and t.wait_s >= 5
        ]
        activity = [(t.start, t.end) for t in turns] + [(e["ts"], e["ts"]) for e in evs]
        scene_flags = [e["scene"] for e in evs if e.get("scene") is not None]
        hours = max(day_length_h, 0.25)
        parallel_by_hour: dict[int, int] = defaultdict(int)
        for p in parallel:
            parallel_by_hour[local_dt(p["ts"], p["utc_offset_min"]).hour] += 1
        prompts_by_hour: dict[int, int] = defaultdict(int)
        for p in prompts:
            prompts_by_hour[local_dt(p["ts"], p["utc_offset_min"]).hour] += 1

        out[day] = {
            "date": day.isoformat(),
            "sessions": len({e["session"] for e in evs}),
            "turns": len(turns),
            "prompts": len(prompts),
            "median_turn_s": _median([t.duration_s for t in turns]),
            "median_wait_s": _median(waits),
            "p90_wait_s": _quantile(waits, 0.9),
            "waits_s": [round(w, 1) for w in waits],
            "parallel_starts": len(parallel),
            "parallel_starts_per_hour": len(parallel) / hours,
            "peak_concurrency": peak,
            "mean_concurrency": round(mean_conc, 3),
            "multi_busy_share": round(multi_share, 3),
            "busy_by_level": dict(busy_by_level),
            "reply_words_total": sum(replies),
            "median_reply_words": _median(replies),
            "reading_wpm": _median(reading_wpm),
            "prompts_per_hour": len(prompts) / hours,
            "longest_stretch_min": _longest_stretch(activity) / 60,
            "day_length_h": day_length_h,
            "tool_fails": sum(1 for e in evs if e["kind"] == "tool_fail"),
            "needs_input": sum(1 for e in evs if e["kind"] == "needs_input"),
            "scene_share": (sum(scene_flags) / len(scene_flags)) if scene_flags else None,
            "parallel_by_hour": dict(parallel_by_hour),
            "prompts_by_hour": dict(prompts_by_hour),
        }
    return out


def timeline(events: list[dict], day: date) -> dict:
    """Everything the daily timeline chart draws, for one local date."""
    analysis = analyse(events)
    evs = [e for e in analysis.events if local_date(e["ts"], e["utc_offset_min"]) == day]
    turns = [t for t in analysis.turns if local_date(t.start, t.offset) == day]
    sessions = []
    for e in evs:
        if e["session"] not in sessions:
            sessions.append(e["session"])
    parallel = [
        p for p in analysis.parallel_starts if local_date(p["ts"], p["utc_offset_min"]) == day
    ]
    return {
        "events": evs,
        "turns": turns,
        "sessions": sessions,
        "parallel": parallel,
        "needs_input": [e for e in evs if e["kind"] == "needs_input"],
        "tool_fails": [e for e in evs if e["kind"] == "tool_fail"],
        "steps": concurrency_steps(turns),
        "scene": [(e["ts"], e.get("scene")) for e in evs],
    }
