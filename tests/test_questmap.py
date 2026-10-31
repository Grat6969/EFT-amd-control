"""Quest markers on tarkov.dev's map pictures (questmap.py)."""

import math
import os
import time

import pytest

from tarkov_display import questmap
from tarkov_display.questmap import Drawings, Picture, build, floor_name, prepare_svg, project, quest_entry, quest_markers, rotate, svg_picture, tile_layout

# tarkov.dev's real numbers for Customs (maps.json).
CUSTOMS = quest_entry({
    "key": "customs", "transform": [0.239, 168.65, 0.239, 136.35], "coordinateRotation": 180,
    "bounds": [[698, -307], [-372, 237]], "svgPath": "https://assets.tarkov.dev/maps/svg/Customs.svg", "svgLayer": "Ground_Level",
    "tilePath": "https://assets.tarkov.dev/maps/customs/main/{z}/{x}/{y}.png", "tileSize": 256, "minZoom": 2, "maxZoom": 6,
    "layers": [{"name": "2nd Floor", "extents": [{"height": [2.7, 6.5], "bounds": [[[243, 190], [165, 125], "dorms"]]}]},
               {"name": "3rd Floor", "extents": [{"height": [5.7, 1000], "bounds": [[[243, 190], [165, 125], "dorms"]]}]},
               {"name": "Underground", "extents": [{"height": [-1000, 0.5], "bounds": [[[635, -137], [620, -125], "zb-1011"]]}]}],
})
CUSTOMS_VIEW = (1062.4827, 535.17401)  # Customs.svg's viewBox


def close(a, b, tol=1e-6):
    return all(math.isclose(x, y, abs_tol=tol) for x, y in zip(a, b))


# -- where a game position lands ----------------------------------------------------------

def test_rotation_is_exact_for_quarter_turns():
    assert rotate(3, 4, 0) == (3, 4)
    assert rotate(3, 4, 90) == (-4, 3)
    assert rotate(3, 4, 180) == (-3, -4)
    assert rotate(3, 4, 270) == (4, -3)
    assert close(rotate(1, 0, 45), (math.sqrt(0.5), math.sqrt(0.5)))


def test_projection_follows_tarkov_devs_leaflet_setup():
    # getCRS: Transformation(t0, t1, -t2, t3) after the rotation; LatLng(lat=z, lng=x).
    assert close(project(CUSTOMS, 200, 150), (0.239 * -200 + 168.65, -0.239 * -150 + 136.35))


def test_drawing_corners_and_centring():
    # A drawing exactly the shape of its bounds fills them corner to corner:
    # north-west of the game (west = smallest x, north = largest z) lands
    # where Leaflet puts it after the turn, here bottom right.
    entry = dict(CUSTOMS)
    minx, miny, maxx, maxy = questmap.box(entry, entry["bounds"])
    same = svg_picture(entry, maxx - minx, maxy - miny)
    assert close(same.fraction(entry, -372, 237), (1, 1)) and close(same.fraction(entry, 698, -307), (0, 0))
    # Customs.svg is a little wider for its height than its bounds: the
    # drawing is fitted by width and centred top to bottom, as an SVG is.
    pic = svg_picture(entry, *CUSTOMS_VIEW)
    fx, fy = pic.fraction(entry, 698, -307)
    assert math.isclose(fx, 0, abs_tol=1e-9) and -0.01 < fy < 0
    _, fy2 = pic.fraction(entry, -372, 237)
    assert math.isclose(fy + fy2, 1, abs_tol=1e-9)  # the same margin above and below


def test_landmarks_land_on_their_buildings():
    # tarkov.dev's own labels for Customs (maps.json), placed on Customs.svg:
    # checked by eye on the rendered drawing, each sits on its building.
    pic = svg_picture(CUSTOMS, *CUSTOMS_VIEW)
    for (x, z), (fx, fy) in [((200, 150), (0.4654, 0.8433)),    # Dorms
                             ((-215, -119), (0.8533, 0.3441)),  # Big Red
                             ((404, 31), (0.2748, 0.6225))]:    # New Gas
        got = pic.fraction(CUSTOMS, x, z)
        assert close(got, (fx, fy), tol=0.001), (x, z, got)


