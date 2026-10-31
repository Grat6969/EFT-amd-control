"""Quest markers on tarkov.dev's map pictures.

tarkov.dev's interactive maps put things at their in-game position. For each
map, their maps.json says how a game position (x and z; y is height) lands on
the map: a rotation, then Leaflet's scale-and-offset ("transform"), and the
rectangle of game coordinates their SVG drawing covers ("svgBounds", else
"bounds"). This module does the same arithmetic as their website
(src/pages/map/index.jsx: getCRS, applyRotation, getBounds, and Leaflet's
SVGOverlay, which centres the drawing in that rectangle when their shapes
differ) and gives every position as a fraction of the picture's width and
height, the way the app's own map markers are kept.

The pictures are tarkov.dev's SVG drawings, showing the ground floor as their
site does by default, or for maps that only have satellite-style tiles, a
mosaic of tiles. The 2D and 3D map images made by players don't come with
game coordinates, so quest markers can't be placed on those.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

log = logging.getLogger(__name__)

SVG_NS = "http://www.w3.org/2000/svg"
# Only tarkov.dev's own map files are ever downloaded or shown.
SVG_PREFIX = "https://assets.tarkov.dev/maps/svg/"
TILE_PREFIX = "https://assets.tarkov.dev/maps/"
PICTURE_SIZE = 3000      # pixels along the longer side of a drawing
MOSAIC_SIZE = 1800       # a tile mosaic is at least this wide or tall, if the tiles allow
MAX_TILES = 256
SVG_MAX_BYTES = 8 * 1024 * 1024
SVG_TTL = 3 * 24 * 3600
LICENSE = {"name": "CC BY-NC-SA 4.0", "link": "https://github.com/the-hideout/tarkov-dev-svg-maps"}
KEY = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# Anything that could run code or load something from elsewhere.
UNSAFE_TAGS = {"script", "foreignobject", "iframe", "object", "embed", "image", "audio", "video", "animate", "set",
               "animatemotion", "animatetransform", "discard", "handler", "listener"}

ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")


# -- where a game position lands ---------------------------------------------------------

_EXACT = {0: (1.0, 0.0), 90: (0.0, 1.0), 180: (-1.0, 0.0), 270: (0.0, -1.0)}


def rotate(x: float, z: float, degrees) -> Tuple[float, float]:
    """tarkov.dev's applyRotation: Leaflet's LatLng(lat=z, lng=x) turned about
    the origin; gives (lng, lat)."""
    d = float(degrees or 0) % 360
    cos, sin = _EXACT.get(d) or (math.cos(math.radians(d)), math.sin(math.radians(d)))  # type: ignore[arg-type]
    return x * cos - z * sin, x * sin + z * cos


def project(entry: dict, x: float, z: float) -> Tuple[float, float]:
    """A game position in the map's Leaflet pixels at zoom 0 (y grows down)."""
    rx, ry = rotate(x, z, entry.get("rotation"))
    t = entry.get("transform") or (1, 0, 1, 0)
    return t[0] * rx + t[1], -t[2] * ry + t[3]


def _rect(bounds) -> Tuple[float, float, float, float]:
    """west, south, east, north of a maps.json bounds ([[x, z], [x, z]])."""
    (x0, z0), (x1, z1) = bounds
    return min(x0, x1), min(z0, z1), max(x0, x1), max(z0, z1)


def box(entry: dict, bounds) -> Tuple[float, float, float, float]:
    """The pixel rectangle Leaflet stretches an overlay over: from its
    north-west corner to its south-east one, projected."""
    west, south, east, north = _rect(bounds)
    ax, ay = project(entry, west, north)
    bx, by = project(entry, east, south)
    return min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)


def in_bounds(entry: dict, x: float, z: float) -> bool:
    """Inside the map (tarkov.dev leaves out quest positions that aren't)."""
    if not entry.get("bounds"):
        return True
    west, south, east, north = _rect(entry["bounds"])
    return west <= x <= east and south <= z <= north


