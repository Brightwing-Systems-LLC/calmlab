"""Turning text into counts, and dropping the text.

Every function here takes text and returns integers. Nothing returned, logged or raised
carries the text: errors are swallowed to `(None, None)` rather than re-raised, because an
exception message is one of the ways a string escapes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_WORD = re.compile(r"\S+")

# Only the end of a transcript is read: the final reply is always there, and a long
# session's transcript can run to many megabytes.
TAIL_BYTES = 2 * 1024 * 1024


def count_words(text: str) -> int:
    return len(_WORD.findall(text or ""))


def estimate_tokens(text: str) -> int:
    """About four characters per token for English prose and code. An estimate, used the
    same way for everyone and every day, so comparisons hold even though the
    absolute number is approximate."""
    if not text:
        return 0
    return max(1, round(len(text) / 4))


def counts(text: str | None) -> tuple[int, int]:
    text = text or ""
    return count_words(text), estimate_tokens(text)


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _is_human_prompt(entry: dict) -> bool:
    if entry.get("type") != "user":
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("type") == "text" for b in content) and not any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        )
    return False


def final_reply_counts(transcript_path: str | Path | None) -> tuple[int | None, int | None]:
    """Words and estimated tokens of the assistant's last text reply in this turn.

    Reads the transcript only to count. Returns (None, None) if it cannot tell.
    """
    if not transcript_path:
        return None, None
    try:
        path = Path(transcript_path)
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
                fh.readline()
            lines = fh.read().decode("utf-8", errors="replace").splitlines()
    except Exception:
        return None, None

    entries = []
    for line in lines:
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if isinstance(entry, dict):
            entries.append(entry)

    # Walk back from the end to the last assistant entry with text, then gather every
    # text block belonging to that same message (one reply can span several entries).
    last_id = None
    pieces: list[str] = []
    for entry in reversed(entries):
        if _is_human_prompt(entry):
            break
        if entry.get("type") != "assistant":
            continue
        message = entry.get("message") or {}
        text = _text_of(message.get("content"))
        if not text.strip():
            continue
        msg_id = message.get("id") or id(entry)
        if last_id is None:
            last_id = msg_id
        if msg_id != last_id:
            break
        pieces.append(text)
    if last_id is None:
        return 0, 0
    words, tokens = counts("\n".join(reversed(pieces)))
    del pieces, entries, lines
    return words, tokens
