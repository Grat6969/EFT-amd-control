"""How often the price check names the right item, measured with a real OCR
engine on made-up Tarkov stash screens.

    python -m tests.reader_bench [--trials 150] [--seed 1] [--items FILE] [--ocr oracle --noise 0.03]

Each trial draws a stash grid packed with real items (names, short names and
sizes from tarkov.dev's item file, or FILE, a JSON list of them), puts the
mouse on one and draws the game's name tooltip next to it. Then the app's
own scanner reads it, with Windows OCR (Tesseract where Windows OCR isn't
installed), three ways:

- Ctrl+Alt+P with the tooltip showing
- Ctrl+Alt+P pressed before the tooltip showed (only grid labels to go on)
- hover price check (the tooltip appears after the mouse stops)

and so does a frozen copy of the v1.8.3 reader, for comparison. Wrong
answers and no answer are counted apart: no answer is better than a wrong
one. ``--ocr oracle`` stands in for the OCR engine with one that reads back
exactly the text that was drawn (with ``--noise``, a share of characters
misread the way OCR does): a quick check of how the reader picks the right
text, on any machine. Needs Pillow. Not part of the normal test run.
"""

from __future__ import annotations

import argparse
import base64
import difflib
import functools
import gzip
import json
import random
import string
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from tarkov_display.prices import Item, normalize

SCREEN = (1920, 1080)
CELL = 64                     # a stash cell at 1080p
STASH = (560, 260, 12, 9)     # left, top, columns, rows
BACKGROUNDS = {               # roughly the game's item background tints
    "default": (34, 36, 37), "black": (20, 20, 20), "blue": (30, 40, 54), "green": (31, 44, 31),
    "grey": (44, 46, 46), "orange": (56, 38, 22), "red": (54, 27, 25), "violet": (42, 31, 54),
    "yellow": (54, 52, 28),
}


# -- the item list ---------------------------------------------------------------------------


@dataclass
class Spec:
    item: Item
    w: int
    h: int
    background: str


KEEP = ("id", "name", "shortName", "width", "height", "backgroundColor", "types")


def download_items() -> List[dict]:
    from tarkov_display import staticapi
    from tarkov_display.client import TarkovClient

    return [{k: r.get(k) for k in KEEP} for r in staticapi.Source(TarkovClient()).items.values()]


def load_items(path: str) -> Tuple[List[Item], List[Spec]]:
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:
        return load_items_from(json.load(fh))


def load_items_from(raw: List[dict]) -> Tuple[List[Item], List[Spec]]:
    """Every item (what the matcher knows) and the ones to put in the stash."""
    items, specs = [], []
    for r in raw:
        if not r.get("id") or not r.get("name") or not r.get("shortName"):
            continue
        types = r.get("types") or []
        item = Item(id=r["id"], name=r["name"], short_name=r["shortName"], is_preset="preset" in types,
                    flea_banned="noFlea" in types, tags=list(types))
        items.append(item)
        w, h = r.get("width") or 1, r.get("height") or 1
        if not item.is_preset and w <= 5 and h <= 4:
            specs.append(Spec(item, w, h, r.get("backgroundColor") or "default"))
    return items, specs


# -- drawing a stash -------------------------------------------------------------------------


