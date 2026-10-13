"""Your own markers with notes, pinned on the map images.

Kept per map image (the 2D and 3D images of a map have different layouts)
and shared by PvP and PvE, because the maps are the same in both. A marker's
position is a fraction of the image's width and height, so it stays put
whatever size the image is shown at.
"""

from __future__ import annotations

import copy
import json
import logging
import math
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

IMAGE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ID = re.compile(r"^[a-f0-9]{1,32}$")
COLORS = ("yellow", "red", "green", "blue", "purple", "white")
MAX_NOTE = 500
MAX_PER_IMAGE = 300


class MarkerError(ValueError):
    pass


def _pos(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise MarkerError(f"bad position: {value!r}")
    return round(max(0.0, min(1.0, float(value))), 5)


def _note(value) -> str:
    if not isinstance(value, str):
        raise MarkerError("the note must be text")
    return value.strip()[:MAX_NOTE]


def _color(value) -> str:
    if value not in COLORS:
        raise MarkerError(f"colour must be one of {', '.join(COLORS)}")
    return value


def _image(value) -> str:
    if not isinstance(value, str) or not IMAGE.match(value):
        raise MarkerError("bad map image")
    return value


def _marker(raw) -> Optional[dict]:
    """A valid marker from saved data, or None."""
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not ID.match(raw["id"]):
        return None
    try:
        out = {"id": raw["id"], "x": _pos(raw.get("x")), "y": _pos(raw.get("y")),
               "note": _note(raw.get("note", "")), "color": raw.get("color") if raw.get("color") in COLORS else COLORS[0]}
    except MarkerError:
        return None
    created = raw.get("created")
    out["created"] = int(created) if isinstance(created, (int, float)) and math.isfinite(created) and created > 0 else 0
    return out


def _clean(data) -> dict:
    out = {}
    if not isinstance(data, dict):
        return out
    for image, markers in data.items():
        if not isinstance(image, str) or not IMAGE.match(image) or not isinstance(markers, list):
            continue
        good = [m for m in map(_marker, markers) if m][:MAX_PER_IMAGE]
        if good:
            out[image] = good
    return out


class Markers:
    def __init__(self, path: Optional[Path]) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.data: dict = {}
        if path and path.exists():
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    self.data = _clean(json.load(fh))
            except Exception as exc:  # a damaged file must never stop the app starting
                log.warning("Could not read map markers %s: %s", path, exc)
                try:  # keep it: the next save would overwrite it
                    shutil.copy2(path, path.with_name(path.stem + ".unreadable" + path.suffix))
                except OSError:
                    pass

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

    def apply(self, op) -> dict:
        """Change the markers. ``op`` comes from the app's web page."""
        if not isinstance(op, dict):
            raise MarkerError("bad request")
        kind = op.get("op")
        image = _image(op.get("image"))
        with self._lock:
            markers = list(self.data.get(image, []))
            if kind == "add":
                if len(markers) >= MAX_PER_IMAGE:
                    raise MarkerError(f"this map already has {MAX_PER_IMAGE} markers")
                markers.append({"id": uuid.uuid4().hex[:12], "x": _pos(op.get("x")), "y": _pos(op.get("y")),
                                "note": _note(op.get("note", "")), "color": _color(op.get("color", COLORS[0])),
                                "created": int(time.time())})
            elif kind in ("update", "delete"):
                marker_id = op.get("id")
                found = next((m for m in markers if m["id"] == marker_id), None)
                if found is None:
                    raise MarkerError("that marker doesn't exist any more")
                if kind == "delete":
                    markers.remove(found)
                else:
                    changes = {}
                    for key, check in (("x", _pos), ("y", _pos), ("note", _note), ("color", _color)):
                        if key in op:
                            changes[key] = check(op[key])
                    found.update(changes)
            elif kind == "clear":
                markers.clear()
            else:
                raise MarkerError(f"unknown change {kind!r}")
            if markers:
                self.data[image] = markers
            else:
                self.data.pop(image, None)
            self._save()
            return copy.deepcopy(self.data)