def test_floors():
    assert floor_name(CUSTOMS, 200, 4.0, 150) == "2nd Floor"     # in the dorms, 2nd floor height
    assert floor_name(CUSTOMS, 200, 8.0, 150) == "3rd Floor"
    assert floor_name(CUSTOMS, 200, 6.0, 150) == "3rd Floor"     # both ranges: the floor that starts higher
    assert floor_name(CUSTOMS, 0, 4.0, 0) is None                # same height elsewhere: not a building with floors
    assert floor_name(CUSTOMS, 630, -3.0, -130) == "Underground"
    assert floor_name(CUSTOMS, 200, 1.0, 150) is None            # ground floor


def test_tile_layout_matches_leaflet():
    lab = quest_entry({"key": "the-lab", "transform": [0.575, 281.2, 0.575, 193.7], "coordinateRotation": 270,
                       "bounds": [[-80, -477], [-287, -193]], "tilePath": "https://assets.tarkov.dev/maps/labs_v4/1st/{z}/{x}/{y}.png",
                       "tileSize": 175, "minZoom": 2, "maxZoom": 6})
    layout = tile_layout(lab)
    assert (layout["zoom"], layout["x0"], layout["y0"], layout["columns"], layout["rows"]) == (4, 0, 2, 16, 12)
    pic = layout["picture"]
    # A spot's place in the mosaic is its Leaflet pixel at that zoom, less the first tile's.
    px, py = project(lab, -150, -340)
    fx, fy = pic.fraction(lab, -150, -340)
    assert close((fx * layout["width"], fy * layout["height"]), (px * 16 - 0, py * 16 - 2 * 175))
    small = tile_layout(lab, target=100000)  # asked for more tiles than allowed: a smaller zoom
    assert small["columns"] * small["rows"] <= questmap.MAX_TILES or small["zoom"] == 2
    # Bounds reaching past tile 0 (Icebreaker's): no tiles with negative numbers.
    ice = quest_entry({"key": "icebreaker", "transform": [2.0, 125.0, 3.5, 91.0], "coordinateRotation": 180,
                       "bounds": [[77, -64.5], [-65.5, 67.4]], "tilePath": "https://assets.tarkov.dev/maps/icebreaker/06/{z}/{x}/{y}.png",
                       "minZoom": 1, "maxZoom": 5})
    layout = tile_layout(ice)
    assert layout["x0"] >= 0 and layout["y0"] >= 0 and layout["columns"] >= 1 and layout["rows"] >= 1


def test_quest_entry_checks_what_it_keeps():
    assert quest_entry({"key": "x", "transform": [1, 0, 1, 0], "bounds": [[0, 0], [1, 1]]}) is None  # nothing to draw on
    assert quest_entry({"key": "x", "transform": [0, 0, 1, 0], "bounds": [[0, 0], [1, 1]], "svgPath": questmap.SVG_PREFIX + "a.svg"}) is None
    assert quest_entry({"key": "x", "transform": [1, 0, 1], "bounds": [[0, 0], [1, 1]], "svgPath": questmap.SVG_PREFIX + "a.svg"}) is None
    assert quest_entry({"key": "x", "transform": [1, 0, 1, 0], "bounds": [[0, 0]], "svgPath": questmap.SVG_PREFIX + "a.svg"}) is None
    # Only tarkov.dev's own files.
    assert quest_entry({"key": "x", "transform": [1, 0, 1, 0], "bounds": [[0, 0], [1, 1]], "svgPath": "https://evil.example/a.svg"}) is None
    assert quest_entry({"key": "x", "transform": [1, 0, 1, 0], "bounds": [[0, 0], [1, 1]], "tilePath": "https://evil.example/{z}/{x}/{y}"}) is None
    e = quest_entry({"key": "x", "transform": [1, 0, 1, 0], "bounds": [[0, 0], [1, 1]], "svgPath": questmap.SVG_PREFIX + "a.svg",
                     "layers": [{"name": "Up", "extents": [{"height": [1, 2], "bounds": [[[0, 0], [1, 1], "a"], "junk"]}, {"height": "x"}]}, "junk"]})
    assert e["svg"] == questmap.SVG_PREFIX + "a.svg" and e["layers"] == [{"name": "Up", "extents": [{"height": [1, 2], "bounds": [[[0, 0], [1, 1]]]}]}]