@functools.lru_cache(maxsize=None)
def font(size: int):
    from PIL import ImageFont

    for name in ("bahnschrift.ttf", "Bahnschrift.ttf", "DejaVuSansCondensed.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


@dataclass
class Placed:
    spec: Spec
    box: Tuple[int, int, int, int]  # screen pixels: left, top, right, bottom


@dataclass
class Scene:
    stash: object                    # PIL image of the whole screen, no tooltip
    tooltip: object                  # ... with the tooltip
    cursor: Tuple[int, int]
    target: Placed
    placed: List[Placed]
    texts: List[Tuple[str, Tuple[int, int, int, int]]] = field(default_factory=list)  # drawn, with screen boxes
    tip: Optional[Tuple[str, Tuple[int, int, int, int]]] = None


def write(draw, texts, xy, text, f, fill):
    """Draw ``text`` and note where (for the oracle OCR)."""
    draw.text(xy, text, fill=fill, font=f)
    x0, y0, x1, y1 = draw.textbbox(xy, text, font=f)
    texts.append((text, (int(x0), int(y0), int(x1), int(y1))))


def pack(specs: Sequence[Spec], rng: random.Random) -> List[Placed]:
    left, top, cols, rows = STASH
    used = [[False] * cols for _ in range(rows)]
    placed = []
    for r in range(rows):
        for c in range(cols):
            if used[r][c] or rng.random() < 0.12:
                continue
            for _ in range(12):
                spec = rng.choice(specs)
                if c + spec.w <= cols and r + spec.h <= rows and not any(
                        used[rr][cc] for rr in range(r, r + spec.h) for cc in range(c, c + spec.w)):
                    for rr in range(r, r + spec.h):
                        for cc in range(c, c + spec.w):
                            used[rr][cc] = True
                    x0, y0 = left + c * CELL, top + r * CELL
                    placed.append(Placed(spec, (x0, y0, x0 + spec.w * CELL, y0 + spec.h * CELL)))
                    break
    return placed


def draw_item(draw, p: Placed, rng: random.Random, label_size: int, texts: list) -> None:
    x0, y0, x1, y1 = p.box
    bg = BACKGROUNDS.get(p.spec.background, BACKGROUNDS["default"])
    draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=bg, outline=(72, 74, 74))
    # The icon: a few shapes in the item's colours, sometimes with print on it.
    for _ in range(rng.randint(3, 7)):
        tone = rng.randint(55, 150)
        col = (tone + rng.randint(-15, 15), tone + rng.randint(-15, 15), tone - rng.randint(0, 25))
        a = (rng.randint(x0 + 4, x1 - 8), rng.randint(y0 + 12, y1 - 8))
        b = (min(x1 - 3, a[0] + rng.randint(6, max(8, (x1 - x0) // 2))), min(y1 - 3, a[1] + rng.randint(6, max(8, (y1 - y0) // 2))))
        (draw.ellipse if rng.random() < 0.5 else draw.rectangle)((a, b), fill=col)
    if rng.random() < 0.15:
        word = "".join(rng.choice(string.ascii_uppercase) for _ in range(rng.randint(3, 6)))
        write(draw, texts, (x0 + 8, (y0 + y1) // 2), word, font(rng.randint(7, 9)), (30, 30, 30))
    # The short name in the top right corner, the stack count in the bottom right.
    f = font(label_size)
    text = p.spec.item.short_name
    tw = draw.textlength(text, font=f)
    tx, ty = x1 - 4 - tw, y0 + 2
    draw.text((tx + 1, ty + 1), text, fill=(8, 8, 8), font=f)
    write(draw, texts, (tx, ty), text, f, (210, 210, 204))
    if rng.random() < 0.3:
        count = rng.choice(["x2", "x3", "x10", "60", "120", "100/100", "18/18"])
        cw = draw.textlength(count, font=f)
        write(draw, texts, (x1 - 4 - cw, y1 - label_size - 4), count, f, (210, 210, 204))


def make_scene(specs: Sequence[Spec], rng: random.Random):
    """A Scene, and the texts still visible once the tooltip shows."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", SCREEN, (16, 17, 17))
    draw = ImageDraw.Draw(img)
    left, top, cols, rows = STASH
    for r in range(rows):  # empty cells
        for c in range(cols):
            x, y = left + c * CELL, top + r * CELL
            draw.rectangle((x, y, x + CELL - 1, y + CELL - 1), fill=(22, 23, 23), outline=(40, 41, 41))
    placed = pack(specs, rng)
    label_size = rng.choice([10, 11, 11, 12])
    texts: list = []
    for p in placed:
        draw_item(draw, p, rng, label_size, texts)
    # The mouse rests somewhere on an item, not on its label.
    target = rng.choice(placed)
    x0, y0, x1, y1 = target.box
    cursor = (rng.randint(x0 + 6, x1 - 8), rng.randint(y0 + 18, y1 - 6))
    with_tip = img.copy()
    tip_font = font(rng.choice([12, 13, 13, 14]))
    tdraw = ImageDraw.Draw(with_tip, "RGBA")
    name = target.spec.item.name
    tw = tdraw.textlength(name, font=tip_font)
    th = tip_font.size + 8
    dx, dy = rng.randint(12, 22), rng.choice([rng.randint(12, 26), rng.randint(12, 26), -th - rng.randint(4, 12)])
    bx, by = cursor[0] + dx, cursor[1] + dy
    if bx + tw + 12 > SCREEN[0]:
        bx = cursor[0] - dx - tw - 12
    tdraw.rectangle((bx, by, bx + tw + 12, by + th), fill=(8, 8, 8, 236), outline=(78, 78, 76, 255))
    tip: list = []
    write(tdraw, tip, (bx + 6, by + 3), name, tip_font, (232, 232, 226, 255))
    tip_box = (int(bx), int(by), int(bx + tw + 12), int(by + th))
    hidden = [t for t in texts if not _overlap(t[1], tip_box)]  # the tooltip covers what's under it
    return Scene(img, with_tip, cursor, target, placed, texts, (tip[0][0], tip[0][1]) if tip else None), hidden


def _overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


class FakeScreen:
    """The scanner's screen, showing a picture instead of the real one.
    ``texts``: what's written on it, for the oracle OCR."""

    last: Optional[tuple] = None  # the latest grab: x, y, w, h, scale, texts

    def __init__(self, image, cursor, texts=()):
        self.image, self.cursor, self.texts = image, cursor, list(texts)

    def cursor_pos(self):
        return self.cursor

    def target_rect(self):
        return 0, 0, SCREEN[0], SCREEN[1]

    def grab(self, x, y, w, h, scale=1):
        from PIL import Image

        FakeScreen.last = (x, y, w, h, scale, self.texts)
        crop = self.image.crop((x, y, x + w, y + h))
        if scale != 1:
            crop = crop.resize((w * scale, h * scale), Image.BILINEAR)
        return crop.convert("RGBA").tobytes("raw", "BGRA"), w * scale, h * scale


CONFUSIONS = {"0": "O", "O": "0", "o": "0", "1": "l", "l": "1", "I": "l", "i": "l", "5": "S", "S": "5", "6": "8",
              "8": "6", "3": "8", "B": "8", "Z": "2", "2": "Z", "g": "9", "e": "c", "c": "e", "u": "v", "n": "h"}


class OracleOcr:
    """Reads back the text drawn in the latest grab (see FakeScreen), word
    for word with boxes like Windows OCR, joining words on the same line
    that are close together; ``noise`` of the characters are misread."""

    max_dimension = 2600

    def __init__(self, noise: float = 0.0, seed: int = 0):
        self.noise = noise
        self.rng = random.Random(seed)

    def misread(self, text: str) -> str:
        out = []
        for ch in text:
            r = self.rng.random()
            if r < self.noise * 0.7 and ch in CONFUSIONS:
                out.append(CONFUSIONS[ch])
            elif r < self.noise * 0.85:
                continue  # dropped
            elif r < self.noise and ch.isalpha():
                out.append(self.rng.choice(string.ascii_lowercase))
            else:
                out.append(ch)
        return "".join(out)

    def read(self, bgra: bytes, w: int, h: int):
        from tarkov_display.ocr import OcrLine

        x, y, gw, gh, scale, texts = FakeScreen.last
        lines = []
        for text, (x0, y0, x1, y1) in texts:
            if x1 <= x or y1 <= y or x0 >= x + gw or y0 >= y + gh:
                continue
            cx, cy = ((x0 + x1) / 2 - x) * scale, ((y0 + y1) / 2 - y) * scale
            i = (int(min(h - 1, max(0, cy))) * w + int(min(w - 1, max(0, cx)))) * 4
            if bgra[i:i + 4] == bytes(4):
                continue  # blanked out
            box = ((x0 - x) * scale, (y0 - y) * scale, (x1 - x) * scale, (y1 - y) * scale)
            lines.append([self.misread(text), box])
        # OCR joins words on a line that are near each other.
        lines.sort(key=lambda t: (round(t[1][1] / (8 * scale)), t[1][0]))
        joined: list = []
        for text, box in lines:
            last = joined[-1] if joined else None
            if last and abs(last[1][1] - box[1]) < 4 * scale and 0 <= box[0] - last[1][2] < 14 * scale:
                last[0] += " " + text
                last[1] = (last[1][0], min(last[1][1], box[1]), box[2], max(last[1][3], box[3]))
            else:
                joined.append([text, box])
        return [OcrLine(t, (b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for t, b in joined if t.strip()]


# -- the v1.8.3 reader, frozen for comparison -------------------------------------------------


class BaselineMatcher:
    """matching.ItemMatcher as of v1.8.3."""

    MIN_SCORE, FULL_NAME_SCORE, TOOLTIP_SCORE = 0.72, 0.9, 0.8

    def __init__(self, items):
        self.by_name, self.by_short = {}, {}
        for item in items:
            for key, index in ((normalize(item.name), self.by_name), (normalize(item.short_name), self.by_short)):
                if key and (key not in index or index[key].is_preset and not item.is_preset):
                    index[key] = item
        self.names = sorted(self.by_name, key=len, reverse=True)
        self.shorts = list(self.by_short)

    def match_line(self, text):
        line = normalize(text)
        if len(line) < 2:
            return None
        if line in self.by_name:
            return (self.by_name[line], 1.0, True, line)
        if line in self.by_short:
            return (self.by_short[line], 0.98, False, line)
        best = None
        if len(line) >= 6:
            for name in self.names:
                if len(name) >= 6 and name in line:
                    best = (self.by_name[name], 0.95, True, name)
                    break
        if best is None:
            close = difflib.get_close_matches(line, self.names, n=1, cutoff=self.MIN_SCORE)
            if close:
                best = (self.by_name[close[0]], difflib.SequenceMatcher(None, line, close[0]).ratio(), True, close[0])
        if len(line) >= 3:
            close = difflib.get_close_matches(line, self.shorts, n=1, cutoff=0.8)
            if close:
                score = difflib.SequenceMatcher(None, line, close[0]).ratio() * 0.95
                if best is None or score > best[1]:
                    best = (self.by_short[close[0]], score, False, close[0])
        return best

    def match_lines(self, lines):
        matches = [m for m in (self.match_line(t) for t in lines) if m is not None]
        full = [m for m in matches if m[2] and m[1] >= self.FULL_NAME_SCORE]
        for m in full:
            if m[3] not in self.by_short:
                return m[0]
        if full:
            return full[0][0]
        for m in matches:
            if m[1] >= 0.95:
                return m[0]
        best = max(matches, key=lambda m: m[1], default=None)
        return best[0] if best and best[1] >= self.MIN_SCORE else None

    def match_tooltip(self, lines):
        matches = [m for m in (self.match_line(t) for t in lines) if m is not None and m[2]]
        best = max(matches, key=lambda m: m[1], default=None)
        return best[0] if best and best[1] >= self.TOOLTIP_SCORE else None


def candidate_lines(lines):
    return list(lines) + [f"{a} {b}" for a, b in zip(lines, lines[1:])]


def baseline_hotkey(screen, ocr, matcher, cursor):
    left, right, up, down, scale = 160, 520, 90, 90, 2
    x, y = cursor[0] - left, cursor[1] - up
    bgra, w, h = screen.grab(x, y, left + right, up + down, scale)
    lines = sorted(ocr.read(bgra, w, h), key=lambda l: ((l.x - left * scale) ** 2 + (2 * (l.y - up * scale)) ** 2))
    return matcher.match_lines(candidate_lines([l.text for l in lines])), [l.text for l in lines]


def baseline_tooltip(screen, ocr, matcher, box, keep):
    from tarkov_display.tooltip import keep_only

    m = 6
    x, y, w, h = box[0] - m, box[1] - m, box[2] - box[0] + 2 * m, box[3] - box[1] + 2 * m
    bgra, iw, ih = screen.grab(x, y, w, h, 3)
    bgra = keep_only(bgra, iw, ih, (x, y), keep, 3)
    lines = sorted(ocr.read(bgra, iw, ih), key=lambda l: (l.y, l.x))
    return matcher.match_tooltip(candidate_lines([l.text for l in lines])), [l.text for l in lines]


# -- one trial, both readers --------------------------------------------------------------------


def screens(scene, visible):
    """The stash without and with the tooltip, as the scanner's screen."""
    plain = FakeScreen(scene.stash, scene.cursor, scene.texts)
    tip = FakeScreen(scene.tooltip, scene.cursor, visible + ([scene.tip] if scene.tip else []))
    return plain, tip


def run_trial(scene, visible, scanner, ocr, baseline) -> Dict[str, Tuple[str, str, list]]:
    """{scenario: (current outcome, baseline outcome, what OCR read)}; an
    outcome is "right", "wrong" or "none"."""
    from tarkov_display.tooltip import SCREEN_CHANGED, find_tooltips

    want = scene.target.spec.item.id

    def outcome(item):
        return "none" if item is None else ("right" if item.id == want else "wrong")

    plain, tip = screens(scene, visible)
    out = {}
    for name, screen in (("hotkey + tooltip", tip), ("hotkey, no tooltip", plain)):
        scanner.screen = screen
        result = scanner.scan()
        base_item, read = baseline_hotkey(screen, ocr, baseline, scene.cursor)
        out[name] = (outcome(result.match.item if result.match else None), outcome(base_item), read)

    scanner.screen = plain
    area = scanner.area_at(scene.cursor)
    base = scanner.snapshot(area)
    scanner.screen = tip
    cur = scanner.snapshot(area)
    boxes = find_tooltips(base, cur, cur, area)
    boxes = [] if boxes == SCREEN_CHANGED else boxes
    current = old = None
    read: list = []
    for found in boxes[:4]:
        if current is None:
            result = scanner.read_tooltip(found.box, scene.cursor, area.k, keep=found.keep)
            current = result.match.item if result.match else None
            read += result.lines
        if old is None:
            old, _ = baseline_tooltip(tip, ocr, baseline, found.box, found.keep)
    out["hover"] = (outcome(current), outcome(old), read or ["(no tooltip box found)"])
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--trials", type=int, default=150)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--items", help="JSON list of items, may be .gz (default: download tarkov.dev's item file)")
    parser.add_argument("--ocr", choices=("real", "oracle"), default="real")
    parser.add_argument("--noise", type=float, default=0.0, help="oracle OCR: share of characters misread")
    parser.add_argument("--show", type=int, default=12, help="failures to print per scenario")
    parser.add_argument("--dump-items", action="store_true", help="print the item list (gzip, base64) at the end")
    args = parser.parse_args(argv)
    try:
        import PIL  # noqa: F401
    except ImportError:
        print("Needs Pillow: pip install pillow")
        return 2

    from tarkov_display.ocr import create_ocr
    from tarkov_display.prices import PriceDB
    from tarkov_display.profiles import ScanConfig
    from tarkov_display.scanner import ItemScanner

    raw = None
    if not args.items:
        raw = download_items()
        items, specs = load_items_from(raw)
    else:
        items, specs = load_items(args.items)
    print(f"{len(items)} items, {len(specs)} can go in the stash")
    ocr = OracleOcr(args.noise, args.seed) if args.ocr == "oracle" else create_ocr()
    print("OCR:", type(ocr).__name__, f"(noise {args.noise:.0%})" if args.ocr == "oracle" else "")
    db = PriceDB()
    db.set_items(items)
    scanner = object.__new__(ItemScanner)  # the real scanner, minus the real screen
    scanner.prices, scanner.cfg, scanner.debug_dir, scanner.ocr = db, ScanConfig(), None, ocr
    scanner._matcher = scanner._matcher_for = None
    baseline = BaselineMatcher(items)

    rng = random.Random(args.seed)
    tally: Dict[str, Counter] = defaultdict(Counter)
    by_size: Dict[str, Counter] = defaultdict(Counter)
    failures: Dict[str, list] = defaultdict(list)
    started = time.time()
    for trial in range(args.trials):
        scene, visible = make_scene(specs, rng)
        spec = scene.target.spec
        for scenario, (now, old, read) in run_trial(scene, visible, scanner, ocr, baseline).items():
            tally[scenario][f"current {now}"] += 1
            tally[scenario][f"baseline {old}"] += 1
            by_size[f"{scenario} | {'1x1' if spec.w * spec.h == 1 else 'bigger'}"][now] += 1
            if now != "right" and len(failures[scenario]) < args.show:
                failures[scenario].append(f"{spec.item.name} [{spec.item.short_name}, {spec.w}x{spec.h}] -> {now}; read {read[:8]}")
    took = time.time() - started

    print(f"\n{args.trials} trials in {took:.0f}s ({took / max(1, args.trials):.2f}s each)\n")
    print(f"{'scenario':22} {'':10} {'right':>6} {'wrong':>6} {'none':>6}")
    for scenario, counts in tally.items():
        for who in ("baseline", "current"):
            n = sum(counts[f"{who} {k}"] for k in ("right", "wrong", "none"))
            row = [100 * counts[f"{who} {k}"] / max(1, n) for k in ("right", "wrong", "none")]
            print(f"{scenario:22} {who:10} {row[0]:5.0f}% {row[1]:5.0f}% {row[2]:5.0f}%")
    print("\nby size (current):")
    for key, counts in sorted(by_size.items()):
        n = sum(counts.values())
        print(f"  {key:40} {100 * counts['right'] / n:5.0f}% right of {n}")
    for scenario, lines in failures.items():
        print(f"\nmisses, {scenario} (current):")
        for line in lines:
            print("  " + line)
    if args.dump_items and raw is not None:
        blob = base64.b64encode(gzip.compress(json.dumps(raw, separators=(",", ":")).encode(), 9)).decode()
        print(f"\nITEMS-GZ-BASE64 {len(blob)} chars")
        for i in range(0, len(blob), 4000):
            print("ITEMS:" + blob[i:i + 4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
