"""Keys: what's near each locked door, and reading keys off a screenshot.

tarkov.dev's map data places every locked door, loot container and loose
loot spawn on each map, but doesn't say which room a container is in. So
"behind the door" is estimated: the containers and loose loot within a few
metres of the door, on the same floor. That can take in a corridor or the
room next door too; the Keys page says so.

Reading keys from a screenshot: the window cuts the picture into pieces,
enlarges them (key labels are small) and sends each here as grey pixels;
OCR reads the labels, and they're matched to keys' short names (the label
printed on each key) or full names, the way the price check reads text.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

NEAR = 9.0        # metres from the door, along the ground...
SAME_FLOOR = 2.5  # ... and this far up or down
KEEP_LOOSE = 5    # most valuable loose loot kept per key

# Rough worth of a container, in points (a safe is worth a lot more than a
# jacket). Matched on words in the container's name, first match wins.
CONTAINER_POINTS: Tuple[Tuple[str, int], ...] = (
    ("bank safe", 40), ("safe", 35), ("shturman", 30), ("plastic suitcase", 18), ("weapon box", 15),
    ("weapon crate", 15), ("pc block", 14), ("technical supply", 14), ("medical supply", 14), ("medcase", 14),
    ("lab technician", 14), ("ground cache", 14), ("buried barrel", 14), ("grenade box", 10), ("toolbox", 10),
    ("cash register", 8), ("wooden crate", 8), ("medbag", 7), ("ration", 7), ("duffle", 7), ("sport bag", 7),
    ("dead scav", 7), ("ammo", 6), ("jacket", 4), ("drawer", 4), ("filing cabinet", 4),
)
OTHER_CONTAINER = 4
LOOSE_CAP = 20          # points for one valuable loose item at most...
LOOSE_ROUBLES = 25000   # ... at a point per this many roubles


def container_points(name: str) -> int:
    low = (name or "").lower()
    for word, points in CONTAINER_POINTS:
        if word in low:
            return points
    return OTHER_CONTAINER


def _pos(p) -> Optional[Tuple[float, float, float]]:
    if not isinstance(p, dict):
        return None
    try:
        x, y, z = float(p["x"]), float(p.get("y") or 0), float(p["z"])
    except (KeyError, TypeError, ValueError):
        return None
    return (x, y, z) if all(math.isfinite(v) for v in (x, y, z)) else None


def _near(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> bool:
    # y is height in tarkov.dev's coordinates.
    return abs(a[1] - b[1]) <= SAME_FLOOR and math.hypot(a[0] - b[0], a[2] - b[2]) <= NEAR


def _ref_id(ref) -> Optional[str]:
    if isinstance(ref, str):
        return ref
    if isinstance(ref, dict):
        return ref.get("id")
    return None


def key_loot(m: dict, container_names: Dict[str, str], item_value: Callable[[str], float],
             item_ref: Callable[[str], dict]) -> Dict[str, dict]:
    """{key id: {"containers": [{name, count}], "loose": [{id, name, ...}], "score"}}
    for every key that opens a door on map ``m`` (a map from tarkov.dev's
    map file: locks, lootContainers and lootLoose with positions).
    ``container_names``: container id -> name; ``item_value``: roubles."""
    containers = []
    for c in m.get("lootContainers") or []:
        if not isinstance(c, dict):
            continue
        ref = c.get("lootContainer")
        name = ref.get("name") if isinstance(ref, dict) and ref.get("name") else container_names.get(_ref_id(ref) or "")
        p = _pos(c.get("position"))
        if name and p:
            containers.append((name, p))
    loose = []
    for spot in m.get("lootLoose") or []:
        if not isinstance(spot, dict):
            continue
        p = _pos(spot.get("position"))
        ids = [i for i in (_ref_id(x) for x in spot.get("items") or []) if i]
        if p and ids:
            loose.append((ids, p))
    doors: Dict[str, List[Tuple[float, float, float]]] = {}
    for lock in m.get("locks") or []:
        if not isinstance(lock, dict):
            continue
        kid, p = _ref_id(lock.get("key")), _pos(lock.get("position"))
        if kid and p:
            doors.setdefault(kid, []).append(p)
    out = {}
    for kid, spots in doors.items():
        # A container near two of the key's doors counts once.
        found = {i for i, (_, p) in enumerate(containers) if any(_near(p, d) for d in spots)}
        counts: Dict[str, int] = {}
        for i in found:
            counts[containers[i][0]] = counts.get(containers[i][0], 0) + 1
        values: Dict[str, float] = {}
        for ids, p in loose:
            if any(_near(p, d) for d in spots):
                for i in ids:
                    if i not in values:
                        values[i] = item_value(i) or 0
        top = sorted((i for i in values if values[i] > 0), key=lambda i: -values[i])[:KEEP_LOOSE]
        score = sum(container_points(name) * n for name, n in counts.items())
        score += sum(min(LOOSE_CAP, values[i] / LOOSE_ROUBLES) for i in top[:3])
        out[kid] = {
            "containers": [{"name": name, "count": n} for name, n in
                           sorted(counts.items(), key=lambda kv: (-container_points(kv[0]), -kv[1], kv[0]))],
            "loose": [dict(item_ref(i), value=int(values[i])) for i in top],
            "score": round(score),
            "doors": len(spots),
        }
    return out


# -- reading keys off a screenshot ---------------------------------------------------------

MATCH = 0.86   # a label must fit a key's short name this well...
FULL = 0.85    # ... or its full name this well
MARGIN = 0.05  # ... and fit it better than any other key by this much


def gray_to_bgra(gray: bytes) -> bytes:
    """Grey pixels (one byte each) as the 32-bit BGRA the OCR engines take."""
    n = len(gray)
    out = bytearray(n * 4)
    out[0::4] = gray
    out[1::4] = gray
    out[2::4] = gray
    out[3::4] = b"\xff" * n
    return bytes(out)


class KeyMatcher:
    """Matches text read off a screenshot to keys."""

    def __init__(self, keys: Sequence) -> None:
        from .reader import ItemIndex  # (reader -> prices -> staticapi -> this module)

        self.keys = {k.id: k for k in keys}
        self.index = ItemIndex(list(keys))

    def _best(self, text: str):
        """(key, how well) for a piece of text, or None when it isn't clearly one key."""
        from .reader import canon

        size = len(canon(text))
        if size < 2:
            return None
        if size == 2:  # two letters (GS): only word for word, and only one key's
            items = self.index.keys("short").get(canon(text)) or []
            return (items[0], 1.0) if len(items) == 1 else None
        for kind, need in (("short", MATCH), ("full", FULL)):
            found = self.index.lookup(text, kind, k=4)
            if not found or found[0][1] < need:
                continue
            best_key, best = found[0]
            items = self.index.keys(kind)[best_key]
            rival = next((s for key, s in found[1:] if self.index.keys(kind)[key] != items), 0.0)
            if len(items) == 1 and best - rival >= MARGIN:
                return items[0], best
        return None

    def match(self, lines: Iterable, origin: Tuple[float, float] = (0, 0), scale: float = 1.0) -> List[dict]:
        """Every key read in OCR ``lines``: [{id, read, score, x, y}], x/y the
        label's centre in screen-shot pixels (``origin`` and ``scale`` map
        the enlarged piece back). A run of words is tried whole first, then
        its parts (OCR runs neighbouring labels together)."""
        from .reader import segments

        out = []
        for seg in segments(lines, origin, scale):
            words = seg.text.split()
            spans = [(0, len(words))] + [(i, j) for n in range(min(4, len(words) - 1), 0, -1)
                                         for i in range(len(words) - n + 1) for j in [i + n]]
            used = [False] * len(words)
            width = (seg.box[2] - seg.box[0]) / max(1, len(seg.text))
            for i, j in spans:
                if any(used[i:j]):
                    continue
                text = " ".join(words[i:j])
                hit = self._best(text)
                if not hit:
                    continue
                for n in range(i, j):
                    used[n] = True
                start = len(" ".join(words[:i])) + (1 if i else 0)
                x0 = seg.box[0] + width * start
                out.append({"id": hit[0].id, "read": text, "score": round(hit[1], 3),
                            "x": round(x0 + width * len(text) / 2), "y": round((seg.box[1] + seg.box[3]) / 2)})
                if (i, j) == (0, len(words)):
                    break
        return out
