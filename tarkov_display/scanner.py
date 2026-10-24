"""Price check for the item under the mouse cursor.

Runs only when you press the hotkey, or with hover price check on when the
mouse rests on something in Tarkov (see hover.py): one screenshot of the
area around the cursor, read with OCR, matched against the tarkov.dev item
list. Hover price check also takes small snapshots of that area to spot the
game's tooltip appearing (see tooltip.py), then reads just the tooltip.
"""

from __future__ import annotations

import itertools
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from .matching import FULL_NAME_SCORE, ItemMatcher, Match, candidate_lines
from .ocr import create_ocr, order_by_distance
from .prices import PriceDB
from .profiles import ScanConfig
from .screen import ScreenSampler, to_bmp
from .tooltip import Area, Box, blank_boxes, keep_only

log = logging.getLogger(__name__)

Mask = Tuple[int, int, int, int]  # left, top, width, height on screen
TOOLTIP_MARGIN = 6  # pixels (at 1080p) read around the tooltip box
TOOLTIP_SCALE = 3   # enlarge the tooltip this much before OCR: its text is small
_saves = itertools.count()


@dataclass
class ScanResult:
    match: Optional[Match]
    lines: List[str] = field(default_factory=list)
    cursor: tuple = (0, 0)
    error: Optional[str] = None
    debug_file: Optional[Path] = None
    via: str = "text"               # who read the name: "text" (Windows' text reader) or "claude"
    ai_error: Optional[str] = None  # why asking Claude didn't help, when it was asked


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
        self.ai = None  # AiReader (ai.py), set by the app

    def matcher(self) -> ItemMatcher:
        items = self.prices.items
        if self._matcher_for is not items:
            self._matcher = ItemMatcher(items)
            self._matcher_for = items
        return self._matcher

    def scan(self, mask: Iterable[Mask] = (), quiet: bool = False, strict: bool = False, ask_ai: bool = True) -> ScanResult:
        """Check the item under the cursor. ``mask``: screen boxes to leave out
        of the capture, such as our own popup. ``quiet``: log the result only
        in the debug log (hover checks). ``strict``: only accept a full name
        that can't be a grid label (hover checks that didn't find the tooltip).
        ``ask_ai``: Claude may be asked, if it's on (see ai.py)."""
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

        lines = order_by_distance(self.ocr.read(bgra, iw, ih), cx * scale, cy * scale)
        texts = [l.text for l in lines]
        matcher = self.matcher()
        match = matcher.match_lines(candidate_lines(texts), strict=strict)
        result = ScanResult(match, texts, cursor)
        sure = bool(match and match.full and match.score >= FULL_NAME_SCORE and not matcher.ambiguous(match))
        # Claude is asked only when something like an item name was read near the mouse.
        if ask_ai and self._ai_wanted(sure) and (match or matcher.match_lines(candidate_lines(texts))):
            self._ask_ai(result, bgra, iw, ih, "area", (cx * scale, cy * scale), sure)
        return self._done(result, bgra, iw, ih, quiet, "hover" if strict else "scan")

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
        bottom on screen). The text is known to be the tooltip, so a slightly
        misread full name still counts. ``keep``: if given, only these parts
        of the screen are read (the parts that changed when it appeared)."""
        if not self.prices.items:
            return ScanResult(None, error="Prices not downloaded yet (check your internet connection).")
        m = int(TOOLTIP_MARGIN * max(1.0, k))
        x, y = box[0] - m, box[1] - m
        w, h = box[2] - box[0] + 2 * m, box[3] - box[1] + 2 * m
        scale = ocr_scale(TOOLTIP_SCALE, w, h, getattr(self.ocr, "max_dimension", 2600))
        try:
            bgra, iw, ih = self.screen.grab(x, y, w, h, scale)
        except OSError as exc:
            return ScanResult(None, cursor=cursor, error=str(exc))
        keep = list(keep)
        if keep:
            bgra = keep_only(bgra, iw, ih, (x, y), keep, scale)
        bgra = blank_boxes(bgra, iw, ih, (x, y), mask, scale)
        texts = [l.text for l in sorted(self.ocr.read(bgra, iw, ih), key=lambda l: (l.y, l.x))]
        match = self.matcher().match_tooltip(candidate_lines(texts))
        result = ScanResult(match, texts, cursor)
        sure = bool(match and match.score >= 1.0)  # read exactly as an item's name
        if texts and self._ai_wanted(sure):
            self._ask_ai(result, bgra, iw, ih, "tooltip", None, sure)
        return self._done(result, bgra, iw, ih, True, "tooltip")

    # -- Claude (ai.py) -------------------------------------------------------------

    def _ai_wanted(self, sure: bool) -> bool:
        ai = getattr(self, "ai", None)
        return bool(ai and ai.wanted(sure))

    def _ask_ai(self, result: ScanResult, bgra: bytes, w: int, h: int, kind: str, cursor, sure: bool) -> None:
        """Ask Claude what the image shows, and use its answer if it names an item."""
        read = self.ai.read(bgra, w, h, kind, cursor)
        if read.error:
            result.ai_error = read.error
            return
        if read.name is None:
            result.lines.append("Claude: no item")
            if not sure:  # neither Claude nor the text reader can say what it is
                result.match = None
            return
        result.lines.append(f"Claude: {read.name}")
        match = self.matcher().match_tooltip([read.name])
        if match:
            result.match, result.via = match, "claude"
        else:
            result.ai_error = f"Claude read \u201c{read.name}\u201d, which isn't in the price list"

    # -- results ------------------------------------------------------------------

    def _done(self, result: ScanResult, bgra: bytes, w: int, h: int, quiet: bool, kind: str) -> ScanResult:
        match = result.match
        if self.cfg.debug and self.debug_dir:
            result.debug_file = self._save_debug(bgra, w, h, result, kind)
        say = log.debug if quiet else log.info
        if match:
            say("%s: %r -> %s (%.0f%%)", kind.title(), match.text, match.item.name, match.score * 100)
        else:
            say("%s: no item matched. OCR read: %s", kind.title(), result.lines)
        return result

    def _save_debug(self, bgra: bytes, w: int, h: int, result: ScanResult, kind: str = "scan") -> Path:
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        # Hover checks can save several a second: number them.
        stem = self.debug_dir / f"{kind}_{time.strftime('%Y%m%d_%H%M%S')}_{next(_saves) % 1000:03d}"
        stem.with_suffix(".bmp").write_bytes(to_bmp(bgra, w, h))
        found = f"{result.match.item.name} ({result.match.score:.0%})" if result.match else "no match"
        stem.with_suffix(".txt").write_text("\n".join(result.lines) + f"\n\n-> {found}\n", encoding="utf-8")
        return stem.with_suffix(".bmp")
