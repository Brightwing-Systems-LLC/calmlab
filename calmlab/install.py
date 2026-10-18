"""Adding and removing the collector's hooks in a Claude Code settings file.

Runs only on your own machine. It merges into what is there (other
hooks are left exactly as they were), always writes a timestamped backup first, and
`--dry-run` shows the result without writing. Our entries are recognised by their
command ending in `calmlab hook`, which is also how uninstall finds them.
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import time
from pathlib import Path

from .hook import HOOK_EVENTS

MARKER = "calmlab hook"
DEFAULT_SETTINGS = Path.home() / ".claude" / "settings.json"


def hook_command() -> str:
    exe = shutil.which("calmlab")
    if exe:
        return f'"{exe}" hook' if " " in exe else f"{exe} hook"
    return f"{sys.executable} -m calmlab hook"


def _ours(entry: dict) -> bool:
    return any(MARKER in (h.get("command") or "") for h in entry.get("hooks", []))


def with_hooks(settings: dict, command: str) -> dict:
    out = copy.deepcopy(settings)
    hooks = out.setdefault("hooks", {})
    for event in HOOK_EVENTS:
        entries = [e for e in hooks.get(event, []) if not _ours(e)]
        entries.append({"hooks": [{"type": "command", "command": command, "timeout": 10}]})
        hooks[event] = entries
    return out


def without_hooks(settings: dict) -> dict:
    out = copy.deepcopy(settings)
    hooks = out.get("hooks")
    if not isinstance(hooks, dict):
        return out
    for event in list(hooks):
        kept = [e for e in hooks[event] if not _ours(e)]
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if not hooks:
        del out["hooks"]
    return out


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text()
    return json.loads(text) if text.strip() else {}


def apply(path: Path, transform, dry_run: bool, out=print) -> Path | None:
    """Rewrite `path` through `transform`. Returns the backup path, or None on dry run."""
    current = _read(path)
    updated = transform(current)
    rendered = json.dumps(updated, indent=2) + "\n"
    if dry_run:
        out(f"Dry run: {path} would become:\n{rendered}")
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if path.exists():
        backup = path.with_name(f"{path.name}.calmlab-backup-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(path, backup)
        out(f"Backed up {path} to {backup}")
    tmp = path.with_name(path.name + ".calmlab-tmp")
    tmp.write_text(rendered)
    tmp.replace(path)
    out(f"Wrote {path}")
    return backup


def installed(path: Path = DEFAULT_SETTINGS) -> bool:
    try:
        hooks = _read(path).get("hooks") or {}
    except Exception:
        return False
    return all(any(_ours(e) for e in hooks.get(event, [])) for event in HOOK_EVENTS)


def install(path: Path = DEFAULT_SETTINGS, dry_run: bool = False, command: str | None = None, out=print):
    command = command or hook_command()
    return apply(path, lambda s: with_hooks(s, command), dry_run, out)


def uninstall(path: Path = DEFAULT_SETTINGS, dry_run: bool = False, out=print):
    return apply(path, without_hooks, dry_run, out)