@dataclass(frozen=True)
class Picture:
    """A map picture's place in Leaflet pixels at zoom 0."""
    x0: float
    y0: float
    width: float
    height: float

    def fraction(self, entry: dict, x: float, z: float) -> Tuple[float, float]:
        px, py = project(entry, x, z)
        return (px - self.x0) / self.width, (py - self.y0) / self.height


def svg_picture(entry: dict, view_width: float, view_height: float) -> Picture:
    """Where tarkov.dev's drawing sits: its viewBox fitted, centred, into the
    rectangle of its bounds (an SVG's default preserveAspectRatio)."""
    minx, miny, maxx, maxy = box(entry, entry.get("svgBounds") or entry["bounds"])
    bw, bh = maxx - minx, maxy - miny
    scale = min(bw / view_width, bh / view_height)
    dw, dh = view_width * scale, view_height * scale
    return Picture(minx + (bw - dw) / 2, miny + (bh - dh) / 2, dw, dh)


def tile_layout(entry: dict, target: float = MOSAIC_SIZE) -> dict:
    """The tiles covering the map at one zoom level, as Leaflet would load them."""
    tiles = entry["tiles"]
    size = tiles.get("size") or 256
    minx, miny, maxx, maxy = box(entry, entry["bounds"])
    longest = max(maxx - minx, maxy - miny)
    low, high = int(tiles.get("minZoom") or 0), int(tiles.get("maxZoom") or 6)
    zoom = max(low, min(high, math.ceil(math.log2(target / longest)) if longest > 0 else low))
    while True:
        k = 2 ** zoom
        i0, j0 = math.floor(minx * k / size), math.floor(miny * k / size)
        i1, j1 = math.ceil(maxx * k / size) - 1, math.ceil(maxy * k / size) - 1
        if (i1 - i0 + 1) * (j1 - j0 + 1) <= MAX_TILES or zoom <= low:
            break
        zoom -= 1
    picture = Picture(i0 * size / k, j0 * size / k, (i1 - i0 + 1) * size / k, (j1 - j0 + 1) * size / k)
    return {"zoom": zoom, "size": size, "x0": i0, "y0": j0, "columns": i1 - i0 + 1, "rows": j1 - j0 + 1,
            "width": (i1 - i0 + 1) * size, "height": (j1 - j0 + 1) * size, "url": tiles["url"], "picture": picture}


def _contains(bounds, x: float, z: float) -> bool:
    west, south, east, north = _rect(bounds[:2])
    return west <= x <= east and south <= z <= north


def floor_name(entry: dict, x: float, y: float, z: float) -> Optional[str]:
    """Which of the map's other floors a spot is on (tarkov.dev's layers:
    a height range, and sometimes only within some buildings). None for the
    ground floor the picture shows."""
    best, best_low = None, None
    for layer in entry.get("layers") or []:
        for extent in layer.get("extents") or []:
            low, high = extent.get("height") or (None, None)
            if low is None or not low <= y < high:
                continue
            if extent.get("bounds") and not any(_contains(b, x, z) for b in extent["bounds"]):
                continue
            if best_low is None or low > best_low:  # overlapping ranges: the floor that starts highest
                best, best_low = layer.get("name"), low
    return best


# -- the drawings ---------------------------------------------------------------------------

def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _number(text) -> Optional[float]:
    m = re.match(r"\s*([0-9.]+)", text or "")
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def _sanitize(element) -> None:
    for child in list(element):
        if not isinstance(child.tag, str) or _local(child.tag).lower() in UNSAFE_TAGS:
            element.remove(child)
        else:
            _sanitize(child)
    for name in list(element.attrib):
        value = element.attrib[name]
        local = _local(name).lower()
        if local.startswith("on") or "javascript:" in value.lower().replace(" ", ""):
            del element.attrib[name]
        elif local == "href" and not value.strip().startswith("#"):
            del element.attrib[name]


