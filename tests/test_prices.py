import struct

from tarkov_display.prices import describe, rub
from tarkov_display.matching import ItemMatcher, candidate_lines
from tarkov_display.ocr import OcrLine, order_by_distance, parse_tesseract_tsv
from tarkov_display.prices import PriceDB, parse_items
from tarkov_display.profiles import ScanConfig
from tarkov_display.scanner import capture_rect
from tarkov_display.screen import to_bmp


def raw_item(id, name, short, avg=None, low=None, w=1, h=1, types=(), sell=(), tasks=()):
    return {
        "id": id, "name": name, "shortName": short, "types": list(types), "width": w, "height": h,
        "basePrice": 1000, "avg24hPrice": avg, "lastLowPrice": low, "low24hPrice": low,
        "changeLast48hPercent": 2.5, "updated": "2026-10-08T00:00:00Z", "link": f"https://tarkov.dev/item/{id}",
        "sellFor": [{"priceRUB": p, "vendor": {"name": v}} for v, p in sell],
        "usedInTasks": [{"name": t} for t in tasks],
    }


API_DATA = {
    "items": [
        raw_item("ledx", "LEDX Skin Transilluminator", "LEDX", 1_050_000, 1_000_000,
                 sell=[("Flea Market", 1_000_000), ("Therapist", 780_000), ("Jaeger", 600_000)],
                 tasks=["Private clinic"]),
        raw_item("gpu", "Graphics card", "GPU", 450_000, 440_000, w=2, h=1,
                 sell=[("Flea Market", 440_000), ("Mechanic", 300_000)]),
        raw_item("salewa", "Salewa first aid kit", "Salewa", 20_000, 18_000,
                 sell=[("Therapist", 12_000)]),
        raw_item("tetriz", "Tetriz portable game console", "Tetriz", 40_000, 39_000,
                 sell=[("Therapist", 25_000)]),
        raw_item("labskey", "TerraGroup Labs keycard (Red)", "Red", None, None, types=["noFlea"],
                 sell=[("Therapist", 900_000)]),
        raw_item("m4preset", "Colt M4A1 5.56x45 assault rifle Default", "M4A1", 50_000, types=["preset"]),
        raw_item("m4", "Colt M4A1 5.56x45 assault rifle", "M4A1", 45_000),
    ],
    "hideoutStations": [
        {"name": "Medstation", "levels": [{"level": 3, "itemRequirements": [{"count": 1, "item": {"id": "ledx"}}]}]},
    ],
}


def db():
    d = PriceDB()
    d.set_items(parse_items(API_DATA))
    return d


def by_id(items, id):
    return next(i for i in items if i.id == id)


def test_parse_items():
    items = parse_items(API_DATA)
    ledx = by_id(items, "ledx")
    assert ledx.best_trader == "Therapist" and ledx.best_trader_price == 780_000
    assert ledx.flea_price == 1_050_000 and ledx.best_place == "Flea Market"
    assert ledx.hideout == ["Medstation 3 (x1)"] and ledx.quests == ["Private clinic"]
    gpu = by_id(items, "gpu")
    assert gpu.slots == 2 and gpu.per_slot == 225_000
    key = by_id(items, "labskey")
    assert key.flea_banned and key.flea_price is None and key.best_place == "Therapist"


def test_cache_roundtrip(tmp_path):
    path = tmp_path / "prices.json"
    d = PriceDB(path)
    d.set_items(parse_items(API_DATA))
    d.save_cache()
    again = PriceDB(path)
    assert len(again.items) == len(API_DATA["items"])
    assert by_id(again.items, "ledx").hideout == ["Medstation 3 (x1)"]
    assert PriceDB(path, game_mode="pve").items == []  # PvE uses its own prices


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


def test_describe():
    d = db()
    lines = describe(by_id(d.items, "ledx"))
    assert lines[0] == "LEDX Skin Transilluminator"
    assert any("Therapist" in l for l in lines)
    assert any(l.startswith("Hideout: Medstation 3") for l in lines)
    assert "can't be sold" in describe(by_id(d.items, "labskey"))[1]
    assert rub(1234567) == "1 234 567 ₽" and rub(None) == "-"
