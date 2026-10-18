"""From metric days and check-ins to what the home page says.

`days()` joins each day's metrics with that day's drain. `week()` summarises seven days
against the seven before. `finding()` looks for the one way your days split that lines up
best with how drained you said you were, and says it in a sentence, or says nothing
until there is enough to go on.

A finding compares your higher days with your lower days. It is a pattern in your own
data, not a cause, and the page says so.
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta

from . import metrics

MIN_CHECKIN_DAYS = 7
MIN_GROUP_DAYS = 3
MIN_DIFF = 0.5

CANDIDATES = (
    "parallel_starts", "mean_concurrency", "day_length_h", "longest_stretch_min",
    "median_wait_s", "prompts_per_hour",
)


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
    return {"this": this, "prev": prev if prev["active_days"] else None}


def _points(n: float) -> str:
    n = round(abs(n), 1)
    return f"{n:.1f} point" + ("" if n == 1 else "s")


def _sentence(metric: str, threshold: float, diff: float) -> tuple[str, str, str]:
    """(lead, emphasised threshold, tail) so the page can set the numbers apart."""
    feel = f"{_points(diff)} {'more' if diff > 0 else 'less'} drained"
    if metric == "parallel_starts":
        return "On days you start", f"{threshold:.0f} or more", f" agents while another is still running, you rate yourself|{feel}"
    if metric == "mean_concurrency":
        return "On days you keep", f"{threshold:.1f} or more", f" agents busy at once, you rate yourself|{feel}"
    if metric == "day_length_h":
        return "On days you work", f"{threshold:.0f} hours or more", f", you rate yourself|{feel}"
    if metric == "longest_stretch_min":
        return "On days with a focus stretch of", f"{duration(threshold * 60)} or more", f", you rate yourself|{feel}"
    if metric == "median_wait_s":
        return "On days your agents typically wait", f"{duration(threshold)} or more", f" for you, you rate yourself|{feel}"
    return "On days you send", f"{threshold:.0f} or more", f" prompts an hour, you rate yourself|{feel}"


def finding(all_days: dict[date, dict]) -> dict:
    rated = [r for r in all_days.values() if r.get("drain") is not None and r.get("turns")]
    if len(rated) < MIN_CHECKIN_DAYS:
        return {"ready": False, "have": len(rated), "need": MIN_CHECKIN_DAYS}
    best = None
    for metric in CANDIDATES:
        pairs = [(r[metric], r["drain"]) for r in rated if r.get(metric) is not None]
        if len(pairs) < 2 * MIN_GROUP_DAYS:
            continue
        cut = statistics.median(v for v, _ in pairs)
        high = [(v, dr) for v, dr in pairs if v >= cut]
        low = [(v, dr) for v, dr in pairs if v < cut]
        if len(high) < MIN_GROUP_DAYS or len(low) < MIN_GROUP_DAYS:
            continue
        diff = statistics.fmean(dr for _, dr in high) - statistics.fmean(dr for _, dr in low)
        if abs(diff) >= MIN_DIFF and (best is None or abs(diff) > abs(best["diff"])):
            best = {"metric": metric, "threshold": min(v for v, _ in high), "diff": diff,
                    "days": len(pairs)}
    if best is None:
        return {"ready": True, "found": False, "days": len(rated)}
    lead, emph, tail = _sentence(best["metric"], best["threshold"], best["diff"])
    middle, feel = tail.split("|")
    return {"ready": True, "found": True, "lead": lead, "emph": emph, "middle": middle,
            "feel": feel, **best}
