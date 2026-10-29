"""Price check for the item under the mouse cursor.

Runs only when you press the hotkey, or with hover price check on when the
mouse rests on something in Tarkov (see hover.py): a screenshot of the area
around the cursor, read with OCR; reader.py works out which item it names.
If the game's name tooltip hasn't shown yet when you press the hotkey, the
scanner waits a moment for it, the way hover price check does: it takes
small snapshots of that area to spot the tooltip appearing (see tooltip.py)
and reads it.
"""

from __future__ import annotations

import itertools
import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple

from .matching import ItemMatcher, Match
from .ocr import create_ocr, order_by_distance
from .prices import PriceDB
from .profiles import ScanConfig
from .reader import Decision, Reader, segments
from .screen import ScreenSampler, to_bmp
from .tooltip import SCREEN_CHANGED, Area, Box, blank_boxes, find_tooltips, keep_only, overlaps

log = logging.getLogger(__name__)

Mask = Tuple[int, int, int, int]  # left, top, width, height on screen
TOOLTIP_MARGIN = 6  # pixels (at 1080p) read around the tooltip box
TOOLTIP_SCALE = 3   # enlarge the tooltip this much before OCR: its text is small
LABEL_SCALE = 3     # ... and the item's corner label
LABEL_AREA = (70, 210, 340, 6)  # where the item's own label can be: left of, above, right of, below the mouse (1080p)
WAIT_FOR_TOOLTIP = 1.2  # seconds Ctrl+Alt+P waits for the name tooltip when it isn't up yet
WAIT_STEP = 0.08
SURE = 0.92         # a tooltip read this good, with no close rival, needs no label to back it up
_saves = itertools.count()


@dataclass
class ScanResult:
    match: Optional[Match]
    lines: List[str] = field(default_factory=list)
    cursor: tuple = (0, 0)
    error: Optional[str] = None
    debug_file: Optional[Path] = None
    why: str = ""   # how the reader decided (for the debug log)
    hint: str = ""  # why there's no answer, for the player


def capture_rect(cursor, screen_height: int, cfg: ScanConfig):
    """Area to capture around the cursor, scaled from 1080p to this screen."""
    k = max(0.5, screen_height / 1080.0)
    cx, cy = cursor
    left = int(cfg.left * k)
    up = int(cfg.up * k)
    return cx - left, cy - up, left + int(cfg.right * k), up + int(cfg.down * k), left, up


