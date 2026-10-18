"""Whether the Vibe Nature scene is running: a heartbeat file the game writes.

The contract (also in README.md, "For the Vibe Nature side"):

    ~/.calmlab/scene.json   (or $CALMLAB_HOME/scene.json)
    {"running": true, "updated_at": 1760700000.0, "source": "vibe-nature"}

The game rewrites it at least every 30 seconds while the scene is on screen, and writes
`"running": false` when the scene is hidden or the game quits. A file older than
STALE_AFTER seconds counts as not running, so a crash cannot leave the flag stuck on.
It carries no other field and the collector reads no other field.
"""

from __future__ import annotations

import json
import os
import tempfile
import time

from . import paths

STALE_AFTER = 90.0


def write(running: bool, now: float | None = None, source: str = "manual") -> None:
    paths.ensure_home()
    target = paths.scene_path()
    payload = {"running": bool(running), "updated_at": now if now is not None else time.time(),
               "source": source}
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".scene-")
    with os.fdopen(fd, "w") as fh:
        json.dump(payload, fh)
    os.replace(tmp, target)


def running(now: float | None = None) -> bool | None:
    """True or False from a fresh heartbeat; None when the game has never reported."""
    now = now if now is not None else time.time()
    try:
        data = json.loads(paths.scene_path().read_text())
    except FileNotFoundError:
        return None
    except Exception:
        return False
    try:
        fresh = now - float(data.get("updated_at", 0)) <= STALE_AFTER
    except (TypeError, ValueError):
        return False
    return bool(data.get("running")) and fresh
