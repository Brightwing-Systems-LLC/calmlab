from __future__ import annotations

from datetime import date, timedelta

from calmlab import findings


def fake_days(pairs):
    """{date: row} from (parallel_starts, drain) pairs, other metrics flat."""
    start = date(2026, 9, 1)
    out = {}
    for i, (ps, drain) in enumerate(pairs):
        out[start + timedelta(days=i)] = {
            "turns": 10, "parallel_starts": ps, "drain": drain, "checkins": 1 if drain else 0,
            "mean_concurrency": 1.5, "day_length_h": 8.0, "longest_stretch_min": 90.0,
            "median_wait_s": 120.0, "prompts_per_hour": 10.0, "waits_s": [120.0],
        }
    return out


def test_not_ready_before_seven_days_with_a_checkin():
    f = findings.finding(fake_days([(10, 3)] * 6 + [(10, None)] * 5))
    assert f == {"ready": False, "have": 6, "need": 7}


def test_finds_the_split_that_lines_up_with_drain():
    f = findings.finding(fake_days([(5, 2), (8, 2), (6, 1), (30, 4), (40, 5), (35, 4), (7, 2), (33, 4)]))
    assert f["found"] and f["metric"] == "parallel_starts"
    assert f["threshold"] == 30
    assert f["diff"] > 2
    sentence = f"{f['lead']} {f['emph']}{f['middle']} {f['feel']}."
    assert sentence.startswith("On days you start 30 or more agents while another is still running, you rate yourself")
    assert sentence.endswith("points more drained.")


def test_says_so_when_there_is_no_pattern():
    f = findings.finding(fake_days([(5, 3), (30, 3), (6, 3), (31, 3), (7, 3), (32, 3), (8, 3)]))
    assert f == {"ready": True, "found": False, "days": 7}


def test_days_joins_checkins_onto_metric_days():
    events = [
        {"kind": "prompt_submit", "ts": 1_789_376_400.0, "utc_offset_min": 0, "session": "a" * 16,
         "prompt_words": 3, "prompt_tokens": 1, "reply_words": None, "reply_tokens": None, "scene": None},
        {"kind": "turn_start", "ts": 1_789_376_400.0, "utc_offset_min": 0, "session": "a" * 16,
         "prompt_words": None, "prompt_tokens": None, "reply_words": None, "reply_tokens": None, "scene": None},
    ]
    checkins = [{"local_date": "2026-09-14", "drain": 2}, {"local_date": "2026-09-14", "drain": 4},
                {"local_date": "2026-09-15", "drain": 5}]
    days = findings.days(events, checkins)
    assert days[date(2026, 9, 14)]["drain"] == 3 and days[date(2026, 9, 14)]["checkins"] == 2
    assert days[date(2026, 9, 15)]["turns"] == 0


def test_delta_and_duration():
    assert findings.delta(None, 3) == ""
    assert findings.delta(3.04, 3.0) == "same as last week"
    assert findings.delta(2.5, 3.0) == "−0.5 vs last week"
    assert findings.delta(200, 100, "duration") == "+1m 40s vs last week"
    assert findings.delta(90, 30, "minutes") == "+1h 00m vs last week"
    assert findings.duration(45) == "45s"
    assert findings.duration(600) == "10m"
    assert findings.duration(5400) == "1h 30m"