def ocr_scale(wanted, w: int, h: int, max_dimension: int) -> int:
    """How much to enlarge the capture: as asked, but never past what the OCR
    engine accepts (Windows OCR refuses images over ~2600 pixels)."""
    fits = max(1, max_dimension // max(1, w, h))
    return max(1, min(int(wanted), fits))


class ItemScanner:
    def __init__(self, prices: PriceDB, cfg: ScanConfig, debug_dir: Optional[Path] = None) -> None:
        self.prices = prices
        self.cfg = cfg
        self.debug_dir = debug_dir
        self.screen = ScreenSampler()
        self.ocr = create_ocr()
        self._matcher: Optional[ItemMatcher] = None
        self._matcher_for = None
        self._reader: Optional[Reader] = None
        self._reader_for = None

    def matcher(self) -> ItemMatcher:
        items = self.prices.items
        if self._matcher_for is not items:
            self._matcher = ItemMatcher(items)
            self._matcher_for = items
        return self._matcher

    def reader(self) -> Reader:
        items = self.prices.items
        if self._reader_for is not items:
            self._reader = Reader(items)
            self._reader_for = items
        return self._reader

    def _k(self) -> float:
        return max(0.5, self.screen.target_rect()[3] / 1080.0)

    def scan(self, mask: Iterable[Mask] = (), quiet: bool = False, strict: bool = False) -> ScanResult:
        """Check the item under the cursor. ``mask``: screen boxes to leave out
        of the capture, such as our own popup. ``quiet``: log the result only
        in the debug log (hover checks). ``strict``: only answer from a full
        name, the tooltip's (hover checks that didn't see the tooltip appear)."""
        if not self.prices.items:
            return ScanResult(None, error="Prices not downloaded yet (check your internet connection).")
        cursor = self.screen.cursor_pos()
        screen_h = self.screen.target_rect()[3]
        x, y, w, h, cx, cy = capture_rect(cursor, screen_h, self.cfg)
        scale = ocr_scale(self.cfg.scale, w, h, getattr(self.ocr, "max_dimension", 2600))
        try:
            bgra, iw, ih = self.screen.grab(x, y, w, h, scale)
        except OSError as exc:
            return ScanResult(None, cursor=cursor, error=str(exc))
        bgra = blank_boxes(bgra, iw, ih, (x, y), mask, scale)

        lines = self.ocr.read(bgra, iw, ih)
        self.last_segments = segments(lines, (x, y), scale)  # for the accuracy bench's diagnostics
        decision = self.reader().decide(self.last_segments, cursor, self._k(), need_tooltip=strict)
        texts = [l.text for l in order_by_distance(lines, cx * scale, cy * scale)]
        result = ScanResult(_match(decision), texts, cursor, why=decision.why, hint=decision.hint)
        return self._done(result, bgra, iw, ih, quiet, "hover" if strict else "scan")

    def scan_waiting(self, mask: Iterable[Mask] = (), wait: float = WAIT_FOR_TOOLTIP,
                     sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> ScanResult:
        """Ctrl+Alt+P: check now, and if the name tooltip wasn't read (it shows
        a moment after the mouse stops), watch for it to appear for up to
        ``wait`` seconds and read it. Gives up when the mouse moves."""
        mask = list(mask)
        try:
            cursor = self.screen.cursor_pos()
            area = self.area_at(cursor)
            base = prev = self.snapshot(area, mask)
        except OSError:
            return self.scan(mask)
        first = self.scan(mask)
        if first.error or (first.match and first.match.full):
            return first
        tried: List[Box] = []
        end = clock() + wait
        while clock() < end:
            sleep(WAIT_STEP)
            now = self.screen.cursor_pos()
            if math.hypot(now[0] - cursor[0], now[1] - cursor[1]) > 4 * area.k:
                break
            try:
                cur = self.snapshot(area, mask)
            except OSError:
                break
            found = find_tooltips(base, prev, cur, area)
            prev = cur
            if found == SCREEN_CHANGED:
                break
            for f in found:
                if any(overlaps(f.box, t) for t in tried):
                    continue
                tried.append(f.box)
                result = self.read_tooltip(f.box, cursor, area.k, mask, f.keep)
                if result.match:
                    log.info("Scan: the tooltip showed after %.1fs: %s", wait - (end - clock()), result.match.item.name)
                    return result
        return first

    # -- hover price check ------------------------------------------------------

    def area_at(self, cursor: Tuple[int, int]) -> Area:
        """The area a check around ``cursor`` reads."""
        screen_h = self.screen.target_rect()[3]
        x, y, w, h, _, _ = capture_rect(cursor, screen_h, self.cfg)
        return Area(x, y, w, h, tuple(cursor), max(0.5, screen_h / 1080.0))

    def snapshot(self, area: Area, mask: Iterable[Mask] = ()) -> bytes:
        """A plain capture of ``area`` (for spotting what changes in it)."""
        bgra, w, h = self.screen.grab(area.x, area.y, area.w, area.h, 1)
        return blank_boxes(bgra, w, h, (area.x, area.y), mask)

    def read_tooltip(self, box: Box, cursor: Tuple[int, int], k: float = 1.0, mask: Iterable[Mask] = (),
                     keep: Iterable[Mask] = ()) -> ScanResult:
        """Read the item name from the tooltip at ``box`` (left, top, right,
        bottom on screen). ``keep``: if given, only these parts of the screen
        are read (the parts that changed when it appeared). Unless the name
        reads clearly, the item's own corner label is read too, to settle it."""
        if not self.prices.items:
            return ScanResult(None, error="Prices not downloaded yet (check your internet connection).")
        m = int(TOOLTIP_MARGIN * max(1.0, k))
        x, y = box[0] - m, box[1] - m
        w, h = box[2] - box[0] + 2 * m, box[3] - box[1] + 2 * m
        scale = ocr_scale(TOOLTIP_SCALE, w, h, getattr(self.ocr, "max_dimension", 2600))
        mask = list(mask)
        try:
            bgra, iw, ih = self.screen.grab(x, y, w, h, scale)
        except OSError as exc:
            return ScanResult(None, cursor=cursor, error=str(exc))
        keep = list(keep)
        if keep:
            bgra = keep_only(bgra, iw, ih, (x, y), keep, scale)
        bgra = blank_boxes(bgra, iw, ih, (x, y), mask, scale)
        lines = sorted(self.ocr.read(bgra, iw, ih), key=lambda l: (l.y, l.x))
        segs = segments(lines, (x, y), scale)
        reader = self.reader()
        decision = reader.decide(segs, cursor, k, tooltip_box=box)
        texts = [l.text for l in lines]
        if not _sure(decision):
            label = self._read_label(cursor, k, mask + [(box[0], box[1], box[2] - box[0], box[3] - box[1])])
            if label:
                label_segs, label_texts = label
                decision = reader.decide(segs + label_segs, cursor, k, tooltip_box=box)
                texts += [f"label: {t}" for t in label_texts]
        result = ScanResult(_match(decision), texts, cursor, why=decision.why, hint=decision.hint)
        return self._done(result, bgra, iw, ih, True, "tooltip")

    def _read_label(self, cursor, k: float, mask: List[Mask]):
        """OCR of where the item's own corner label can be (above and right of
        the mouse): (segments, texts), or None."""
        left, up, right, down = (int(v * k) for v in LABEL_AREA)
        x, y, w, h = cursor[0] - left, cursor[1] - up, left + right, up + down
        scale = ocr_scale(LABEL_SCALE, w, h, getattr(self.ocr, "max_dimension", 2600))
        try:
            bgra, iw, ih = self.screen.grab(x, y, w, h, scale)
        except OSError:
            return None
        bgra = blank_boxes(bgra, iw, ih, (x, y), mask, scale)
        lines = self.ocr.read(bgra, iw, ih)
        return segments(lines, (x, y), scale), [l.text for l in lines]

    # -- results ------------------------------------------------------------------

    def _done(self, result: ScanResult, bgra: bytes, w: int, h: int, quiet: bool, kind: str) -> ScanResult:
        match = result.match
        if self.cfg.debug and self.debug_dir:
            result.debug_file = self._save_debug(bgra, w, h, result, kind)
        say = log.debug if quiet else log.info
        if match:
            say("%s: %r -> %s (%.0f%%; %s)", kind.title(), match.text, match.item.name, match.score * 100, result.why)
        else:
            say("%s: no item matched (%s). OCR read: %s", kind.title(), result.why, result.lines)
        return result

    def _save_debug(self, bgra: bytes, w: int, h: int, result: ScanResult, kind: str = "scan") -> Path:
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        # Hover checks can save several a second: number them.
        stem = self.debug_dir / f"{kind}_{time.strftime('%Y%m%d_%H%M%S')}_{next(_saves) % 1000:03d}"
        stem.with_suffix(".bmp").write_bytes(to_bmp(bgra, w, h))
        found = f"{result.match.item.name} ({result.match.score:.0%})" if result.match else "no match"
        stem.with_suffix(".txt").write_text("\n".join(result.lines) + f"\n\n-> {found}\n{result.why}\n", encoding="utf-8")
        return stem.with_suffix(".bmp")


def _match(d: Decision) -> Optional[Match]:
    if d.item is None:
        return None
    return Match(d.item, d.score, d.text, d.full)


def _sure(d: Decision) -> bool:
    """A clear tooltip read with no close rival: no need to read the label too."""
    if d.item is None or not d.full or d.score < SURE:
        return False
    return not d.alternatives or d.score - d.alternatives[0][1] >= 0.08