def prepare_svg(raw: bytes, layer: Optional[str], size: int = PICTURE_SIZE) -> Tuple[bytes, Tuple[float, float]]:
    """tarkov.dev's drawing as the app shows it: only the given floor (their
    layer groups are the top-level <g> elements with an id), nothing that runs
    or loads anything, and a pixel size for the picture. Gives the SVG and the
    drawing's own (viewBox) width and height."""
    text = raw.decode("utf-8-sig")
    if "<!ENTITY" in text:
        raise ValueError("unexpected entity declarations in the map drawing")
    root = ET.fromstring(text)
    if root.tag != f"{{{SVG_NS}}}svg":
        raise ValueError("the map drawing isn't an SVG")
    view = [float(v) for v in re.split(r"[\s,]+", (root.get("viewBox") or "").strip()) if v]
    if len(view) != 4:
        width, height = _number(root.get("width")), _number(root.get("height"))
        if not width or not height:
            raise ValueError("the map drawing has no size")
        view = [0.0, 0.0, width, height]
        root.set("viewBox", f"0 0 {width:g} {height:g}")
    if view[2] <= 0 or view[3] <= 0:
        raise ValueError("the map drawing has no size")
    groups = [c for c in root if _local(c.tag) == "g" and c.get("id")]
    if layer and any(g.get("id") == layer for g in groups):
        for g in groups:
            if g.get("id") != layer and g.get("data-keep-with-group") != layer:
                root.remove(g)
    _sanitize(root)
    scale = size / max(view[2], view[3])
    root.set("width", str(max(1, round(view[2] * scale))))
    root.set("height", str(max(1, round(view[3] * scale))))
    root.set("preserveAspectRatio", "none")  # fill the picture exactly, so fractions of it are fractions of the drawing
    return ET.tostring(root, encoding="utf-8"), (view[2], view[3])


class Drawings:
    """tarkov.dev's map drawings, downloaded when first needed and kept on disk."""

    def __init__(self, cache_dir: Optional[Path], fetch) -> None:
        self.cache_dir = cache_dir
        self.fetch = fetch  # url -> bytes
        self._lock = threading.Lock()
        self._memory: Dict[Tuple[str, Optional[str]], Tuple[float, bytes, Tuple[float, float]]] = {}

    def _path(self, url: str) -> Optional[Path]:
        if not self.cache_dir:
            return None
        return self.cache_dir / f"mapsvg_{hashlib.sha1(url.encode()).hexdigest()[:16]}.svg"

    def _raw(self, url: str) -> bytes:
        path = self._path(url)
        cached = None
        if path and path.exists():
            cached = path.read_bytes()
            if time.time() - path.stat().st_mtime < SVG_TTL:
                return cached
        try:
            raw = self.fetch(url)
            if len(raw) > SVG_MAX_BYTES:
                raise ValueError("the map drawing is too large")
        except Exception:
            if cached is not None:  # an old copy beats none
                log.warning("Couldn't update the map drawing %s; using the saved one", url, exc_info=True)
                return cached
            raise
        if path:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp")
                tmp.write_bytes(raw)
                os.replace(tmp, path)
            except OSError as exc:
                log.debug("Couldn't save the map drawing: %s", exc)
        return raw

    def get(self, url: str, layer: Optional[str]) -> Tuple[bytes, Tuple[float, float]]:
        if not url.startswith(SVG_PREFIX) or ".." in url:
            raise ValueError("not one of tarkov.dev's map drawings")
        with self._lock:
            hit = self._memory.get((url, layer))
            if hit and time.time() - hit[0] < SVG_TTL:
                return hit[1], hit[2]
            svg, view = prepare_svg(self._raw(url), layer)
            self._memory[(url, layer)] = (time.time(), svg, view)
            return svg, view


# -- maps.json -------------------------------------------------------------------------------

def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _bounds(value):
    if (isinstance(value, list) and len(value) >= 2 and all(isinstance(p, list) and len(p) >= 2 for p in value[:2])
            and all(_finite(v) for p in value[:2] for v in p[:2])):
        return [[float(value[0][0]), float(value[0][1])], [float(value[1][0]), float(value[1][1])]]
    return None


