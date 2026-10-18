"""Baseline vs scene comparisons with confidence intervals.

The unit of analysis is the tester, not the day: days from one person are not
independent, so each tester contributes one mean per condition and the interval comes
from resampling testers (a percentile bootstrap, fixed seed so a page renders the same
numbers twice). With one tester it falls back to resampling that tester's days and says
so, because that interval describes one person rather than a population.
"""

from __future__ import annotations

import random
import statistics
from collections import defaultdict

RESAMPLES = 2000


def _mean(values):
    return statistics.fmean(values) if values else None


def bootstrap_ci(values: list[float], level: float = 0.95, seed: int = 11) -> tuple[float, float] | None:
    values = [v for v in values if v is not None]
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    n = len(values)
    means = sorted(statistics.fmean(rng.choices(values, k=n)) for _ in range(RESAMPLES))
    lo_i = int((1 - level) / 2 * RESAMPLES)
    hi_i = int((1 + level) / 2 * RESAMPLES) - 1
    return means[lo_i], means[hi_i]


def paired_effect(rows: list[dict], metric: str) -> dict:
    """rows: dicts with `tester`, `condition` ('baseline'|'scene') and the metric.

    Returns condition means, the mean within-tester difference (scene - baseline), its
    95% CI, the relative change and how many testers had both conditions.
    """
    per: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        v = r.get(metric)
        if v is None or r.get("condition") not in ("baseline", "scene"):
            continue
        per[r["tester"]][r["condition"]].append(float(v))

    paired = {t: c for t, c in per.items() if c.get("baseline") and c.get("scene")}
    base_means = [_mean(c["baseline"]) for c in paired.values()]
    scene_means = [_mean(c["scene"]) for c in paired.values()]
    diffs = [s - b for s, b in zip(scene_means, base_means, strict=True)]

    unit = "testers"
    ci = bootstrap_ci(diffs)
    base_ci, scene_ci = bootstrap_ci(base_means), bootstrap_ci(scene_means)
    if len(paired) == 1:
        (only,) = paired.values()
        unit = "days (one tester)"
        b, s = only["baseline"], only["scene"]
        base_ci, scene_ci = bootstrap_ci(b), bootstrap_ci(s)
        rng = random.Random(5)
        sims = sorted(
            statistics.fmean(rng.choices(s, k=len(s))) - statistics.fmean(rng.choices(b, k=len(b)))
            for _ in range(RESAMPLES)
        )
        ci = (sims[int(0.025 * RESAMPLES)], sims[int(0.975 * RESAMPLES) - 1]) if len(b) > 1 and len(s) > 1 else None

    base = _mean(base_means)
    diff = _mean(diffs)
    return {
        "metric": metric,
        "n": len(paired),
        "unit": unit,
        "baseline": base,
        "baseline_ci": base_ci,
        "scene": _mean(scene_means),
        "scene_ci": scene_ci,
        "diff": diff,
        "diff_ci": ci,
        "relative": (diff / base) if (diff is not None and base) else None,
        "per_tester": [
            {"tester": t, "baseline": b, "scene": s}
            for t, b, s in zip(paired, base_means, scene_means, strict=True)
        ],
    }
