import gzip
import io
import json
import re
import struct
import urllib.error
import urllib.request

import pytest

from tarkov_display import prices as prices_mod
from tarkov_display.client import drop_nulls
from tarkov_display.matching import ItemMatcher, candidate_lines
from tarkov_display.ocr import OcrLine, order_by_distance, parse_tesseract_tsv
from tarkov_display.prices import (
    EUR_ID, LITE_ITEMS_URL, USD_ID, PriceDB, describe, error_message,
    parse_graphql_items, parse_hideout, parse_lite_items, parse_tasks, rub,
)
from tarkov_display.profiles import ScanConfig
from tarkov_display.scanner import capture_rect, ocr_scale
from tarkov_display.screen import to_bmp


# -- sample data shaped like tarkov.dev's responses ---------------------------

def raw_item(id, name, short, avg=None, low=None, w=1, h=1, types=(), sell=()):
    """One item from the GraphQL ``items`` query."""
    return {
        "id": id, "name": name, "shortName": short, "types": list(types), "width": w, "height": h,
        "basePrice": 1000, "avg24hPrice": avg, "lastLowPrice": low, "low24hPrice": low,
        "changeLast48hPercent": 2.5, "updated": "2026-10-08T00:00:00Z", "link": f"https://tarkov.dev/item/{id}",
        "sellFor": [{"priceRUB": p, "vendor": {"name": v}} for v, p in sell],
    }


API_ITEMS = [
    raw_item("ledx", "LEDX Skin Transilluminator", "LEDX", 1_050_000, 1_000_000,
             sell=[("Flea Market", 1_000_000), ("Therapist", 780_000), ("Jaeger", 600_000)]),
    raw_item("gpu", "Graphics card", "GPU", 450_000, 440_000, w=2, h=1,
             sell=[("Flea Market", 440_000), ("Mechanic", 300_000)]),
    raw_item("salewa", "Salewa first aid kit", "Salewa", 20_000, 18_000, sell=[("Therapist", 12_000)]),
    raw_item("tetriz", "Tetriz portable game console", "Tetriz", 40_000, 39_000, sell=[("Therapist", 25_000)]),
    raw_item("labskey", "TerraGroup Labs keycard (Red)", "Red", None, None, types=["noFlea"],
             sell=[("Therapist", 900_000)]),
    raw_item("m4preset", "Colt M4A1 5.56x45 assault rifle Default", "M4A1", 50_000, types=["preset"]),
    raw_item("m4", "Colt M4A1 5.56x45 assault rifle", "M4A1", 45_000),
]


def lite_item(uid, name, short, avg=None, low=None, slots=1, tags=(), trader=None, trader_price=None, cur="₽",
              base=1000):
    """One entry of /api/v1/items, as built by tarkov.dev's toLiteApiItem()."""
    return {
        "uid": uid, "name": name, "tags": list(tags), "shortName": short, "price": low, "basePrice": base,
        "avg24hPrice": avg, "traderName": trader, "traderPrice": trader_price,
        "traderPriceCur": cur if trader else None, "updated": "2026-10-08T00:00:00.000Z", "slots": slots,
        "diff24h": 1200, "icon": "", "link": f"https://tarkov.dev/item/{uid}", "wikiLink": "", "img": "",
        "imgBig": "", "img512": "", "image8x": "", "bsgId": uid, "isFunctional": True,
        "reference": "https://tarkov.dev",
    }


LITE_ITEMS = [
    lite_item(USD_ID, "Dollars", "USD", tags=["money"], base=142),
    lite_item(EUR_ID, "Euros", "EUR", tags=["money"], base=160),
    lite_item("ledx", "LEDX Skin Transilluminator", "LEDX", 1_050_000, 1_000_000,
              trader="Therapist", trader_price=780_000),
    lite_item("gpu", "Graphics card", "GPU", 450_000, 440_000, slots=2, trader="Mechanic", trader_price=300_000),
    lite_item("rooster", "Golden rooster figurine", "Rooster", 60_000, 58_000, slots=2,
              trader="Peacekeeper", trader_price=300, cur="$"),
    lite_item("gun", "Ragman jacket", "Jacket", None, None, trader="Ragman", trader_price=100, cur="€"),
    lite_item("labskey", "TerraGroup Labs keycard (Red)", "Red", None, None, tags=["noFlea"],
              trader="Therapist", trader_price=900_000),
    lite_item("junk", "Nobody buys this", "Junk", 5_000, 4_000),
]

