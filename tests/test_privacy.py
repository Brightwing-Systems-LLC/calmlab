"""The privacy guarantee, tested the way it would be broken: feed real-looking text through
every input the hook sees, then search every byte CalmLab wrote, and everything the hook
printed, for any piece of it."""

from __future__ import annotations

import io
import json
import sqlite3

from calmlab import checkin, hook, store

SECRET_PROMPT = "refactor the zanzibar_payroll module in /Users/alice/clients/acme-secret"
SECRET_REPLY = "I updated quixotic_ledger.py and the flamingo-billing tests now pass"
SECRET_SESSION = "session-id-7f3a-very-identifying"
SECRET_PATH_BITS = ("zanzibar", "payroll", "alice", "acme-secret", "quixotic", "ledger", "flamingo",
                    "billing", "very-identifying", "Bash", "rm -rf", "tool_output_marker")


def _transcript(tmp_path):
    path = tmp_path / "transcript.jsonl"
    lines = [
        {"type": "user", "message": {"role": "user", "content": SECRET_PROMPT}},
        {"type": "assistant", "message": {"id": "m1", "content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "rm -rf build"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "tool_output_marker"}]}},
        {"type": "assistant", "message": {"id": "m2", "content": [{"type": "text", "text": SECRET_REPLY}]}},
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines))
    return path


def _run_session(tmp_path):
    transcript = _transcript(tmp_path)
    common = {"session_id": SECRET_SESSION, "transcript_path": str(transcript),
              "cwd": "/Users/alice/clients/acme-secret"}
    payloads = [
        {**common, "hook_event_name": "SessionStart", "source": "startup"},
        {**common, "hook_event_name": "UserPromptSubmit", "prompt": SECRET_PROMPT},
        {**common, "hook_event_name": "PostToolUseFailure", "tool_name": "Bash",
         "tool_input": {"command": "rm -rf build"}, "error": "tool_output_marker zanzibar"},
        {**common, "hook_event_name": "Notification", "notification_type": "permission_prompt",
         "message": "Claude needs your permission to use Bash on zanzibar_payroll"},
        {**common, "hook_event_name": "Stop"},
        {**common, "hook_event_name": "SessionEnd", "reason": "exit"},
    ]
    for i, p in enumerate(payloads):
        hook.record(p, now=1_760_000_000 + i * 10)


def _all_written_bytes(home) -> bytes:
    return b"".join(p.read_bytes() for p in home.rglob("*") if p.is_file())


def test_no_text_reaches_the_store(consented, tmp_path):
    _run_session(tmp_path)
    blob = _all_written_bytes(consented)
    for bit in SECRET_PATH_BITS + (SECRET_SESSION,):
        assert bit.encode() not in blob, f"{bit!r} was written to disk"
    # And the database, read back through SQL rather than as bytes (pages can compress).
    conn = sqlite3.connect(consented / "calmlab.sqlite3")
    dump = "\n".join(conn.iterdump())
    for bit in SECRET_PATH_BITS + (SECRET_SESSION,):
        assert bit not in dump


def test_the_counts_are_right(consented, tmp_path):
    _run_session(tmp_path)
    with store.connect() as conn:
        events = store.events(conn)
    kinds = [e["kind"] for e in events]
    assert kinds == ["session_start", "prompt_submit", "turn_start", "tool_fail", "needs_input",
                     "turn_end", "session_end"]
    prompt = events[1]
    assert prompt["prompt_words"] == len(SECRET_PROMPT.split())
    assert prompt["prompt_tokens"] == round(len(SECRET_PROMPT) / 4)
    end = events[5]
    assert end["reply_words"] == len(SECRET_REPLY.split())
    assert {e["session"] for e in events} != {SECRET_SESSION}
    assert len(events[0]["session"]) == 16


def test_last_assistant_message_is_only_counted(consented):
    hook.record({"hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": "hi"}, now=1.0)
    hook.record({"hook_event_name": "Stop", "session_id": "s",
                 "last_assistant_message": SECRET_REPLY}, now=2.0)
    assert b"flamingo" not in _all_written_bytes(consented)
    with store.connect() as conn:
        assert store.events(conn)[-1]["reply_words"] == len(SECRET_REPLY.split())


def test_schema_has_nowhere_to_put_text(consented):
    with store.connect() as conn:
        cols = {row[1]: row[2] for row in conn.execute("PRAGMA table_info(events)")}
        checkin_cols = {row[1]: row[2] for row in conn.execute("PRAGMA table_info(checkins)")}
    text_cols = {name for name, kind in cols.items() if kind == "TEXT"}
    assert text_cols == {"kind", "session"}, "a new TEXT column on events needs a privacy review"
    checkin_text = {name for name, kind in checkin_cols.items() if kind == "TEXT"}
    assert checkin_text == {"local_date", "trigger"}, "a new TEXT column on checkins needs a privacy review"


def test_store_refuses_a_string_count(consented):
    import pytest

    with store.connect() as conn, pytest.raises(TypeError):
        store.add_event(conn, store.Event(kind="prompt_submit", ts=1, utc_offset_min=0,
                                          session="0" * 16, prompt_words="some words"))


def test_hook_prints_nothing(consented, capsys, monkeypatch):
    payload = {"hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": SECRET_PROMPT}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert hook.main() == 0
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def test_hook_swallows_garbage_silently(consented, capsys):
    assert hook.main(io.StringIO("not json zanzibar")) == 0
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def test_a_checkin_answer_keeps_only_the_digit(consented):
    hook.record({"hook_event_name": "UserPromptSubmit", "session_id": SECRET_SESSION, "prompt": "calm 4"}, now=5.0)
    with store.connect() as conn:
        assert store.events(conn) == [], "a blocked answer never reached the model, so it is not a prompt"
        (row,) = store.checkins(conn)
    assert row["drain"] == 4
    assert SECRET_SESSION.encode() not in _all_written_bytes(consented)


def test_only_an_exact_answer_is_treated_as_one(consented):
    for prompt in ("calm 4 and also refactor zanzibar", "please stay calm 4ever", "calm 9", "calm 4" + " " * 20):
        assert checkin.parse_answer(prompt) is None
        assert hook.record({"hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": prompt}) is None
    blob = _all_written_bytes(consented)
    assert b"zanzibar" not in blob and b"ever" not in blob


def test_hook_output_is_one_of_two_fixed_messages(consented, monkeypatch, utc):
    """Stdout from a UserPromptSubmit hook reaches the model, so what is printed must
    never depend on the payload beyond the one digit."""
    printed = []
    for prompt in (SECRET_PROMPT, "calm 2", "calm 5"):
        out = io.StringIO()
        payload = {"hook_event_name": "UserPromptSubmit", "session_id": SECRET_SESSION, "prompt": prompt}
        hook.main(io.StringIO(json.dumps(payload)), out)
        printed.append(out.getvalue())
    out = io.StringIO()
    stop = {"hook_event_name": "Stop", "session_id": SECRET_SESSION, "last_assistant_message": SECRET_REPLY}
    monkeypatch.setattr(hook.time, "time", lambda: 1_760_000_000 + 17 * 3600 - (1_760_000_000 % 86400))
    hook.main(io.StringIO(json.dumps(stop)), out)
    printed.append(out.getvalue())
    assert printed[0] == ""
    assert json.loads(printed[1]) == hook.answered_output(2)
    assert json.loads(printed[2]) == hook.answered_output(5)
    assert json.loads(printed[3]) == hook.ask_output()
    for text in printed:
        for bit in SECRET_PATH_BITS + (SECRET_SESSION,):
            assert bit not in text
