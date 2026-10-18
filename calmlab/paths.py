"""Where CalmLab keeps its files. Everything lives under one folder."""

from __future__ import annotations

import os
from pathlib import Path


def home() -> Path:
    """`CALMLAB_HOME` if set (tests, or to keep it elsewhere), else ~/.calmlab."""
    return Path(os.environ.get("CALMLAB_HOME") or Path.home() / ".calmlab")


def db_path() -> Path:
    return home() / "calmlab.sqlite3"


def scene_path() -> Path:
    return home() / "scene.json"


def ensure_home() -> Path:
    path = home()
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path
