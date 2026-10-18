"""The Claude Code hook: `calmlab hook`, reading the hook payload on stdin.

What it reads from a payload: `hook_event_name`, `session_id` (hashed with a local salt
before anything is stored), `notification_type` (to skip sign-in notices), and, only to
count them, `prompt` and the final reply (from `last_assistant_message` when Claude Code
provides it, else the transcript at `transcript_path`). The prompt is also matched
against exactly `calm N`, and only the digit is kept. Everything else in the payload
(`cwd`, tool names, tool input and output, messages) is never looked at.

It writes to stdout in exactly two cases, both fixed JSON that carries nothing from the
payload: the check-in question after a Stop, and the block that keeps a `calm N` answer
from reaching the model. Anything else would be added to the model's context, so the
silence is a privacy property, not manners. It always exits 0.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time

from . import checkin, counting, scene, store

EVENT_MAP = {
    "SessionStart": "session_start",
    "UserPromptSubmit": "prompt_submit",
    "Stop": "turn_end",
    "PostToolUseFailure": "tool_fail",
    "Notification": "needs_input",
    "SessionEnd": "session_end",
}

# The hook events `calmlab setup` registers. Kept beside EVENT_MAP so the two cannot drift.
HOOK_EVENTS = tuple(EVENT_MAP)

IGNORED_NOTIFICATIONS = {"auth_success"}


def session_hash(salt: str, session_id: str) -> str:
    return hmac.new(salt.encode(), str(session_id).encode(), hashlib.sha256).hexdigest()[:16]


def recording_enabled(conn) -> bool:
    """Nothing is recorded until you have agreed in `calmlab setup`."""
    return bool(store.get_meta(conn, "consent"))


def events_for(payload: dict, salt: str, now: float) -> list[store.Event]:
    name = payload.get("hook_event_name")
    kind = EVENT_MAP.get(name)
    if kind is None or not payload.get("session_id"):
        return []
    if kind == "needs_input" and payload.get("notification_type") in IGNORED_NOTIFICATIONS:
        return []

    base = {
        "ts": now,
        "utc_offset_min": store.local_offset_min(now),
        "session": session_hash(salt, payload["session_id"]),
        "scene": scene.running(now),
    }
    if kind == "prompt_submit":
        words, tokens = counting.counts(payload.get("prompt") if isinstance(payload.get("prompt"), str) else "")
        return [
            store.Event(kind="prompt_submit", prompt_words=words, prompt_tokens=tokens, **base),
            store.Event(kind="turn_start", **base),
        ]
    if kind == "turn_end":
        reply = payload.get("last_assistant_message")
        if isinstance(reply, str):
            words, tokens = counting.counts(reply)
        else:
            words, tokens = counting.final_reply_counts(payload.get("transcript_path"))
        return [store.Event(kind="turn_end", reply_words=words, reply_tokens=tokens, **base)]
    return [store.Event(kind=kind, **base)]


def ask_output() -> dict:
    return {"systemMessage": checkin.QUESTION}


def answered_output(drain: int) -> dict:
    return {
        "decision": "block",
        "reason": checkin.RECORDED.format(n=drain),
        "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "suppressOriginalPrompt": True},
    }


def record(payload: dict, now: float | None = None) -> dict | None:
    """Store what one payload means. Returns the JSON to print, or None for silence."""
    now = now if now is not None else time.time()
    with store.connect() as conn:
        if not recording_enabled(conn):
            return None
        if payload.get("hook_event_name") == "UserPromptSubmit":
            drain = checkin.parse_answer(payload.get("prompt"))
            if drain is not None:
                checkin.answer(conn, drain, now)
                return answered_output(drain)
        written = events_for(payload, store.salt(conn), now)
        for event in written:
            store.add_event(conn, event)
        if written and written[-1].kind == "turn_end":
            trigger = checkin.due(conn, written[-1].session, now)
            if trigger:
                checkin.mark_asked(conn, trigger, now)
                return ask_output()
        return None


def main(stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    try:
        payload = json.loads(stdin.read() or "{}")
        if isinstance(payload, dict):
            out = record(payload)
            if out is not None:
                stdout.write(json.dumps(out))
    except Exception:
        # Never block or disturb a Claude Code session, and never echo what failed.
        pass
    return 0
