from __future__ import annotations

import json
from datetime import date

import pytest

from calmlab import cli, counting, hook, install, metrics, paths, scene, store

S1, S2 = "a" * 16, "b" * 16


def ev(kind, ts, session=S1, **kw):
    return {"kind": kind, "ts": float(ts), "utc_offset_min": 0, "session": session,
            "prompt_words": kw.get("pw"), "prompt_tokens": None, "reply_words": kw.get("rw"),
            "reply_tokens": None, "scene": kw.get("scene")}


def prompt(ts, session=S1):
    return [ev("prompt_submit", ts, session, pw=5), ev("turn_start", ts, session)]


# 2026-09-14 09:00 UTC
T0 = 1_789_376_400.0


class TestHookGate:
    def test_nothing_is_recorded_before_consent(self, calmlab_home):
        assert hook.record({"hook_event_name": "SessionStart", "session_id": "x"}) is None
        with store.connect() as conn:
            assert store.events(conn) == []

    def test_unknown_events_and_auth_notifications_are_ignored(self, consented):
        hook.record({"hook_event_name": "PreToolUse", "session_id": "x"})
        hook.record({"hook_event_name": "Notification", "session_id": "x", "notification_type": "auth_success"})
        with store.connect() as conn:
            assert store.events(conn) == []

    def test_scene_flag_is_recorded(self, consented):
        scene.write(True, now=T0)
        hook.record({"hook_event_name": "SessionStart", "session_id": "x"}, now=T0 + 10)
        hook.record({"hook_event_name": "SessionEnd", "session_id": "x"}, now=T0 + 500)
        with store.connect() as conn:
            flags = [e["scene"] for e in store.events(conn)]
        assert flags == [True, False]  # the second is past the stale window


class TestScene:
    def test_never_reported(self, calmlab_home):
        assert scene.running() is None

    def test_fresh_and_stale(self, calmlab_home):
        scene.write(True, now=100.0)
        assert scene.running(now=150.0) is True
        assert scene.running(now=100.0 + scene.STALE_AFTER + 1) is False
        scene.write(False, now=200.0)
        assert scene.running(now=201.0) is False

    def test_garbage_file_is_not_running(self, calmlab_home):
        paths.ensure_home()
        paths.scene_path().write_text("{nope")
        assert scene.running() is False


class TestCounting:
    def test_final_reply_spans_entries_of_one_message(self, tmp_path):
        path = tmp_path / "t.jsonl"
        rows = [
            {"type": "user", "message": {"content": "go"}},
            {"type": "assistant", "message": {"id": "m1", "content": [{"type": "text", "text": "earlier words here"}]}},
            {"type": "assistant", "message": {"id": "m2", "content": [{"type": "text", "text": "one two"}]}},
            {"type": "assistant", "message": {"id": "m2", "content": [{"type": "text", "text": "three"}]}},
        ]
        path.write_text("\n".join(json.dumps(r) for r in rows))
        assert counting.final_reply_counts(path)[0] == 3

    def test_missing_transcript(self):
        assert counting.final_reply_counts("/nope/missing.jsonl") == (None, None)

    def test_no_reply_since_prompt(self, tmp_path):
        path = tmp_path / "t.jsonl"
        path.write_text(json.dumps({"type": "user", "message": {"content": "go"}}))
        assert counting.final_reply_counts(path) == (0, 0)


