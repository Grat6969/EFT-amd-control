"""Price check for the item under the mouse cursor.

Runs only when you press the hotkey: one screenshot of the area around the
cursor, read with OCR, matched against the tarkov.dev item list.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .matching import ItemMatcher, Match, candidate_lines
from .ocr import create_ocr, order_by_distance
from .prices import PriceDB
from .profiles import ScanConfig
from .screen import ScreenSampler, to_bmp

log = logging.getLogger(__name__)


@dataclass
class ScanResult:
    match: Optional[Match]
    lines: List[str] = field(default_factory=list)
    cursor: tuple = (0, 0)
    error: Optional[str] = None
    debug_file: Optional[Path] = None


def capture_rect(cursor, screen_height: int, cfg: ScanConfig):
    """Area to capture around the cursor, scaled from 1080p to this screen."""
    k = max(0.5, screen_height / 1080.0)
    cx, cy = cursor
    left = int(cfg.left * k)
    up = int(cfg.up * k)
    return cx - left, cy - up, left + int(cfg.right * k), up + int(cfg.down * k), left, up


class ItemScanner:
    def __init__(self, prices: PriceDB, cfg: ScanConfig, debug_dir: Optional[Path] = None) -> None:
        self.prices = prices
        self.cfg = cfg
        self.debug_dir = debug_dir
        self.screen = ScreenSampler()
        self.ocr = create_ocr()
        self._matcher: Optional[ItemMatcher] = None
        self._matcher_for = None

    def matcher(self) -> ItemMatcher:
        items = self.prices.items
        if self._matcher_for is not items:
            self._matcher = ItemMatcher(items)
            self._matcher_for = items
        return self._matcher

    def scan(self) -> ScanResult:
        if not self.prices.items:
            return ScanResult(None, error="Prices not downloaded yet (check your internet connection).")
        cursor = self.screen.cursor_pos()
        screen_h = self.screen.target_rect()[3]
        x, y, w, h, cx, cy = capture_rect(cursor, screen_h, self.cfg)
        scale = max(1, int(self.cfg.scale))
        try:
            bgra, iw, ih = self.screen.grab(x, y, w, h, scale)
        except OSError as exc:
            return ScanResult(None, cursor=cursor, error=str(exc))

        lines = order_by_distance(self.ocr.read(bgra, iw, ih), cx * scale, cy * scale)
        texts = [l.text for l in lines]
        match = self.matcher().match_lines(candidate_lines(texts))
        result = ScanResult(match, texts, cursor)
        if self.cfg.debug and self.debug_dir:
            result.debug_file = self._save_debug(bgra, iw, ih, result)
        if match:
            log.info("Scan: %r -> %s (%.0f%%)", match.text, match.item.name, match.score * 100)
        else:
            log.info("Scan: no item matched. OCR read: %s", texts)
        return result

    def _save_debug(self, bgra: bytes, w: int, h: int, result: ScanResult) -> Path:
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        stem = self.debug_dir / time.strftime("scan_%Y%m%d_%H%M%S")
        stem.with_suffix(".bmp").write_bytes(to_bmp(bgra, w, h))
        found = f"{result.match.item.name} ({result.match.score:.0%})" if result.match else "no match"
        stem.with_suffix(".txt").write_text("\n".join(result.lines) + f"\n\n-> {found}\n", encoding="utf-8")
        return stem.with_suffix(".bmp")
