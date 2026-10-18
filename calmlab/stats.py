"""Two kinds of statistics: links between a day measure and drain, and baseline vs
scene comparisons.

Links use Spearman's rank correlation, because drain is a 1 to 5 rating and the day
measures are skewed; ranks ask only "do higher days go with higher drain". The p-value
comes from shuffling drain across days (a permutation test, fixed seed so a page shows
the same numbers twice), which needs no assumption about how the values are spread.
Several measures are tested at once, so `significant()` applies the Benjamini-Hochberg
correction: a link is shown only if it survives having looked at all of them.

For baseline vs scene, the unit of analysis is the tester, not the day: days from one person are not
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
PERMUTATIONS = 2000
FALSE_DISCOVERY_RATE = 0.05


def ranks(values: list[float]) -> list[float]:
    """1-based ranks, ties sharing the average of the ranks they span."""
    order = sorted(range(len(values)), key=values.__getitem__)
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    sxx, syy = sum(d * d for d in dx), sum(d * d for d in dy)
    if sxx == 0 or syy == 0:
        return None
    return sum(a * b for a, b in zip(dx, dy, strict=True)) / (sxx * syy) ** 0.5


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Rank correlation, or None when either side has no variation to rank."""
    if len(xs) < 3:
        return None
    return _pearson(ranks(xs), ranks(ys))


def spearman_test(xs: list[float], ys: list[float], seed: int = 17) -> tuple[float, float] | None:
    """(rho, two-sided permutation p-value), or None when rho is undefined."""
    rx, ry = ranks(xs), ranks(ys)
    rho = _pearson(rx, ry)
    if rho is None:
        return None
    rng = random.Random(seed)
    shuffled = list(ry)
    hits = 0
    for _ in range(PERMUTATIONS):
        rng.shuffle(shuffled)
        r = _pearson(rx, shuffled)
        if r is not None and abs(r) >= abs(rho) - 1e-12:
            hits += 1
    return rho, (hits + 1) / (PERMUTATIONS + 1)


def significant(pvalues: list[float], rate: float = FALSE_DISCOVERY_RATE) -> list[bool]:
    """Benjamini-Hochberg: which of these tests survive, keeping false discoveries under `rate`."""
    m = len(pvalues)
    order = sorted(range(m), key=pvalues.__getitem__)
    passed = 0
    for rank, i in enumerate(order, start=1):
        if pvalues[i] <= rank / m * rate:
            passed = rank
    keep = set(order[:passed])
    return [i in keep for i in range(m)]


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
