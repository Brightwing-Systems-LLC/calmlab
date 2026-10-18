"""What the Patterns tab shows: your days over a chosen range, cut a few ways.

Everything here is computed from the same metric days the You tab uses, so nothing new
is recorded to draw it. Each cut comes with one plain sentence, so the page can be read
without decoding a chart.
"""

from __future__ import annotations

import math
import statistics
from datetime import date, timedelta

from .findings import MEASURES, MIN_GROUP_DAYS, Measure, duration, split

RANGES = {"14": ("2 weeks", 14), "56": ("8 weeks", 56), "all": ("All", None)}
DEFAULT_RANGE = "56"

WAIT_BINS = ((0, 30, "Under 30s"), (30, 120, "30s to 2m"), (120, 600, "2m to 10m"), (600, math.inf, "Over 10m"))
LEVELS = ((1, "One agent"), (2, "Two"), (3, "Three"), (4, "Four or more"))
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
WEEKDAY_NAMES = ("Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays")


# The small charts under "Over time": day measures from findings.MEASURES, plus two that
# are not tested against drain (prompts) or are drain itself.
TREND_KEYS = ("parallel_starts", "mean_concurrency", "median_wait_s", "longest_stretch_min", "day_length_h", "prompts", "drain")
EXTRA = {
    "prompts": Measure("Prompts", "Prompts", lambda v: f"{v:.0f}", "", ""),
    "drain": Measure("Drain", "Drain", lambda v: f"{v:.1f}", "", ""),
}


def trend_measure(key: str) -> Measure:
    return MEASURES.get(key) or EXTRA[key]


def window(all_days: dict[date, dict], today: date, key: str) -> tuple[date, date, dict[date, dict]]:
    """(first day, last day, the days between) for a range key from RANGES."""
    n = RANGES.get(key, RANGES[DEFAULT_RANGE])[1]
    if n is None:
        start = min(all_days) if all_days else today
    else:
        start = today - timedelta(days=n - 1)
    return start, today, {d: r for d, r in all_days.items() if start <= d <= today}


def _active(rows: dict[date, dict]) -> dict[date, dict]:
    return {d: r for d, r in rows.items() if r.get("turns")}


def hour_grid(rows: dict[date, dict]) -> dict | None:
    """Average prompts in each hour, by weekday. Only weekdays you worked get a row."""
    active = _active(rows)
    if not active:
        return None
    by_wd: dict[int, list[dict]] = {}
    for d, r in active.items():
        by_wd.setdefault(d.weekday(), []).append(r)
    used = [h for r in active.values() for h in r.get("prompts_by_hour", {})]
    lo, hi = min(min(used, default=9), 8), max(max(used, default=17), 18)
    grid, best = [], None
    for wd in sorted(by_wd):
        days = by_wd[wd]
        cells = []
        for h in range(lo, hi + 1):
            prompts = sum(r.get("prompts_by_hour", {}).get(h, 0) for r in days) / len(days)
            parallel = sum(r.get("parallel_by_hour", {}).get(h, 0) for r in days) / len(days)
            cells.append({"hour": h, "prompts": prompts, "parallel": parallel})
            if best is None or prompts > best[2]:
                best = (wd, h, prompts)
        grid.append({"weekday": wd, "label": WEEKDAYS[wd], "name": WEEKDAY_NAMES[wd], "days": len(days), "cells": cells})
    hour_totals = {}
    for row in grid:
        for c in row["cells"]:
            hour_totals[c["hour"]] = hour_totals.get(c["hour"], 0) + c["prompts"] * row["days"]
    peak_hour = max(hour_totals, key=hour_totals.get)
    starts = [min(r["prompts_by_hour"]) for r in active.values() if r.get("prompts_by_hour")]
    return {
        "hours": list(range(lo, hi + 1)), "rows": grid,
        "sentence": (f"Your busiest hour is usually {peak_hour:02d}:00, and you typically start "
                     f"around {statistics.median(starts):02.0f}:00." if starts else ""),
        "peak": {"name": WEEKDAY_NAMES[best[0]], "hour": best[1]},
    }


def wait_bins(rows: dict[date, dict]) -> dict | None:
    waits = [w for r in rows.values() for w in r.get("waits_s", [])]
    if not waits:
        return None
    bins = []
    for lo, hi, label in WAIT_BINS:
        n = sum(1 for w in waits if lo <= w < hi)
        bins.append({"label": label, "n": n, "share": n / len(waits)})
    long_share = bins[-1]["share"]
    return {
        "bins": bins, "count": len(waits),
        "sentence": (f"Half the time, you answer a finished agent within {duration(statistics.median(waits))}. "
                     f"{long_share:.0%} of replies wait more than ten minutes."),
    }


def concurrency(rows: dict[date, dict]) -> dict | None:
    totals = {level: 0.0 for level, _ in LEVELS}
    for r in rows.values():
        for level, s in r.get("busy_by_level", {}).items():
            totals[min(int(level), 4)] += s
    busy = sum(totals.values())
    if not busy:
        return None
    bars = [{"label": label, "seconds": totals[level], "share": totals[level] / busy} for level, label in LEVELS]
    multi = 1 - bars[0]["share"]
    return {
        "bars": bars, "busy_s": busy,
        "sentence": (f"While agents are working, {multi:.0%} of the time you have two or more going at once."
                     if multi >= 0.005 else "While agents are working, you almost always have just one going."),
    }


def scatter(rows: dict[date, dict], metric: str) -> dict:
    """Each rated day as (metric, drain), and the same higher-half split the finding uses."""
    points = [{"date": d, "x": r[metric], "y": r["drain"]} for d, r in sorted(rows.items())
              if r.get("turns") and r.get("drain") is not None and r.get(metric) is not None]
    need = 2 * MIN_GROUP_DAYS
    return {"points": points, "need": need,
            "split": split([(p["x"], p["y"]) for p in points]) if len(points) >= need else None}


# Which links belong under which section of the page.
SECTIONS = {
    "when": ("start_hour", "end_hour", "day_length_h"),
    "waits": ("median_wait_s", "long_wait_share"),
    "busy": ("parallel_starts", "mean_concurrency", "multi_busy_share"),
}


def notes(links: dict) -> dict[str, list[dict]]:
    """The strongest significant link under each section, so a chart can say what goes with
    drain. One per section: the full list is at the top of the page, and three notes about
    one habit under one chart is noise."""
    return {name: [t for t in links["significant"] if t["key"] in keys][:1] for name, keys in SECTIONS.items()}


def standing(all_days: dict[date, dict], key: str, value: float) -> dict:
    """Where this value sits among your worked days: the shares strictly below and above it,
    so a value many days share (no parallel starts at all) is not called lower than all of them."""
    values = [r[key] for r in all_days.values() if r.get("turns") and r.get(key) is not None]
    if not values:
        return {"below": 0.0, "above": 0.0, "at": 0.5}
    below = sum(1 for v in values if v < value) / len(values)
    above = sum(1 for v in values if v > value) / len(values)
    return {"below": below, "above": above, "at": (below + 1 - above) / 2}


def trend_summary(rows: dict[date, dict], key: str) -> str:
    values = [r[key] for r in rows.values() if r.get("turns") and r.get(key) is not None]
    if not values:
        return ""
    return f"average {trend_measure(key).fmt(statistics.fmean(values))}"