def test_alternate_maps_use_their_main_maps_drawing():
    images = {"factory": {"quest": {"key": "factory", "altMaps": ["night-factory"]}}, "woods": {"images": []}}
    assert questmap.entry_for(images, "night-factory")["key"] == "factory"
    assert questmap.entry_for(images, "factory")["key"] == "factory"
    assert questmap.entry_for(images, "woods") is None and questmap.entry_for(None, "x") is None


# -- quest markers ---------------------------------------------------------------------------

def objective(oid, desc, zones=(), locations=(), item=None, optional=False):
    o = {"id": oid, "type": "visit", "description": desc, "optional": optional, "zones": list(zones), "possibleLocations": list(locations)}
    if item:
        o["questItem"] = {"id": "qi", "name": item}
    return o


def zone(zid, map_id, x, y, z, outline=True):
    out = {"id": zid, "map": {"id": map_id}, "position": {"x": x, "y": y, "z": z}}
    if outline:
        out["outline"] = [{"x": x - 2, "y": y, "z": z - 2}, {"x": x + 2, "y": y, "z": z - 2}, {"x": x + 2, "y": y, "z": z + 2}]
    return out


def test_quest_markers():
    pic = svg_picture(CUSTOMS, *CUSTOMS_VIEW)
    tasks = [
        {"id": "t2", "name": "Zeta", "trader": {"name": "Prapor"}, "objectives": [
            objective("o1", "Visit the dorms", [zone("z1", "customs-id", 200, 4, 150)]),
            objective("o2", "Mark the dorms", [zone("z2", "customs-id", 200, 4, 150)]),     # the same spot: one marker
            objective("o3", "Somewhere else", [zone("z3", "woods-id", 0, 0, 0)]),         # another map
            objective("o4", "Find the folder", locations=[{"map": {"id": "customs-id"}, "positions": [
                {"x": 404, "y": 1, "z": 31}, {"x": 5000, "y": 0, "z": 0}, {"x": "bad"}]}], item="Folder", optional=True)]},
        {"id": "t1", "name": "alpha", "objectives": [objective("o5", "Go", [zone("z5", "customs-id", 0, 0, 0, outline=False)])]},
        {"id": "t3", "name": "Nothing here", "objectives": [objective("o6", "Elsewhere", [zone("z6", "woods-id", 1, 1, 1)])]},
        "junk", {"name": "no id"},
    ]
    quests, outside = quest_markers(tasks, "customs-id", CUSTOMS, pic)
    assert [q["name"] for q in quests] == ["alpha", "Zeta"] and outside == 1  # sorted; 5000 is off the map
    zeta = quests[1]
    assert zeta["trader"] == "Prapor" and len(zeta["markers"]) == 2
    dorms, folder = zeta["markers"]
    assert dorms["kind"] == "zone" and dorms["objectives"] == ["o1", "o2"] and dorms["floor"] == "2nd Floor"
    assert close((dorms["x"], dorms["y"]), pic.fraction(CUSTOMS, 200, 150), tol=1e-5)
    assert len(dorms["outline"]) == 3 and all(0 < c < 1 for p in dorms["outline"] for c in p)
    assert folder["kind"] == "item" and folder["item"] == "Folder" and folder["optional"] and folder["floor"] is None
    assert "outline" not in quests[0]["markers"][0]


# -- the drawings ----------------------------------------------------------------------------

SVG = b'''<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 200 100">
<style>.a{fill:red}</style>
<g id="Ground_Level" onload="alert(1)"><rect class="a" width="10" height="10" onclick="x()"/>
  <a href="javascript:alert(1)"><rect width="1" height="1"/></a>
  <use xlink:href="https://evil.example/x.svg#a"/><use href="#local"/>
  <foreignObject><div>hi</div></foreignObject><image href="https://evil.example/p.png"/>
  <script>alert(1)</script><animate attributeName="href" to="javascript:alert(1)"/></g>
<g id="First_Floor" data-keep-with-group="Ground_Level"><rect width="2" height="2"/></g>
<g id="Second_Floor"><rect width="3" height="3"/></g>
</svg>'''


