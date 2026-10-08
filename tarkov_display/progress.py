"""Your own progress: finished quests, hideout levels, collected items.

Stored per game mode, because PvP and PvE progress are separate in game.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

DEFAULT = {
    "player_level": 1,
    "faction": "USEC",
    "intel_center": 0,         # Intelligence Center level, lowers flea fees at 3
    "hideout_management": 0,   # Hideout Management skill level
    "tasks": [],               # finished quest ids
    "hideout": {},             # station id -> built level
    "owned": {},               # item id -> how many you have put aside
    "achievements": [],        # unlocked achievement ids
}

LIMITS = {"player_level": (1, 79), "intel_center": (0, 3), "hideout_management": (0, 51)}


class ProgressError(ValueError):
    pass


def _int(value, lo: int, hi: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ProgressError(f"not a number: {value!r}") from None
    return max(lo, min(hi, number))


def _ids(values) -> list:
    if not isinstance(values, list) or not all(isinstance(v, str) and ID.match(v) for v in values):
        raise ProgressError("bad id list")
    return values


def _clean(data: dict) -> dict:
    """A valid progress record from possibly hand-edited or imported data."""
    out = copy.deepcopy(DEFAULT)
    if not isinstance(data, dict):
        return out
    for key, (lo, hi) in LIMITS.items():
        if key in data:
            try:
                out[key] = _int(data[key], lo, hi)
            except ProgressError:
                pass
    if data.get("faction") in ("USEC", "BEAR"):
        out["faction"] = data["faction"]
    for key in ("tasks", "achievements"):
        values = data.get(key)
        if isinstance(values, list):
            out[key] = sorted({v for v in values if isinstance(v, str) and ID.match(v)})
    for key, hi in (("hideout", 10), ("owned", 99999)):
        values = data.get(key)
        if isinstance(values, dict):
            out[key] = {
                k: _int(v, 0, hi) for k, v in values.items()
                if isinstance(k, str) and ID.match(k) and isinstance(v, (int, float)) and v > 0
            }
    return out


class Progress:
    def __init__(self, path: Optional[Path]) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.data = copy.deepcopy(DEFAULT)
        if path and path.exists():
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    self.data = _clean(json.load(fh))
            except (OSError, ValueError) as exc:
                log.warning("Could not read progress file %s: %s", path, exc)

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self.data)

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=1)
        os.replace(tmp, self.path)

    def apply(self, op: dict) -> dict:
        """Change progress. ``op`` comes from the app's web page."""
        if not isinstance(op, dict):
            raise ProgressError("bad request")
        kind = op.get("op")
        with self._lock:
            d = self.data
            if kind in ("tasks", "achievements"):
                ids = set(_ids(op.get("ids")))
                current = set(d[kind])
                current = current | ids if op.get("done") else current - ids
                d[kind] = sorted(current)
            elif kind == "hideout":
                station = op.get("station")
                if not isinstance(station, str) or not ID.match(station):
                    raise ProgressError("bad station id")
                level = _int(op.get("level"), 0, 10)
                if level:
                    d["hideout"][station] = level
                else:
                    d["hideout"].pop(station, None)
            elif kind == "owned":
                item = op.get("item")
                if not isinstance(item, str) or not ID.match(item):
                    raise ProgressError("bad item id")
                count = _int(op.get("count"), 0, 99999)
                if count:
                    d["owned"][item] = count
                else:
                    d["owned"].pop(item, None)
            elif kind == "profile":
                for key, (lo, hi) in LIMITS.items():
                    if key in op:
                        d[key] = _int(op[key], lo, hi)
                if "faction" in op:
                    if op["faction"] not in ("USEC", "BEAR"):
                        raise ProgressError("faction must be USEC or BEAR")
                    d["faction"] = op["faction"]
            elif kind == "reset":
                what = op.get("what")
                if what == "all":
                    self.data = d = copy.deepcopy(DEFAULT)
                elif what in ("tasks", "achievements"):
                    d[what] = []
                elif what in ("hideout", "owned"):
                    d[what] = {}
                else:
                    raise ProgressError("nothing to reset")
            elif kind == "import":
                self.data = _clean(op.get("data"))
            else:
                raise ProgressError(f"unknown change {kind!r}")
            self._save()
            return copy.deepcopy(self.data)