STATIONS = [
    {"name": "Medstation", "levels": [{"level": 3, "itemRequirements": [{"count": 1, "item": {"id": "ledx"}}]}]},
    {"name": "Intelligence Center", "levels": [{"level": 1, "itemRequirements": []}]},
]

TASKS = [
    {"name": "Private Clinic", "objectives": [{"count": 2, "foundInRaid": True, "items": [{"id": "ledx"}]}, {}]},
    # A find + hand-over pair for the same item counts once.
    {"name": "Shortage", "objectives": [
        {"count": 3, "foundInRaid": True, "items": [{"id": "salewa"}]},
        {"count": 3, "foundInRaid": False, "items": [{"id": "salewa"}]},
    ]},
    {"name": "Gunsmith - Part 1", "objectives": [{}]},  # non-item objectives come back empty
]


def make_items():
    items = parse_graphql_items(API_ITEMS)
    hideout, quests = parse_hideout(STATIONS), parse_tasks(TASKS)
    for item in items:
        item.hideout = hideout.get(item.id, [])
        item.quests = quests.get(item.id, [])
    return items


def db():
    d = PriceDB()
    d.set_items(make_items())
    return d


def by_id(items, id):
    return next(i for i in items if i.id == id)


# -- parsing ------------------------------------------------------------------

def test_parse_graphql_items():
    items = make_items()
    ledx = by_id(items, "ledx")
    assert ledx.best_trader == "Therapist" and ledx.best_trader_price == 780_000
    assert ledx.flea_price == 1_050_000 and ledx.best_place == "Flea Market"
    assert ledx.hideout == ["Medstation 3 x1"] and ledx.quests == ["Private Clinic x2 FiR"]
    gpu = by_id(items, "gpu")
    assert gpu.slots == 2 and gpu.size == "2x1" and gpu.per_slot == 225_000
    key = by_id(items, "labskey")
    assert key.flea_banned and key.flea_price is None and key.best_place == "Therapist"


def test_parse_lite_items_converts_currencies():
    items = parse_lite_items(LITE_ITEMS)
    ledx = by_id(items, "ledx")
    assert ledx.avg24h == 1_050_000 and ledx.last_low == 1_000_000
    assert ledx.best_trader == "Therapist" and ledx.best_trader_price == 780_000
    rooster = by_id(items, "rooster")
    assert rooster.best_trader == "Peacekeeper" and rooster.best_trader_price == 300 * 142
    assert rooster.slots == 2 and rooster.per_slot == 30_000
    assert by_id(items, "gun").best_trader_price == 100 * 160
    assert by_id(items, "labskey").flea_banned
    junk = by_id(items, "junk")
    assert junk.best_trader is None and junk.best_trader_price == 0 and junk.best_place == "Flea Market"


def test_parse_lite_items_without_rate_skips_foreign_trader():
    items = parse_lite_items([i for i in LITE_ITEMS if i["uid"] != USD_ID])
    rooster = by_id(items, "rooster")
    assert rooster.best_trader is None and rooster.best_trader_price == 0


def test_parse_tasks():
    quests = parse_tasks(TASKS)
    assert quests == {"ledx": ["Private Clinic x2 FiR"], "salewa": ["Shortage x3 FiR"]}


def test_cache_roundtrip(tmp_path):
    path = tmp_path / "prices.json"
    d = PriceDB(path)
    d.set_items(make_items())
    d.needs_updated = 123.0
    d.save_cache()
    again = PriceDB(path)
    assert len(again.items) == len(API_ITEMS)
    assert by_id(again.items, "ledx").hideout == ["Medstation 3 x1"]
    assert again.needs_updated == 123.0
    assert PriceDB(path, game_mode="pve").items == []  # PvE uses its own prices


