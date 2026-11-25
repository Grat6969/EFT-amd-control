"""Your own progress: finished quests, hideout levels, collected items.

Stored per game mode, because PvP and PvE progress are separate in game.
"""

from __future__ import annotations

import copy
import json
import logging
import math
import os
import shutil
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
    "pinned": [],              # quest ids picked for the next raid
    "objectives": {},          # objective id -> how far along (count done; 1 = done)
    # For the "Ask Claude" export: what you usually take into raid and what you're after.
    "advisor": {"kit": "", "roubles": 0, "goal": "", "notes": ""},
    # Story chapters (see story.py): finished step ids, and a note per chapter (choices made).
    "story": {"steps": [], "notes": {}},
    # Trader id -> {"level": loyalty level (0 = not unlocked), "rep": standing}. Empty = not set
    # up yet, and quest availability ignores trader requirements.
    "traders": {},
    # Quests the game's logs say you accepted (and haven't finished) or failed.
    "accepted": [],
    "failed": [],
}

NOTE_LIMIT = 500
KITS = ("", "budget", "mid", "geared", "meta")
TEXT_LIMITS = {"goal": 200, "notes": 1000}

LIMITS = {"player_level": (1, 79), "intel_center": (0, 3), "hideout_management": (0, 51)}


class ProgressError(ValueError):
    pass


def _trader(data: dict, base: dict) -> dict:
    """Loyalty level 0-4 and reputation -7..10 (a standing of 0.42 is kept to 2 decimals)."""
    out = dict(base)
    if "level" in data:
        out["level"] = _int(data["level"], 0, 4)
    if "rep" in data:
        rep = data["rep"]
        if rep is None or rep == "":
            out.pop("rep", None)
        else:
            try:
                rep = float(rep)
            except (TypeError, ValueError):
                raise ProgressError(f"not a number: {rep!r}") from None
            if not math.isfinite(rep):
                raise ProgressError("bad reputation")
            out["rep"] = round(max(-7.0, min(10.0, rep)), 2)
    return out


def _advisor(data, base: dict, strict: bool = False) -> dict:
    """The advisor settings in ``data`` laid over ``base``."""
    out = dict(base)
    if not isinstance(data, dict):
        if strict:
            raise ProgressError("bad request")
        return out
    if "kit" in data:
        if data["kit"] in KITS:
            out["kit"] = data["kit"]
        elif strict:
            raise ProgressError("unknown kit")
    if "roubles" in data:
        try:
            out["roubles"] = _int(data["roubles"], 0, 10_000_000_000)
        except ProgressError:
            if strict:
                raise
    for key, limit in TEXT_LIMITS.items():
        if key in data:
            if isinstance(data[key], str):
                out[key] = data[key].strip()[:limit]
            elif strict:
                raise ProgressError(f"{key} must be text")
    return out