def quest_entry(variant: dict) -> Optional[dict]:
    """What the app keeps of an interactive map in tarkov.dev's maps.json:
    how to place game positions on it, and its drawing or tiles."""
    transform = variant.get("transform")
    bounds = _bounds(variant.get("bounds"))
    if not (isinstance(transform, list) and len(transform) == 4 and all(_finite(v) for v in transform)) or not bounds:
        return None
    if not transform[0] or not transform[2]:
        return None
    entry = {
        "key": variant.get("key"), "transform": [float(v) for v in transform], "bounds": bounds,
        "rotation": variant.get("coordinateRotation") if _finite(variant.get("coordinateRotation")) else 0,
        "author": variant.get("author"), "authorLink": variant.get("authorLink"),
        "altMaps": [m for m in variant.get("altMaps") or [] if isinstance(m, str)],
        "layers": [],
    }
    svg = variant.get("svgPath")
    if isinstance(svg, str) and svg.startswith(SVG_PREFIX):
        entry.update(svg=svg, svgLayer=variant.get("svgLayer") if isinstance(variant.get("svgLayer"), str) else None,
                     svgBounds=_bounds(variant.get("svgBounds")))
    tiles = variant.get("tilePath")
    if isinstance(tiles, str) and tiles.startswith(TILE_PREFIX) and all(p in tiles for p in ("{z}", "{x}", "{y}")):
        entry["tiles"] = {"url": tiles, "size": variant.get("tileSize") if _finite(variant.get("tileSize")) else 256,
                          "minZoom": variant.get("minZoom") if _finite(variant.get("minZoom")) else 0,
                          "maxZoom": variant.get("maxZoom") if _finite(variant.get("maxZoom")) else 6}
    if "svg" not in entry and "tiles" not in entry:
        return None
    for layer in variant.get("layers") or []:
        if not isinstance(layer, dict) or not isinstance(layer.get("name"), str):
            continue
        extents = []
        for ext in layer.get("extents") or []:
            height = ext.get("height") if isinstance(ext, dict) else None
            if not (isinstance(height, list) and len(height) == 2 and all(_finite(v) for v in height)):
                continue
            areas = [b for b in (_bounds(raw) for raw in ext.get("bounds") or []) if b]
            extents.append({"height": [float(height[0]), float(height[1])], **({"bounds": areas} if areas else {})})
        if extents:
            entry["layers"].append({"name": layer["name"], "extents": extents})
    return entry


def entry_for(mapimages: Optional[dict], normalized_name: str) -> Optional[dict]:
    """The interactive map tarkov.dev shows for one of the game's maps (Night
    Factory is drawn on Factory's map, Ground Zero 21+ on Ground Zero's)."""
    groups = mapimages or {}
    group = groups.get(normalized_name)
    if group and group.get("quest"):
        return group["quest"]
    for g in groups.values():
        entry = (g or {}).get("quest")
        if entry and normalized_name in entry.get("altMaps", []):
            return entry
    return None


# -- quest markers ---------------------------------------------------------------------------

def _xyz(value) -> Optional[Tuple[float, float, float]]:
    if not isinstance(value, dict):
        return None
    x, y, z = value.get("x"), value.get("y", 0), value.get("z")
    if not (_finite(x) and _finite(z)):
        return None
    return float(x), float(y) if _finite(y) else 0.0, float(z)


def _map_of(value) -> Optional[str]:
    m = value.get("map") if isinstance(value, dict) else None
    return m.get("id") if isinstance(m, dict) else m if isinstance(m, str) else None


def _round(v: float) -> float:
    return round(v, 5)


