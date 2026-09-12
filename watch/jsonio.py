"""Read and write the watcher's JSON files without losing them on a crash.

Both the state file and the history file are rewritten on every poll while a
GitHub Actions job may be cancelled at any moment, so writes go to a temporary
file in the same directory and are then renamed over the target. os.replace is
atomic on POSIX and on Windows, so a reader never sees a half-written file.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def read_json(path: str | Path, default: Any, what: str) -> Any:
    """Return the parsed contents of `path`, or `default` if it cannot be read.

    `what` names the file in the warning logged when it is unreadable.
    """
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        log.warning("%s file unreadable (%s); starting fresh", what, e)
        return default


def write_json(path: str | Path, data: Any, sort_keys: bool = False) -> None:
    """Write `data` as pretty JSON, replacing `path` atomically."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=sort_keys) + "\n", encoding="utf-8")
    os.replace(tmp, p)
