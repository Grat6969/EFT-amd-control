"""The Keys page's server side: loot near doors, reading keys off a screenshot."""

from types import SimpleNamespace

import pytest

from tarkov_display import keyrooms
from tarkov_display.ocr import OcrLine
from tarkov_display.progress import Progress, ProgressError

from test_server import body, call


def pos(x, z, y=0.0):
    return {"x": x, "y": y, "z": z}


def test_loot_near_a_door():
    m = {
        "locks": [{"key": "k-safe", "position": pos(0, 0)}, {"key": "k-safe", "position": pos(100, 100)},
                  {"key": "k-empty", "position": pos(50, 0)}, {"key": "k-none"}],
        "lootContainers": [
            {"lootContainer": "c-safe", "position": pos(3, 2)},            # in the room
            {"lootContainer": "c-safe", "position": pos(102, 99)},         # behind the key's other door
            {"lootContainer": "c-jacket", "position": pos(1, 1)},
            {"lootContainer": "c-wb", "position": pos(4, 4, y=6)},         # a floor up: not counted
            {"lootContainer": "c-wb", "position": pos(30, 0)},             # far away
        ],
        "lootLoose": [{"items": ["ledx", "bolts"], "position": pos(2, 0)}, {"items": ["gpu"], "position": pos(80, 80)}],
    }
    names = {"c-safe": "Safe", "c-jacket": "Jacket", "c-wb": "Weapon box"}
    values = {"ledx": 1_000_000, "bolts": 20_000, "gpu": 500_000}
    loot = keyrooms.key_loot(m, names, values.get, lambda i: {"id": i, "shortName": i.upper()})
    safe = loot["k-safe"]
    assert safe["containers"] == [{"name": "Safe", "count": 2}, {"name": "Jacket", "count": 1}]
    assert [i["id"] for i in safe["loose"]] == ["ledx", "bolts"] and safe["loose"][0]["value"] == 1_000_000
    assert safe["doors"] == 2 and safe["score"] == 2 * 35 + 4 + 20 + 1  # LEDX capped at 20 points, bolts ~1
    assert loot["k-empty"] == {"containers": [], "loose": [], "score": 0, "doors": 1}
    assert "k-none" not in loot  # no position: nothing to go on
    assert keyrooms.container_points("Bank safe") == 40 and keyrooms.container_points("Ammo crate") == 6
    assert keyrooms.container_points("Something new") == keyrooms.OTHER_CONTAINER


KEYS = [SimpleNamespace(id=i, name=n, short_name=s, is_preset=False, icon="", tags=["keys"]) for i, n, s in (
    ("k314", "Dorm room 314 marked key", "314"), ("k206", "Dorm room 206 key", "206"), ("k208", "Dorm room 208 key", "208"),
    ("kgs", "Gas station storage room key", "GS"), ("kkiba", "KIBA Arms outer door key", "KIBA"),
    ("kfac", "Factory emergency exit key", "Factory"))]


def line(text, x, y, w=None, h=12):
    w = w or 7 * len(text)
    return OcrLine.of_words([(text, (x, y, x + w, y + h))])


def test_reading_key_labels():
    matcher = keyrooms.KeyMatcher(KEYS)
    found = matcher.match([line("314", 100, 10), line("2O6", 200, 10), line("GS", 300, 10), line("KlBA", 400, 10),
                           line("Factory", 500, 10), line("KEY TOOL", 100, 100), line("GX", 600, 10), line("20?", 700, 10)])
    assert [f["id"] for f in found] == ["k314", "k206", "kgs", "kkiba", "kfac"]  # misread 0/O and l/I still match
    assert found[1]["read"] == "2O6"
    # Two labels run together are split; positions come back in screenshot pixels.
    both = matcher.match([OcrLine.of_words([("314", (0, 0, 21, 12)), ("KIBA", (30, 0, 58, 12))])], origin=(1000, 500), scale=2)
    assert [f["id"] for f in both] == ["k314", "kkiba"]
    assert both[0]["x"] == 1005 and both[0]["y"] == 503
    # Full names (the key tool's tooltip) count too.
    assert [f["id"] for f in matcher.match([line("Dorm room 314 marked key", 0, 0)])] == ["k314"]


def test_gray_to_bgra():
    assert keyrooms.gray_to_bgra(bytes([0, 200])) == bytes([0, 0, 0, 255, 200, 200, 200, 255])


def test_owned_many(tmp_path):
    p = Progress(tmp_path / "p.json")
    p.apply({"op": "owned", "item": "a", "count": 2})
    snap = p.apply({"op": "owned_many", "items": {"a": 0, "b": 3, "c": 1}})
    assert snap["owned"] == {"b": 3, "c": 1}
    with pytest.raises(ProgressError):
        p.apply({"op": "owned_many", "items": {"../x": 1}})
    with pytest.raises(ProgressError):
        p.apply({"op": "owned_many", "items": ["a"]})


class FakeOcr:
    max_dimension = 600

    def __init__(self, lines):
        self.lines, self.seen = lines, []

    def read(self, bgra, w, h):
        self.seen.append((len(bgra), w, h))
        return self.lines


def test_keys_api(webapp, tmp_path, monkeypatch):
    from tarkov_display import screenshots

    key = next(i for i in webapp.app.prices.items if "keys" in i.tags)
    ocr = FakeOcr([line(key.short_name, 20, 20), line("nothing here", 20, 60)])
    webapp._key_ocr = ocr
    assert body(call(webapp.server, "/api/keys/ocr")) == {"engine": "FakeOcr", "maxDimension": 600}

    status, raw, _ = call(webapp.server, "/api/keys/read?w=4&h=2&x=100&y=50&scale=2", "POST", raw=bytes(8),
                          headers={"Content-Type": "application/octet-stream"})
    assert status == 200, raw
    got = body((status, raw, None))
    assert [f["id"] for f in got["found"]] == [key.id] and got["found"][0]["name"] == key.name
    assert got["found"][0]["x"] > 100 and ocr.seen == [(32, 4, 2)]  # grey turned into 32-bit pixels
    # Wrong size, too big for the reader, or JSON: refused.
    for path, data, ctype in (("w=4&h=3", bytes(8), "application/octet-stream"), ("w=700&h=1", bytes(700), "application/octet-stream"),
                              ("w=4&h=2", bytes(8), "application/json")):
        assert call(webapp.server, f"/api/keys/read?{path}", "POST", raw=data, headers={"Content-Type": ctype})[0] in (400, 415)

    # Your newest Tarkov screenshot.
    shots = tmp_path / "shots"
    monkeypatch.setattr(screenshots, "default_folder", lambda: shots)
    assert b"No Tarkov screenshots" in call(webapp.server, "/api/keys/screenshot")[1]
    shots.mkdir()
    (shots / "old.png").write_bytes(b"\x89PNG old")
    newest = shots / "2026-11-25[14-00]_1.0, 2.0, 3.0_0, 0, 0, 1_0.00 (0).png"
    newest.write_bytes(b"\x89PNG new")
    import os
    os.utime(shots / "old.png", (1, 1))
    status, raw, headers = call(webapp.server, "/api/keys/screenshot")
    assert status == 200 and raw == b"\x89PNG new" and headers["Content-Type"] == "image/png"
    assert "2026-11-25" in headers["X-Shot-Name"]


def test_maps_carry_key_loot(webapp):
    maps = webapp.store.get("maps", 10)["data"]
    assert any(m.get("keyLoot") for m in maps)