def quest_markers(tasks: Optional[Iterable[dict]], map_id: str, entry: dict, picture: Picture) -> Tuple[List[dict], int]:
    """Every quest's objective zones and quest item spots on one map, as
    fractions of the picture, like tarkov.dev's map shows them. Also gives how
    many positions were left out for being outside the map."""
    quests, outside = [], 0
    for task in tasks or []:
        if not isinstance(task, dict) or not task.get("id"):
            continue
        markers: List[dict] = []
        seen: Dict[tuple, dict] = {}

        def add(kind, pos, objective, extra):
            nonlocal outside
            x, y, z = pos
            if not in_bounds(entry, x, z):
                outside += 1
                return
            fx, fy = picture.fraction(entry, x, z)
            key = (kind, round(fx, 4), round(fy, 4))
            if key in seen:  # several objectives at one spot: one marker
                if objective["id"] not in seen[key]["objectives"]:
                    seen[key]["objectives"].append(objective["id"])
                return
            mk = {"kind": kind, "x": _round(fx), "y": _round(fy), "objectives": [objective["id"]],
                  "text": objective.get("description") or "", "optional": bool(objective.get("optional")),
                  "floor": floor_name(entry, x, y, z), **extra}
            seen[key] = mk
            markers.append(mk)

        for o in task.get("objectives") or []:
            if not isinstance(o, dict) or not o.get("id"):
                continue
            for zone in o.get("zones") or []:
                if _map_of(zone) != map_id:
                    continue
                pos = _xyz(zone.get("position"))
                if pos is None:
                    continue
                outline = [p for p in (_xyz(v) for v in zone.get("outline") or []) if p]
                extra = {}
                if len(outline) >= 3:
                    extra["outline"] = [[_round(c) for c in picture.fraction(entry, p[0], p[2])] for p in outline]
                add("zone", pos, o, extra)
            item = o.get("questItem") if isinstance(o.get("questItem"), dict) else {}
            for loc in o.get("possibleLocations") or []:
                if _map_of(loc) != map_id:
                    continue
                for p in loc.get("positions") or []:
                    pos = _xyz(p)
                    if pos is not None:
                        add("item", pos, o, {"item": item.get("name")} if item.get("name") else {})
        if markers:
            trader = task.get("trader") if isinstance(task.get("trader"), dict) else {}
            quests.append({"id": task["id"], "name": task.get("name") or "", "trader": trader.get("name"),
                           "markers": markers})
    quests.sort(key=lambda q: q["name"].lower())
    return quests, outside


def build(maps: Optional[list], tasks: Optional[list], mapimages: Optional[dict], normalized_name: str,
          drawings: Optional[Drawings]) -> dict:
    """Everything the map page needs to draw quest markers on one map."""
    game_map = next((m for m in maps or [] if isinstance(m, dict) and m.get("normalizedName") == normalized_name), None)
    if not game_map:
        raise KeyError(f"no map called {normalized_name}")
    entry = entry_for(mapimages, normalized_name)
    out = {"map": {k: game_map.get(k) for k in ("id", "name", "normalizedName")}, "picture": None, "quests": [], "outside": 0}
    if not entry:
        return out
    picture_info = {"key": entry["key"], "author": entry.get("author"), "authorLink": entry.get("authorLink")}
    view = None
    if entry.get("svg") and drawings is not None:
        try:
            _svg, view = drawings.get(entry["svg"], entry.get("svgLayer"))
        except Exception as exc:  # tiles if there are any, else say why
            log.warning("Couldn't get tarkov.dev's drawing of %s: %s", normalized_name, exc)
            out["error"] = str(exc)
    if view:
        vw, vh = view
        picture = svg_picture(entry, vw, vh)
        scale = PICTURE_SIZE / max(vw, vh)
        picture_info.update(kind="svg", width=max(1, round(vw * scale)), height=max(1, round(vh * scale)), license=LICENSE)
    elif entry.get("tiles"):
        layout = tile_layout(entry)
        picture = layout.pop("picture")
        picture_info.update(kind="tiles", tiles=layout, width=layout["width"], height=layout["height"])
    else:
        return out
    out.pop("error", None)
    out["picture"] = picture_info
    out["quests"], out["outside"] = quest_markers(tasks, game_map.get("id"), entry, picture)
    return out


def drawing_key_ok(key: str) -> bool:
    return bool(KEY.match(key or ""))


def find_drawing(mapimages: Optional[dict], key: str) -> Optional[dict]:
    """The interactive map entry whose drawing is called ``key``."""
    for g in (mapimages or {}).values():
        entry = (g or {}).get("quest")
        if entry and entry.get("key") == key and entry.get("svg"):
            return entry
    return None


def dumps(value) -> str:
    return json.dumps(value, separators=(",", ":"))