def test_old_cache_format_is_ignored(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text(json.dumps({"updated": 1.0, "game_mode": "regular", "items": [
        {"id": "x", "name": "X", "short_name": "X", "width": 1, "height": 1},
    ]}))
    assert PriceDB(path).items == []


# -- talking to tarkov.dev ------------------------------------------------------

class FakeResponse:
    def __init__(self, body, headers=None):
        self.body = body
        self.headers = headers or {}

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


def http_422(url):
    body = json.dumps({"errors": ["GraphQL server unavailable. Try again later."]}).encode()
    return urllib.error.HTTPError(url, 422, "Unprocessable Entity", {}, io.BytesIO(body))


class FakeTarkovDev:
    def __init__(self, monkeypatch, lite_ok=True, graphql_ok=True, needs_ok=True):
        self.lite_ok, self.graphql_ok, self.needs_ok = lite_ok, graphql_ok, needs_ok
        self.calls = []
        monkeypatch.setattr(urllib.request, "urlopen", self.urlopen)

    def kinds(self):
        return [c[0] for c in self.calls]

    def urlopen(self, req, timeout):
        assert req.get_header("Accept") == "application/json"
        if req.full_url == LITE_ITEMS_URL:
            self.calls.append(("lite", None))
            if not self.lite_ok:
                raise http_422(req.full_url)
            return FakeResponse(gzip.compress(json.dumps(LITE_ITEMS).encode()), {"Content-Encoding": "gzip"})
        query = json.loads(req.data)["query"]
        if "hideoutStations" in query:
            kind, ok, data = "hideout", self.needs_ok, {"hideoutStations": STATIONS}
        elif "tasks(" in query:
            kind, ok, data = "tasks", self.needs_ok, {"tasks": TASKS}
        else:
            limit = int(re.search(r"limit: (\d+)", query).group(1))
            offset = int(re.search(r"offset: (\d+)", query).group(1))
            kind, ok, data = "items", self.graphql_ok, {"items": API_ITEMS[offset:offset + limit]}
        self.calls.append((kind, query))
        if not ok:
            raise http_422(req.full_url)
        return FakeResponse(json.dumps({"data": data}).encode())


def test_regular_mode_uses_item_list(monkeypatch):
    api = FakeTarkovDev(monkeypatch)
    d = PriceDB()
    assert d.refresh() is True and d.error is None
    assert api.kinds() == ["lite", "hideout", "tasks"]
    ledx = by_id(d.items, "ledx")
    assert ledx.flea_price == 1_050_000
    assert ledx.hideout == ["Medstation 3 x1"] and ledx.quests == ["Private Clinic x2 FiR"]
    assert by_id(d.items, "rooster").best_trader_price == 300 * 142


def test_falls_back_to_paged_graphql(monkeypatch):
    monkeypatch.setattr(prices_mod, "PAGE_SIZE", 3)
    api = FakeTarkovDev(monkeypatch, lite_ok=False)
    d = PriceDB()
    assert d.refresh() is True
    item_queries = [q for kind, q in api.calls if kind == "items"]
    assert [re.search(r"offset: (\d+)", q).group(1) for q in item_queries] == ["0", "3", "6"]
    assert len(d.items) == len(API_ITEMS)
    assert by_id(d.items, "gpu").size == "2x1"


def test_pve_never_uses_item_list(monkeypatch):
    # tarkov.dev's plain list returns PvP prices even for /pve/.
    api = FakeTarkovDev(monkeypatch)
    d = PriceDB(game_mode="pve")
    assert d.refresh() is True
    assert "lite" not in api.kinds()
    assert all("gameMode: pve" in q for kind, q in api.calls)


def test_error_message_when_tarkov_dev_is_down(monkeypatch):
    FakeTarkovDev(monkeypatch, lite_ok=False, graphql_ok=False)
    d = PriceDB()
    assert d.refresh() is False
    assert "422" in d.error and "GraphQL server unavailable" in d.error
    assert error_message(b"", 500, "Server Error") == "HTTP 500 Server Error"
    assert error_message(b'{"errors": [{"message": "Bad"}]}', 400, "Bad Request") == "HTTP 400: Bad"


def test_prices_load_when_quest_and_hideout_requests_fail(monkeypatch):
    api = FakeTarkovDev(monkeypatch)
    d = PriceDB()
    assert d.refresh() is True
    assert by_id(d.items, "ledx").hideout == ["Medstation 3 x1"]

    # A later refresh where only prices work keeps the earlier requirements.
    api.needs_ok = False
    d.needs_updated = 0
    assert d.refresh() is True and d.error is None
    ledx = by_id(d.items, "ledx")
    assert ledx.hideout == ["Medstation 3 x1"] and ledx.quests == ["Private Clinic x2 FiR"]
    assert d.needs_updated == 0  # retried next time


def test_requirements_not_refetched_while_fresh(monkeypatch):
    api = FakeTarkovDev(monkeypatch)
    d = PriceDB()
    d.refresh()
    api.calls.clear()
    d.refresh()
    assert api.kinds() == ["lite"]
    assert by_id(d.items, "ledx").quests == ["Private Clinic x2 FiR"]


def test_partial_graphql_answers_are_used(monkeypatch):
    # tarkov.dev leaves nulls where single entries failed and still sends the rest.
    api = FakeTarkovDev(monkeypatch, lite_ok=False)
    real = api.urlopen

    def urlopen(req, timeout):
        body = json.loads(real(req, timeout).body)
        for value in body["data"].values():
            value.insert(0, None)
            for entry in value:
                for objective in (entry or {}).get("objectives") or []:
                    objective.get("items", []).append(None)
        body["errors"] = [{"message": "Cannot return null for non-nullable field Task.name."}]
        return FakeResponse(json.dumps(body).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    d = PriceDB()
    assert d.refresh() is True and d.error is None
    assert len(d.items) == len(API_ITEMS)
    ledx = by_id(d.items, "ledx")
    assert ledx.hideout == ["Medstation 3 x1"] and ledx.quests == ["Private Clinic x2 FiR"]
    assert drop_nulls({"a": [None, {"b": [1, None, [None]]}], "c": None}) == {"a": [{"b": [1, []]}], "c": None}


# -- search, matching and display ----------------------------------------------

def test_search():
    d = db()
    assert d.search("ledx")[0].id == "ledx"
    assert d.search("graph")[0].id == "gpu"
    assert d.search("first aid")[0].id == "salewa"
    assert d.search("m4a1")[0].id == "m4"  # base item before preset
    assert d.search("") == []


def test_match_ocr_text():
    m = ItemMatcher(db().items)
    assert m.match_lines(["LEDX Skin Transilluminator"]).item.id == "ledx"
    assert m.match_lines(["LEDX"]).item.id == "ledx"
    assert m.match_lines(["Graphics cord"]).item.id == "gpu"          # OCR typo
    assert m.match_lines(["Tetrlz portable game console"]).item.id == "tetriz"
    assert m.match_lines(["Salewa first aid kit (400/400)"]).item.id == "salewa"  # extra text
    assert m.match_lines(["Colt M4A1 5.56x45 assault rifle"]).item.id == "m4"
    assert m.match_lines(["Examine", "x2"]) is None


def test_nearest_line_wins():
    m = ItemMatcher(db().items)
    # Nearest the cursor first: a confident hit there beats a neighbour.
    assert m.match_lines(["Tetriz", "LEDX Skin Transilluminator"]).item.id == "tetriz"


def test_wrapped_name():
    m = ItemMatcher(db().items)
    lines = candidate_lines(["LEDX Skin", "Transilluminator"])
    assert m.match_lines(lines).item.id == "ledx"


def test_order_by_distance():
    lines = [OcrLine("far", 500, 300), OcrLine("near", 330, 190), OcrLine("mid", 100, 180)]
    assert [l.text for l in order_by_distance(lines, 320, 180)] == ["near", "mid", "far"]


def test_available_ocr_engine(monkeypatch):
    import importlib.util

    from tarkov_display import ocr

    monkeypatch.setattr(ocr, "find_tesseract", lambda: None)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: (_ for _ in ()).throw(ModuleNotFoundError(name)))
    assert ocr.available_engine() is None
    monkeypatch.setattr(ocr, "find_tesseract", lambda: "tesseract.exe")
    assert ocr.available_engine() == "Tesseract"
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    assert ocr.available_engine() == "Windows OCR"


def test_parse_tesseract_tsv():
    tsv = "\n".join([
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
        "5\t1\t1\t1\t1\t1\t10\t20\t40\t12\t95\tGraphics",
        "5\t1\t1\t1\t1\t2\t55\t20\t30\t12\t95\tcard",
        "5\t1\t2\t1\t1\t1\t10\t80\t30\t12\t90\tGPU",
        "4\t1\t2\t1\t1\t0\t10\t80\t30\t12\t-1\t",
    ])
    lines = parse_tesseract_tsv(tsv)
    assert [l.text for l in lines] == ["Graphics card", "GPU"]
    assert lines[0].x == (10 + 85) / 2


def test_to_bmp():
    w, h = 3, 2
    bgra = bytes([1, 2, 3, 255]) * (w * h)
    bmp = to_bmp(bgra, w, h)
    assert bmp[:2] == b"BM"
    assert struct.unpack("<I", bmp[2:6])[0] == len(bmp)
    row = 3 * w + 3  # padded to 4 bytes
    assert len(bmp) == 54 + row * h
    assert bmp[54:57] == bytes([1, 2, 3])


def test_capture_rect_scales_with_resolution():
    cfg = ScanConfig(left=100, right=400, up=50, down=50)
    x, y, w, h, cx, cy = capture_rect((1000, 500), 1080, cfg)
    assert (x, y, w, h, cx, cy) == (900, 450, 500, 100, 100, 50)
    x, y, w, h, cx, cy = capture_rect((2000, 1000), 2160, cfg)
    assert (w, h) == (1000, 200) and (x, y) == (1800, 900)


@pytest.mark.parametrize("item_id, size_text", [("gpu", "(2x1)"), ("ledx", None)])
def test_describe(item_id, size_text):
    d = db()
    lines = describe(by_id(d.items, item_id))
    per_slot = next(l for l in lines if l.startswith("Per slot"))
    assert (size_text in per_slot) if size_text else ("(" not in per_slot)


def test_describe_details():
    d = db()
    lines = describe(by_id(d.items, "ledx"))
    assert lines[0] == "LEDX Skin Transilluminator"
    assert any("Therapist" in l for l in lines)
    assert "Hideout: Medstation 3 x1" in lines
    assert "Quests: Private Clinic x2 FiR" in lines
    assert "can't be sold" in describe(by_id(d.items, "labskey"))[1]
    lite = parse_lite_items(LITE_ITEMS)
    assert any("(2 slots)" in l for l in describe(by_id(lite, "rooster")))
    assert rub(1234567) == "1 234 567 ₽" and rub(None) == "-"


def test_item_list_error_object_falls_back(monkeypatch):
    api = FakeTarkovDev(monkeypatch)
    real = api.urlopen

    def urlopen(req, timeout):
        if req.full_url == LITE_ITEMS_URL:
            api.calls.append(("lite", None))
            return FakeResponse(json.dumps({"errors": ["busy"]}).encode())
        return real(req, timeout)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    d = PriceDB()
    assert d.refresh() is True
    assert "items" in api.kinds() and len(d.items) == len(API_ITEMS)


def test_ocr_scale_respects_engine_limit():
    assert ocr_scale(2, 680, 180, 2600) == 2          # 1080p: doubled
    assert ocr_scale(2, 1360, 360, 2600) == 1         # 4K: doubling would be 2720 px
    assert ocr_scale(3, 600, 100, 10000) == 3
    assert ocr_scale(0, 600, 100, 2600) == 1
