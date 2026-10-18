from __future__ import annotations

from datetime import date, timedelta

from calmlab import patterns


def day(**kw):
    row = {"turns": 10, "waits_s": [], "busy_by_level": {}, "prompts_by_hour": {}, "parallel_by_hour": {}}
    return {**row, **kw}


def test_window_picks_the_range_and_falls_back_to_eight_weeks():
    today = date(2026, 10, 18)
    all_days = {today - timedelta(days=n): day() for n in (0, 10, 30, 90)}
    assert len(patterns.window(all_days, today, "14")[2]) == 2
    assert len(patterns.window(all_days, today, "56")[2]) == 3
    assert len(patterns.window(all_days, today, "nonsense")[2]) == 3
    start, _, rows = patterns.window(all_days, today, "all")
    assert start == today - timedelta(days=90) and len(rows) == 4


def test_wait_bins_share_out_every_wait():
    w = patterns.wait_bins({date(2026, 9, 1): day(waits_s=[10, 40, 100, 300, 900])})
    assert [b["n"] for b in w["bins"]] == [1, 2, 1, 1]
    assert abs(sum(b["share"] for b in w["bins"]) - 1) < 1e-9
    assert "within 1m 40s" in w["sentence"] and "20%" in w["sentence"]


def test_concurrency_folds_four_and_up_together():
    c = patterns.concurrency({date(2026, 9, 1): day(busy_by_level={1: 600, 2: 300, 4: 50, 5: 50})})
    assert [round(b["share"], 2) for b in c["bars"]] == [0.6, 0.3, 0.0, 0.1]
    assert "40%" in c["sentence"]
    assert patterns.concurrency({date(2026, 9, 1): day()}) is None


def test_hour_grid_averages_over_the_days_of_each_weekday():
    mon1, mon2, tue = date(2026, 9, 7), date(2026, 9, 14), date(2026, 9, 8)
    g = patterns.hour_grid({
        mon1: day(prompts_by_hour={9: 4, 14: 10}), mon2: day(prompts_by_hour={9: 2}),
        tue: day(prompts_by_hour={10: 6}), date(2026, 9, 9): day(turns=0),
    })
    assert [r["label"] for r in g["rows"]] == ["Mon", "Tue"], "a weekday never worked gets no row"
    mon = {c["hour"]: c["prompts"] for c in g["rows"][0]["cells"]}
    assert mon[9] == 3 and mon[14] == 5
    assert g["hours"][0] <= 8 and g["hours"][-1] >= 18
    assert "busiest hour is usually 14:00" in g["sentence"]


def test_scatter_splits_at_the_median_once_there_are_enough_days():
    rows = {date(2026, 9, i): day(parallel_starts=ps, drain=dr)
            for i, (ps, dr) in enumerate([(5, 2), (6, 2), (7, 1), (30, 4), (31, 5), (32, 4)], start=1)}
    s = patterns.scatter(rows, "parallel_starts")
    assert len(s["points"]) == 6
    assert s["split"]["cut"] == 30, "the lowest value in the higher half"
    assert round(s["split"]["high"], 2) == 4.33 and round(s["split"]["low"], 2) == 1.67
    few = patterns.scatter(dict(list(rows.items())[:5]), "parallel_starts")
    assert few["split"] is None


def test_standing_counts_ties_as_neither_side():
    rows = {date(2026, 9, i): day(parallel_starts=v) for i, v in enumerate([0, 0, 0, 0, 5, 9, 12, 20], start=1)}
    s = patterns.standing(rows, "parallel_starts", 0)
    assert s["below"] == 0 and s["above"] == 0.5
    s = patterns.standing(rows, "parallel_starts", 20)
    assert s["below"] == 0.875 and s["above"] == 0
