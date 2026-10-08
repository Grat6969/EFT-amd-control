"""Matches text read off the screen to a Tarkov item."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from .prices import Item, normalize

MIN_SCORE = 0.72
FULL_NAME_SCORE = 0.9  # a full-name match this good is the hover tooltip


@dataclass
class Match:
    item: Item
    score: float
    text: str
    full: bool = False  # matched the full name (only the tooltip shows it), not the short name


class ItemMatcher:
    def __init__(self, items: Sequence[Item]) -> None:
        self.by_name: Dict[str, Item] = {}
        self.by_short: Dict[str, Item] = {}
        for item in items:
            # Names are shared by an item and its presets; keep the base item.
            for key, index in ((normalize(item.name), self.by_name), (normalize(item.short_name), self.by_short)):
                if key and (key not in index or index[key].is_preset and not item.is_preset):
                    index[key] = item
        self.names = sorted(self.by_name, key=len, reverse=True)
        self.shorts = list(self.by_short)

    def match_line(self, text: str) -> Optional[Match]:
        line = normalize(text)
        if len(line) < 2:
            return None
        if line in self.by_name:
            return Match(self.by_name[line], 1.0, text, full=True)
        if line in self.by_short:
            return Match(self.by_short[line], 0.98, text)

        best: Optional[Match] = None
        # The tooltip line can carry extra text around the name.
        if len(line) >= 6:
            for name in self.names:
                if len(name) >= 6 and name in line:
                    best = Match(self.by_name[name], 0.95, text, full=True)
                    break  # names are sorted longest first
        if best is None:
            close = difflib.get_close_matches(line, self.names, n=1, cutoff=MIN_SCORE)
            if close:
                score = difflib.SequenceMatcher(None, line, close[0]).ratio()
                best = Match(self.by_name[close[0]], score, text, full=True)
        if len(line) >= 3:
            close = difflib.get_close_matches(line, self.shorts, n=1, cutoff=0.8)
            if close:
                score = difflib.SequenceMatcher(None, line, close[0]).ratio() * 0.95
                if best is None or score > best.score:
                    best = Match(self.by_short[close[0]], score, text)
        return best

    def match_lines(self, lines: Sequence[str]) -> Optional[Match]:
        """Pick the item for OCR lines ordered nearest-to-cursor first.

        Only the hover tooltip shows an item's full name; the grid shows
        short names. So the nearest good full-name match wins, even over a
        neighbouring item's short name closer to the cursor. Without one,
        the nearest confident match wins over a slightly better one further
        away.
        """
        matches = [m for m in (self.match_line(text) for text in lines) if m is not None]
        for m in matches:
            if m.full and m.score >= FULL_NAME_SCORE:
                return m
        for m in matches:
            if m.score >= 0.95:
                return m
        best = max(matches, key=lambda m: m.score, default=None)
        return best if best and best.score >= MIN_SCORE else None


def candidate_lines(lines: List[str]) -> List[str]:
    """OCR lines plus each pair of neighbouring lines joined, for names that wrap."""
    out = list(lines)
    out += [f"{a} {b}" for a, b in zip(lines, lines[1:])]
    return out
