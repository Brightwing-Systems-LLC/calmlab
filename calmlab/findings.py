"""From metric days and check-ins to what the home page says.

`days()` joins each day's metrics with that day's drain. `week()` summarises seven days
against the seven before. `links()` tests every day measure in MEASURES against how
drained you said you were (see stats.py for how), and `finding()` says the strongest link
that holds up in one sentence, or says nothing until there is enough to go on.

The test decides whether a link is shown. The sentence then describes it as your higher
days against your lower days, because "1.2 points more drained" reads better than a
correlation. It is a pattern in your own data, not a cause, and the page says so.
"""

from __future__ import annotations

import functools
import statistics
from dataclasses import dataclass
from datetime import date, timedelta

from . import metrics, stats

MIN_CHECKIN_DAYS = 7
MIN_GROUP_DAYS = 3
MIN_DIFF = 0.5
SAME_HABIT = 0.8


def duration(seconds: float | None) -> str:
    if seconds is None:
        return "–"
    seconds = round(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m {s:02d}s" if m < 10 and s else f"{m}m"
    h, m = divmod(seconds // 60, 60)
    return f"{h}h {m:02d}m"


def _clock(h: float) -> str:
    h = h % 24
    return f"{int(h):02d}:{round(h % 1 * 60) % 60:02d}"


def _int(v):
    return f"{v:.0f}"


def _one(v):
    return f"{v:.1f}"


def _hours(v):
    return f"{v:.1f}h"


def _minutes(v):
    return duration(v * 60)


def _pct(v):
    return f"{v:.0%}"


def _tick_plain(v):
    return f"{v:g}"


def _tick_minutes(v):
    return f"{v / 60:g}m"


def _tick_hours(v):
    return f"{v / 60:g}h"


def _tick_h(v):
    return f"{v:g}h"


def _tick_clock(v):
    return f"{int(v) % 24:02d}:00"


@dataclass(frozen=True)
class Measure:
    label: str  # short, for a picker
    axis: str  # what the axis of a chart says
    fmt: object  # value -> text
    phrase: str  # "days with {value}..."
    more: str  # the higher end, as a noun phrase: "more parallel starts"
    unit: float = 1  # ticks are placed in multiples of this (60: whole minutes)
    tick: object = _tick_plain
    singular: bool = False  # "a faster pace goes", not "go"
    zero: bool = True  # whether the axis starts at zero


# The day measures tested against drain, and how each one reads on the page.
MEASURES = {
    "parallel_starts": Measure("Parallel starts", "Parallel starts that day", _int,
                               "{} or more parallel starts", "more parallel starts"),
    "mean_concurrency": Measure("Agents at once", "Agents at once, while busy", _one,
                                "{} or more agents busy at once", "more agents busy at once"),
    "multi_busy_share": Measure("Juggling", "Share of busy time with two or more agents", _pct,
                                "{} or more of busy time juggling agents", "more time juggling agents"),
    "day_length_h": Measure("Day length", "Hours from first to last activity", _hours,
                            "{} or more of work", "longer days", tick=_tick_h),
    "start_hour": Measure("Start time", "First prompt of the day", _clock,
                          "a first prompt at {} or later", "later starts", tick=_tick_clock, zero=False),
    "end_hour": Measure("Finish time", "Last activity of the day", _clock,
                        "work until {} or later", "later finishes", tick=_tick_clock, zero=False),
    "longest_stretch_min": Measure("Focus stretch", "Longest focus stretch", _minutes,
                                   "a focus stretch of {} or more", "longer focus stretches", 60, _tick_hours),
    "median_wait_s": Measure("Wait on you", "Typical wait on you", duration,
                             "a typical wait of {} or more", "agents waiting longer on you", 60, _tick_minutes),
    "long_wait_share": Measure("Long waits", "Share of replies left over ten minutes", _pct,
                               "{} or more of replies left over ten minutes", "more replies left waiting"),
    "prompts_per_hour": Measure("Prompt pace", "Prompts per hour", _one,
                                "{} or more prompts an hour", "a faster prompt pace", singular=True),
}


def delta(now: float | None, before: float | None, kind: str = "number") -> str:
    """'+0.3 vs last week', or '' when either week has no value."""
    if now is None or before is None:
        return ""
    diff = now - before
    if kind == "minutes":
        diff, kind = diff * 60, "duration"
    if kind == "duration":
        if round(abs(diff)) == 0:
            return "same as last week"
        return f"{'+' if diff > 0 else '−'}{duration(abs(diff))} vs last week"
    if round(abs(diff), 1) == 0:
        return "same as last week"
    return f"{'+' if diff > 0 else '−'}{abs(diff):.1f} vs last week"


def days(events: list[dict], checkins: list[dict]) -> dict[date, dict]:
    out = metrics.daily(events)
    by_day: dict[str, list[int]] = {}
    for c in checkins:
        by_day.setdefault(c["local_date"], []).append(c["drain"])
    for row in out.values():
        answers = by_day.get(row["date"], [])
        row["drain"] = statistics.fmean(answers) if answers else None
        row["checkins"] = len(answers)
    for iso, answers in by_day.items():
        d = date.fromisoformat(iso)
        if d not in out:
            out[d] = {"date": iso, "drain": statistics.fmean(answers), "checkins": len(answers),
                      "turns": 0, "parallel_starts": 0, "waits_s": []}
    return dict(sorted(out.items()))


def _window(all_days: dict[date, dict], end: date, n: int = 7) -> list[dict]:
    start = end - timedelta(days=n - 1)
    return [row for d, row in all_days.items() if start <= d <= end]


def _summary(rows: list[dict]) -> dict:
    busy = [r["mean_concurrency"] for r in rows if r.get("turns") and r.get("mean_concurrency")]
    waits = [w for r in rows for w in r.get("waits_s", [])]
    stretches = [r["longest_stretch_min"] for r in rows if r.get("longest_stretch_min")]
    drains = [r["drain"] for r in rows if r.get("drain") is not None for _ in range(r["checkins"])]
    return {
        "active_days": sum(1 for r in rows if r.get("turns")),
        "agents_at_once": statistics.fmean(busy) if busy else None,
        "wait_s": statistics.median(waits) if waits else None,
        "longest_stretch_min": max(stretches) if stretches else None,
        "drain": statistics.fmean(drains) if drains else None,
        "checkins": sum(r.get("checkins", 0) for r in rows),
    }


def week(all_days: dict[date, dict], today: date) -> dict:
    this = _summary(_window(all_days, today))
    prev = _summary(_window(all_days, today - timedelta(days=7)))
    # A first week has nothing before it: every value None, so each delta is blank.
    return {"this": this, "prev": prev if prev["active_days"] else _summary([])}


def _points(n: float) -> str:
    n = round(abs(n), 1)
    return f"{n:.1f} point" + ("" if n == 1 else "s")


def split(pairs: list[tuple[float, float]]) -> dict | None:
    """Your higher days against your lower days, cut at the median, for a readable sentence.

    When more than half your days share the lowest value (no parallel starts at all, say),
    the median cuts nothing off, so the cut moves to "anything above the lowest"."""
    cut = statistics.median(v for v, _ in pairs)
    if cut <= min(v for v, _ in pairs):
        cut = min((v for v, _ in pairs if v > cut), default=cut)
    high = [dr for v, dr in pairs if v >= cut]
    low = [dr for v, dr in pairs if v < cut]
    if len(high) < MIN_GROUP_DAYS or len(low) < MIN_GROUP_DAYS:
        return None
    hi, lo = statistics.fmean(high), statistics.fmean(low)
    return {"cut": min(v for v, _ in pairs if v >= cut), "high": hi, "low": lo, "diff": hi - lo,
            "n_high": len(high), "n_low": len(low)}


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def strength(rho: float) -> str:
    r = abs(rho)
    return "strong" if r >= 0.5 else "moderate" if r >= 0.3 else "weak"


def _pairs(rows, key) -> list[tuple[float, float]]:
    return [(r[key], r["drain"]) for r in rows if r.get("turns") and r.get("drain") is not None and r.get(key) is not None]


@functools.lru_cache(maxsize=64)
def _test(xs: tuple, ys: tuple):
    return stats.spearman_test(list(xs), list(ys))


def links(rows: dict[date, dict]) -> dict:
    """Which day measures go with how drained you said you were, tested properly.

    Every measure in MEASURES is tested on the days that have both it and a check-in.
    A link is `significant` only if it survives the false-discovery correction across all
    of them, so looking at ten measures does not turn up one by luck."""
    rated = {d: r for d, r in rows.items() if r.get("turns") and r.get("drain") is not None}
    out = {"days": len(rated), "need": MIN_CHECKIN_DAYS, "ready": len(rated) >= MIN_CHECKIN_DAYS,
           "tested": [], "by_key": {}, "significant": [], "groups": []}
    if not out["ready"]:
        return out
    tested = []
    for key, m in MEASURES.items():
        values = {d: r[key] for d, r in rated.items() if r.get(key) is not None}
        pairs = _pairs(rated.values(), key)
        if len(pairs) < MIN_CHECKIN_DAYS:
            continue
        result = _test(tuple(v for v, _ in pairs), tuple(dr for _, dr in pairs))
        if result is None:
            continue
        rho, p = result
        tested.append({"key": key, "measure": m, "rho": rho, "p": p, "n": len(pairs),
                       "strength": strength(rho), "split": split(pairs), "values": values, "also": []})
    for t, ok in zip(tested, stats.significant([t["p"] for t in tested]), strict=True):
        t["significant"] = ok
        verb = "goes" if t["measure"].singular else "go"
        t["sentence"] = f"{_cap(t['measure'].more)} {verb} with feeling {'more' if t['rho'] > 0 else 'less'} drained"
    out["tested"] = tested
    out["by_key"] = {t["key"]: t for t in tested}
    out["significant"] = sorted((t for t in tested if t["significant"]), key=lambda t: -abs(t["rho"]))
    out["groups"] = _group(out["significant"])
    return out


def _group(links: list[dict]) -> list[dict]:
    """Fold links whose measures rise and fall together (rank correlation of SAME_HABIT or
    more across the same days) under the strongest of them. Parallel starts, agents at
    once and time juggling are usually one habit, and listing it three times is noise."""
    heads: list[dict] = []
    for t in links:
        for h in heads:
            common = sorted(set(t["values"]) & set(h["values"]))
            rho = stats.spearman([t["values"][d] for d in common], [h["values"][d] for d in common])
            if rho is not None and abs(rho) >= SAME_HABIT:
                h["also"].append(t)
                break
        else:
            heads.append(t)
    return heads


def finding(all_days: dict[date, dict]) -> dict:
    """The strongest link that holds up, said as your higher days against your lower days."""
    found = links(all_days)
    if not found["ready"]:
        return {"ready": False, "have": found["days"], "need": found["need"]}
    best = next((t for t in found["groups"] if t["split"]), None)
    if best is None:
        return {"ready": True, "found": False, "days": found["days"], "checked": len(found["tested"])}
    m, split = best["measure"], best["split"]
    return {
        "ready": True, "found": True, "metric": best["key"], "threshold": split["cut"], "diff": split["diff"],
        "days": best["n"], "rho": best["rho"], "p": best["p"], "strength": best["strength"],
        "checked": len(found["tested"]), "others": len(found["groups"]) - 1,
        "lead": "On days with", "emph": m.phrase.format(m.fmt(split["cut"])), "middle": ",",
        "feel": f"{_points(split['diff'])} {'more' if split['diff'] > 0 else 'less'} drained",
    }