def test_prepare_svg_shows_one_floor_and_nothing_that_runs():
    out, view = prepare_svg(SVG, "Ground_Level", size=1000)
    text = out.decode()
    assert view == (200.0, 100.0)
    assert 'width="1000"' in text and 'height="500"' in text and 'preserveAspectRatio="none"' in text
    assert "Ground_Level" in text and "First_Floor" in text and "Second_Floor" not in text
    for bad in ("script", "onload", "onclick", "javascript", "evil.example", "foreignObject", "<image", "animate"):
        assert bad not in text, bad
    assert 'href="#local"' in text
    # No such floor: everything is kept rather than nothing.
    assert b"Second_Floor" in prepare_svg(SVG, "Nope")[0]


@pytest.mark.parametrize("raw", [
    b"<html/>", b'<svg xmlns="http://www.w3.org/2000/svg"/>',
    b'<!DOCTYPE svg [<!ENTITY a "aaaa">]><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1">&a;</svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 0 10"/>', b"not xml",
])
def test_prepare_svg_refuses_odd_files(raw):
    with pytest.raises(Exception):
        prepare_svg(raw, None)


def test_prepare_svg_size_from_width_and_height():
    _out, view = prepare_svg(b'<svg xmlns="http://www.w3.org/2000/svg" width="300px" height="150"/>', None)
    assert view == (300.0, 150.0)


def test_drawings_are_downloaded_once_and_kept(tmp_path):
    url = questmap.SVG_PREFIX + "Customs.svg"
    calls = []

    def fetch(u):
        calls.append(u)
        return SVG

    d = Drawings(tmp_path, fetch)
    svg, view = d.get(url, "Ground_Level")
    assert view == (200.0, 100.0) and b"Second_Floor" not in svg
    d.get(url, "Ground_Level")
    assert calls == [url]
    # Next start: from disk.
    assert Drawings(tmp_path, lambda u: 1 / 0).get(url, "Ground_Level")[1] == view
    # Old copy, tarkov.dev down: the old copy.
    for f in tmp_path.glob("mapsvg_*.svg"):
        os.utime(f, (time.time() - questmap.SVG_TTL - 10,) * 2)
    assert Drawings(tmp_path, lambda u: 1 / 0).get(url, "Ground_Level")[1] == view
    # Only tarkov.dev's drawings.
    with pytest.raises(ValueError):
        d.get("https://evil.example/x.svg", None)
    with pytest.raises(ZeroDivisionError):
        Drawings(None, lambda u: 1 / 0).get(url, None)


def test_build():
    maps = [{"id": "customs-id", "name": "Customs", "normalizedName": "customs"}, {"id": "w", "name": "Woods", "normalizedName": "woods"}]
    tasks = [{"id": "t", "name": "Q", "objectives": [objective("o", "Go", [zone("z", "customs-id", 200, 1, 150)])]}]
    images = {"customs": {"quest": CUSTOMS}}

    class Fake:
        def __init__(self, fail=False):
            self.fail = fail

        def get(self, url, layer):
            if self.fail:
                raise RuntimeError("offline")
            return b"<svg/>", CUSTOMS_VIEW

    out = build(maps, tasks, images, "customs", Fake())
    assert out["map"]["name"] == "Customs" and out["picture"]["kind"] == "svg" and out["picture"]["width"] == questmap.PICTURE_SIZE
    assert out["picture"]["height"] == round(CUSTOMS_VIEW[1] * questmap.PICTURE_SIZE / CUSTOMS_VIEW[0])
    assert [q["name"] for q in out["quests"]] == ["Q"] and "error" not in out
    # The drawing can't be had: the satellite tiles instead.
    tiles = build(maps, tasks, images, "customs", Fake(fail=True))
    assert tiles["picture"]["kind"] == "tiles" and tiles["quests"] and "error" not in tiles
    no_tiles = build(maps, tasks, {"customs": {"quest": {k: v for k, v in CUSTOMS.items() if k != "tiles"}}}, "customs", Fake(fail=True))
    assert no_tiles["picture"] is None and no_tiles["error"] == "offline"
    assert build(maps, tasks, images, "woods", Fake())["picture"] is None  # no interactive map for it
    with pytest.raises(KeyError):
        build(maps, tasks, images, "nowhere", Fake())


def test_picture_fraction_is_linear():
    p = Picture(10, 20, 100, 50)
    entry = {"transform": [1, 0, 1, 0], "rotation": 0}
    assert p.fraction(entry, 60, -45) == (0.5, 0.5)  # y grows down: z = -45 is 45 px down