def _int(value, lo: int, hi: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):  # JSON allows Infinity, and int() of it overflows
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
    for key in ("tasks", "achievements", "pinned"):
        values = data.get(key)
        if isinstance(values, list):
            out[key] = sorted({v for v in values if isinstance(v, str) and ID.match(v)})
    for key, hi in (("hideout", 10), ("owned", 99999), ("objectives", 9999)):
        values = data.get(key)
        if isinstance(values, dict):
            out[key] = {
                k: _int(v, 0, hi) for k, v in values.items()
                if isinstance(k, str) and ID.match(k) and isinstance(v, (int, float)) and math.isfinite(v) and v > 0
            }
    out["advisor"] = _advisor(data.get("advisor"), out["advisor"])
    traders = data.get("traders") if isinstance(data.get("traders"), dict) else {}
    out["traders"] = {}
    for tid, v in traders.items():
        if isinstance(tid, str) and ID.match(tid) and isinstance(v, dict):
            try:
                out["traders"][tid] = _trader(v, {})
            except ProgressError:
                pass
    for key in ("accepted", "failed"):
        values = data.get(key)
        if isinstance(values, list):
            out[key] = sorted({v for v in values if isinstance(v, str) and ID.match(v)} - set(out["tasks"]))
    story = data.get("story") if isinstance(data.get("story"), dict) else {}
    steps = story.get("steps")
    notes = story.get("notes")
    out["story"] = {
        "steps": sorted({v for v in steps if isinstance(v, str) and ID.match(v)}) if isinstance(steps, list) else [],
        "notes": {k: v.strip()[:NOTE_LIMIT] for k, v in notes.items()
                  if isinstance(k, str) and ID.match(k) and isinstance(v, str) and v.strip()} if isinstance(notes, dict) else {},
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
            except Exception as exc:  # a damaged file must never stop the app starting
                log.warning("Could not read progress file %s: %s", path, exc)
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
                if kind == "tasks" and op.get("done"):  # finished quests leave the raid plan
                    d["pinned"] = [t for t in d["pinned"] if t not in ids]
                    for key in ("accepted", "failed"):
                        d[key] = [t for t in d.get(key, []) if t not in ids]
            elif kind == "pin":
                ids = set(_ids(op.get("ids")))
                current = set(d["pinned"])
                d["pinned"] = sorted(current | ids if op.get("pinned") else current - ids)
            elif kind == "objective":
                objective = op.get("id")
                if not isinstance(objective, str) or not ID.match(objective):
                    raise ProgressError("bad objective id")
                count = _int(op.get("count"), 0, 9999)
                if count:
                    d["objectives"][objective] = count
                else:
                    d["objectives"].pop(objective, None)
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
            elif kind == "owned_many":  # several at once, e.g. keys read off a screenshot
                items = op.get("items")
                if not isinstance(items, dict) or len(items) > 500:
                    raise ProgressError("bad items")
                for item, count in items.items():
                    if not isinstance(item, str) or not ID.match(item):
                        raise ProgressError("bad item id")
                    count = _int(count, 0, 99999)
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
            elif kind == "advisor":
                d["advisor"] = _advisor(op.get("settings"), d.get("advisor") or DEFAULT["advisor"], strict=True)
            elif kind == "trader":
                tid = op.get("id")
                if not isinstance(tid, str) or not ID.match(tid):
                    raise ProgressError("bad trader id")
                traders = d.setdefault("traders", {})
                traders[tid] = _trader(op, traders.get(tid, {}))
            elif kind == "quest_status":
                # From the game logs: "accepted", "failed" or "none" (neither).
                ids, status = set(_ids(op.get("ids"))), op.get("status")
                if status not in ("accepted", "failed", "none"):
                    raise ProgressError("bad quest status")
                for key in ("accepted", "failed"):
                    current = set(d.get(key, [])) - ids
                    if status == key:
                        current |= ids - set(d["tasks"])
                    d[key] = sorted(current)
            elif kind == "story":
                story = d.setdefault("story", {"steps": [], "notes": {}})
                ids = set(_ids(op.get("ids")))
                current = set(story["steps"])
                story["steps"] = sorted(current | ids if op.get("done") else current - ids)
            elif kind == "story_note":
                chapter, text = op.get("chapter"), op.get("text")
                if not isinstance(chapter, str) or not ID.match(chapter) or not isinstance(text, str):
                    raise ProgressError("bad story note")
                story = d.setdefault("story", {"steps": [], "notes": {}})
                if text.strip():
                    story["notes"][chapter] = text.strip()[:NOTE_LIMIT]
                else:
                    story["notes"].pop(chapter, None)
            elif kind == "reset":
                what = op.get("what")
                if what == "all":
                    self.data = d = copy.deepcopy(DEFAULT)
                elif what in ("tasks", "achievements", "pinned"):
                    d[what] = []
                elif what in ("hideout", "owned", "objectives"):
                    d[what] = {}
                elif what == "story":
                    d["story"] = {"steps": [], "notes": {}}
                elif what in ("accepted", "failed"):
                    d[what] = []
                elif what == "traders":
                    d["traders"] = {}
                else:
                    raise ProgressError("nothing to reset")
            elif kind == "import":
                self.data = _clean(op.get("data"))
            else:
                raise ProgressError(f"unknown change {kind!r}")
            self._save()
            return copy.deepcopy(self.data)
