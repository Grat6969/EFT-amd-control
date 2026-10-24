"""Finds the game's item tooltip by watching it appear.

Text alone can't tell Tarkov's tooltip from the names printed on the grid:
many items' short names (Toolset, Bolts, Pliers...) are also full names,
and the item next to the one you're pointing at can be nearer the mouse
than the tooltip. But the tooltip always appears after the mouse stops on
an item, while the grid around it stays still. So hover price check takes a
snapshot of the area around the mouse as soon as it stops, and compares
later snapshots with it: a box near the mouse that wasn't there before and
has stopped changing (fade-in done) is the tooltip, wherever the game drew
it. Only that box is read.

Pure functions on top-down 32-bit BGRA buffers, so they can be tested
without Windows.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, Set, Tuple

from .screen import blank_area

Box = Tuple[int, int, int, int]  # left, top, right, bottom (right/bottom exclusive)

BLOCK = 8              # snapshots are compared in squares of this many pixels
SCREEN_CHANGED = "screen changed"  # most of the area changed: scrolled, a window opened...
CHANGED_SHARE = 0.35   # ... this share of it, or more
REACH = 110            # the tooltip box starts within this many pixels of the mouse (at 1080p)
MIN_W, MIN_H, MAX_H = 20, 8, 90  # tooltip box size limits, in pixels at 1080p


@dataclass(frozen=True)
class Found:
    """Something that appeared near the mouse: the box around it, and the
    parts of it that changed (screen rectangles left, top, width, height).
    Only those parts are read, so nothing that was already on screen (a
    neighbour's grid label inside the box, say) can be read with it."""

    box: Box
    keep: Tuple[Tuple[int, int, int, int], ...] = ()


@dataclass(frozen=True)
class Area:
    """The part of the screen watched around the mouse."""

    x: int
    y: int
    w: int
    h: int
    cursor: Tuple[int, int]  # the mouse, in screen pixels
    k: float = 1.0           # screen height / 1080

    def to_screen(self, box: Box) -> Box:
        x0, y0, x1, y1 = box
        return self.x + x0, self.y + y0, self.x + x1, self.y + y1


def keep_only(bgra: bytes, w: int, h: int, origin: Tuple[int, int], rects: Iterable[Tuple[int, int, int, int]],
              scale: int = 1) -> bytes:
    """``bgra`` with everything outside the screen rectangles (left, top,
    width, height) painted black. Same arguments as blank_boxes."""
    out = bytearray(len(bgra))
    ox, oy = origin
    for rx, ry, rw, rh in rects:
        x0, x1 = max(0, (rx - ox) * scale), min(w, (rx + rw - ox) * scale)
        y0, y1 = max(0, (ry - oy) * scale), min(h, (ry + rh - oy) * scale)
        for row in range(y0, y1):
            a, b = (row * w + x0) * 4, (row * w + x1) * 4
            out[a:b] = bgra[a:b]
    return bytes(out)


def blank_boxes(bgra: bytes, w: int, h: int, origin: Tuple[int, int], boxes: Iterable[Tuple[int, int, int, int]],
                scale: int = 1) -> bytes:
    """``bgra`` (a capture whose top-left is at ``origin`` on screen, enlarged
    ``scale`` times) with each screen box (left, top, width, height) painted black."""
    ox, oy = origin
    for bx, by, bw, bh in boxes:
        bgra = blank_area(bgra, w, h, (bx - ox) * scale, (by - oy) * scale, (bx + bw - ox) * scale, (by + bh - oy) * scale)
    return bgra


def changed_blocks(a: bytes, b: bytes, w: int, h: int, block: int = BLOCK, row_step: int = 1) -> Set[Tuple[int, int]]:
    """The squares (column, row) where two same-size captures differ."""
    stride = w * 4
    blocks_across = (w + block - 1) // block
    changed: Set[Tuple[int, int]] = set()
    for y in range(0, h, max(1, row_step)):
        start = y * stride
        row_a, row_b = a[start:start + stride], b[start:start + stride]
        if row_a == row_b:
            continue
        by = y // block
        for bx in range(blocks_across):
            if (bx, by) in changed:
                continue
            s = bx * block * 4
            if row_a[s:s + block * 4] != row_b[s:s + block * 4]:
                changed.add((bx, by))
    return changed


def groups(blocks: Set[Tuple[int, int]]) -> List[Set[Tuple[int, int]]]:
    """Touching squares (including diagonally) grouped together."""
    left, out = set(blocks), []
    while left:
        seed = left.pop()
        group, todo = {seed}, [seed]
        while todo:
            bx, by = todo.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    n = (bx + dx, by + dy)
                    if n in left:
                        left.remove(n)
                        group.add(n)
                        todo.append(n)
        out.append(group)
    return out


def _distance(point: Tuple[float, float], box: Box) -> float:
    x, y = point
    x0, y0, x1, y1 = box
    dx = max(x0 - x, 0, x - x1)
    dy = max(y0 - y, 0, y - y1)
    return math.hypot(dx, dy)


def changed_share(a: bytes, b: bytes, area: Area, block: int = BLOCK) -> float:
    """How much of the area differs between two snapshots (0..1)."""
    if a == b:
        return 0.0
    w, h = area.w, area.h
    total = ((w + block - 1) // block) * ((h + block - 1) // block)
    return len(changed_blocks(a, b, w, h, block, max(1, int(area.k)))) / max(1, total)


def _bounds(blocks) -> Tuple[int, int, int, int]:
    xs = [bx for bx, _ in blocks]
    ys = [by for _, by in blocks]
    return min(xs), min(ys), max(xs), max(ys)


def _join_lines(parts: List[Set[Tuple[int, int]]], gap: int = 2) -> List[Set[Tuple[int, int]]]:
    """Join groups side by side on the same line with at most ``gap`` squares
    between them: one tooltip can come out in pieces where its background
    happens to match what was behind it."""
    parts = [set(p) for p in parts]
    joined = True
    while joined:
        joined = False
        for i in range(len(parts)):
            for j in range(i + 1, len(parts)):
                a, b = _bounds(parts[i]), _bounds(parts[j])
                same_line = a[1] <= b[3] and b[1] <= a[3]
                if same_line and max(a[0], b[0]) - min(a[2], b[2]) <= gap + 1:
                    parts[i] |= parts.pop(j)
                    joined = True
                    break
            if joined:
                break
    return parts


def _runs(blocks, area: Area, block: int) -> Tuple[Tuple[int, int, int, int], ...]:
    """Squares as screen rectangles, one per run of squares along a row."""
    rows = {}
    for bx, by in blocks:
        rows.setdefault(by, []).append(bx)
    out = []
    for by, xs in sorted(rows.items()):
        xs.sort()
        start = prev = xs[0]
        for bx in xs[1:] + [None]:
            if bx is not None and bx == prev + 1:
                prev = bx
                continue
            x0, x1 = start * block, min(area.w, (prev + 1) * block)
            y0, y1 = by * block, min(area.h, (by + 1) * block)
            out.append((area.x + x0, area.y + y0, x1 - x0, y1 - y0))
            if bx is not None:
                start = prev = bx
    return tuple(out)


def find_tooltips(base: bytes, prev: bytes, cur: bytes, area: Area, block: int = BLOCK):
    """What has appeared near the mouse since ``base`` (the snapshot taken
    when the mouse stopped), nearest the mouse first, as Found; or
    SCREEN_CHANGED. ``prev`` is the snapshot before ``cur``: it must look the
    same in both, so it's only found once it has finished appearing. Usually
    that's one thing, the tooltip; if the game also fades in a highlight on
    the item, that's another."""
    w, h, k = area.w, area.h, max(0.5, area.k)
    step = max(1, int(k))  # at 4K, every other row is plenty
    if base == cur:
        return []
    changed = changed_blocks(base, cur, w, h, block, step)
    total = ((w + block - 1) // block) * ((h + block - 1) // block)
    if len(changed) >= CHANGED_SHARE * total:
        return SCREEN_CHANGED
    moving = changed if prev is base else changed_blocks(prev, cur, w, h, block, step)
    settled = changed - moving
    cx, cy = area.cursor[0] - area.x, area.cursor[1] - area.y
    found: List[Tuple[float, Found]] = []
    for group in _join_lines(groups(settled)):
        bx0, by0, bx1, by1 = _bounds(group)
        box = (bx0 * block, by0 * block, min(w, (bx1 + 1) * block), min(h, (by1 + 1) * block))
        bw, bh = box[2] - box[0], box[3] - box[1]
        if bw < MIN_W * k or bh < MIN_H * k or bh > MAX_H * k:
            continue
        d = _distance((cx, cy), box)
        if d <= REACH * k:
            found.append((d, Found(area.to_screen(box), _runs(group, area, block))))
    return [f for _, f in sorted(found, key=lambda x: x[0])]


def overlaps(a: Box, b: Box) -> bool:
    """Do two boxes mostly cover the same place (more than half the smaller one)?"""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return False
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return w * h * 2 > smaller