class TestMetrics:
    def day(self):
        return [
            ev("session_start", T0),
            *prompt(T0 + 10),
            ev("turn_end", T0 + 130, rw=300),          # 2 min turn
            *prompt(T0 + 190),                          # 60 s wait
            ev("session_start", T0 + 200, S2),          # parallel: S1 running
            *prompt(T0 + 210, S2),                      # parallel: S1 running
            ev("turn_end", T0 + 250, rw=100),           # S1 ends
            ev("turn_end", T0 + 400, S2, rw=50),
            *prompt(T0 + 2000, S2),                     # 26 min gap: a break
            ev("turn_end", T0 + 2100, S2, rw=10),
        ]

    def test_turns_and_waits(self):
        turns = metrics.build_turns(self.day())
        s1 = [t for t in turns if t.session == S1]
        assert [t.duration_s for t in s1] == [120, 60]
        assert s1[0].wait_s == 60
        assert s1[1].wait_s is None

    def test_parallel_starts(self):
        a = metrics.analyse(self.day())
        assert [(p["kind"], p["ts"]) for p in a.parallel_starts] == [
            ("session_start", T0 + 200), ("prompt_submit", T0 + 210)]

    def test_daily_numbers(self):
        (m,) = metrics.daily(self.day()).values()
        assert m["prompts"] == 4
        assert m["parallel_starts"] == 2
        assert m["peak_concurrency"] == 2
        assert m["sessions"] == 2
        assert m["day_length_h"] == pytest.approx(2100 / 3600)
        # Activity runs T0..T0+400, then a gap over 10 minutes, then 2000..2100.
        assert m["longest_stretch_min"] == pytest.approx(400 / 60)
        assert m["median_reply_words"] == 75

    def test_an_unclosed_turn_does_not_run_forever(self):
        turns = metrics.build_turns([*prompt(T0), *prompt(T0 + 50_000)])
        assert all(t.duration_s <= metrics.MAX_TURN_S for t in turns)

    def test_local_date_uses_offset(self):
        late = [dict(e, utc_offset_min=-300) for e in prompt(T0 - 3600 * 12)]  # 21:00 UTC prev day
        assert list(metrics.daily(late)) == [date(2026, 9, 13)]


class TestInstall:
    EXISTING = {"model": "opus", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]}}

    def test_dry_run_writes_nothing(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps(self.EXISTING))
        lines = []
        assert install.install(path, dry_run=True, command="/x/calmlab hook", out=lines.append) is None
        assert json.loads(path.read_text()) == self.EXISTING
        assert "calmlab hook" in lines[0]
        assert list(tmp_path.iterdir()) == [path]

    def test_install_backs_up_merges_and_uninstall_restores(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps(self.EXISTING))
        assert not install.installed(path)
        backup = install.install(path, command="/x/calmlab hook", out=lambda s: None)
        assert install.installed(path)
        assert json.loads(backup.read_text()) == self.EXISTING
        data = json.loads(path.read_text())
        assert data["model"] == "opus"
        assert set(data["hooks"]) == set(hook.HOOK_EVENTS)
        assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "say done"
        # Installing twice does not duplicate.
        install.install(path, command="/x/calmlab hook", out=lambda s: None)
        assert len(json.loads(path.read_text())["hooks"]["Stop"]) == 2
        install.uninstall(path, out=lambda s: None)
        assert json.loads(path.read_text()) == self.EXISTING
        assert not install.installed(path)

    def test_install_into_missing_file(self, tmp_path):
        path = tmp_path / "nested" / "settings.json"
        install.install(path, command="calmlab hook", out=lambda s: None)
        install.uninstall(path, out=lambda s: None)
        assert json.loads(path.read_text()) == {}


class TestCli:
    def test_setup_status_uninstall_delete(self, calmlab_home, tmp_path, capsys):
        settings = tmp_path / "settings.json"
        assert cli.main(["setup", "--yes", "--settings", str(settings)]) == 0
        assert install.installed(settings)
        assert hook.record({"hook_event_name": "SessionStart", "session_id": "x"}, now=T0) is None
        with store.connect() as conn:
            assert len(store.events(conn)) == 1
        assert cli.main(["status", "--settings", str(settings)]) == 0
        assert "Recording:    on" in capsys.readouterr().out
        assert cli.main(["uninstall", "--settings", str(settings)]) == 0
        assert not install.installed(settings)
        assert cli.main(["delete", "--yes"]) == 0
        assert not calmlab_home.exists()

    def test_setup_declined_records_nothing(self, calmlab_home, tmp_path, monkeypatch):
        settings = tmp_path / "settings.json"
        monkeypatch.setattr("builtins.input", lambda prompt="": "")
        assert cli.main(["setup", "--settings", str(settings)]) == 1
        assert not settings.exists()
        hook.record({"hook_event_name": "SessionStart", "session_id": "x"}, now=T0)
        with store.connect() as conn:
            assert store.events(conn) == []

    def test_the_hook_path_never_imports_flask(self):
        import subprocess
        import sys

        code = "import sys, calmlab.cli, calmlab.hook; print('flask' in sys.modules)"
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
        assert out.stdout.strip() == "False"
