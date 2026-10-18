from __future__ import annotations

import pytest

from calmlab import checkin, hook, store

# 2026-09-14 00:00 UTC
DAY = 1_789_344_000.0
H = 3600


def at(hour: float) -> float:
    return DAY + hour * H


def stop(now, session="s1"):
    return hook.record({"hook_event_name": "Stop", "session_id": session, "last_assistant_message": "ok"}, now=now)


def submit(now, text="go", session="s1"):
    return hook.record({"hook_event_name": "UserPromptSubmit", "session_id": session, "prompt": text}, now=now)


@pytest.mark.parametrize("text,expected", [
    ("calm 3", 3), ("Calm 1", 1), ("  calm   5 ", 5), ("calm 0", None), ("calm 6", None),
    ("calm3", None), ("calm 3 thanks", None), ("i am calm 3", None), (None, None), (3, None),
])
def test_parse_answer(text, expected):
    assert checkin.parse_answer(text) == expected


def test_end_of_day_is_asked_once_after_four_pm(consented, utc):
    submit(at(15))
    assert stop(at(15.2)) is None
    submit(at(16.1))
    assert stop(at(16.2)) == hook.ask_output()
    submit(at(16.5))
    assert stop(at(16.6)) is None


def test_long_session_is_asked_after_ninety_minutes(consented, utc):
    for minute in range(0, 100, 10):
        submit(at(9 + minute / 60))
        out = stop(at(9 + (minute + 5) / 60))
        if minute + 5 < 90:
            assert out is None
    with store.connect() as conn:
        assert store.get_meta(conn, "checkin_pending")["trigger"] == "long_session"


def test_a_thirty_minute_break_restarts_the_session_clock(consented, utc):
    submit(at(9))
    stop(at(9.1))
    submit(at(10.5))  # 84 minutes later: a break
    assert stop(at(10.6)) is None


def test_at_most_two_a_day_and_three_hours_apart(consented, utc):
    for minute in range(0, 100, 10):  # long-session question at about 14:35
        submit(at(13 + minute / 60))
        stop(at(13 + (minute + 5) / 60))
    submit(at(16.0))
    assert stop(at(16.1)) is None, "three hours have not passed since the long-session ask"
    submit(at(18.0))
    assert stop(at(18.1)) == hook.ask_output()
    submit(at(23.0))
    assert stop(at(23.1)) is None, "two a day"


def test_an_answer_files_under_what_asked_it(consented, utc):
    submit(at(16.1))
    stop(at(16.2))
    assert submit(at(16.25), "calm 2") == hook.answered_output(2)
    submit(at(16.3), "calm 4")
    with store.connect() as conn:
        rows = store.checkins(conn)
        assert checkin.pending(conn, at(16.4)) is None
    assert [(r["drain"], r["trigger"]) for r in rows] == [(2, "end_of_day"), (4, "self")]
    assert rows[0]["asked_at"] == at(16.2)


def test_a_stale_question_is_answered_as_self(consented, utc):
    submit(at(16.1))
    stop(at(16.2))
    submit(at(16.2 + 3), "calm 3")
    with store.connect() as conn:
        (row,) = store.checkins(conn)
    assert row["trigger"] == "self"


def test_store_refuses_bad_checkins(consented):
    with store.connect() as conn:
        for bad in (0, 6, "3", 2.5, True):
            with pytest.raises(ValueError):
                store.add_checkin(conn, bad, "self")
        with pytest.raises(ValueError):
            store.add_checkin(conn, 3, "whenever")
