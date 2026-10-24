"""Telling Tarkov's tooltip apart from everything else around the mouse."""

import os
from types import SimpleNamespace

from tarkov_display.matching import ItemMatcher, candidate_lines
from tarkov_display.ocr import OcrLine, order_by_distance
from tarkov_display.tooltip import (SCREEN_CHANGED, Area, blank_boxes, changed_blocks, changed_share, find_tooltips,
                                    groups, keep_only, overlaps)

W, H = 680, 180
AREA = Area(340, 410, W, H, (500, 500), 1.0)  # the mouse at (500, 500), 160 px from the area's left


def stash(seed=1):
    """A busy, still background (stripes and dots), as top-down BGRA."""
    buf = bytearray(W * H * 4)
    for y in range(H):
        for x in range(0, W, 3):
            v = (x * 7 + y * 13 * seed) % 251
            i = (y * W + x) * 4
            buf[i:i + 4] = bytes((v, v // 2, 255 - v, 0))
    return bytes(buf)


def draw(img, box, shade=40):
    """``img`` with a filled screen box (left, top, right, bottom) on it."""
    x0, y0, x1, y1 = box
    out = bytearray(img)
    for y in range(max(0, y0 - AREA.y), min(H, y1 - AREA.y)):
        a = (y * W + max(0, x0 - AREA.x)) * 4
        b = (y * W + min(W, x1 - AREA.x)) * 4
        out[a:b] = bytes((shade, shade, shade, 0)) * ((b - a) // 4)
    return bytes(out)


BASE = stash()
TOOLTIP = (515, 512, 655, 536)  # just below-right of the mouse, 140 x 24


def test_a_settled_tooltip_is_found():
    cur = draw(BASE, TOOLTIP)
    found = find_tooltips(BASE, cur, cur, AREA)
    assert len(found) == 1 and overlaps(found[0].box, TOOLTIP)
    box = found[0].box
    assert box[0] <= TOOLTIP[0] and box[2] >= TOOLTIP[2]  # whole squares around it
    covered = sum(w * h for _, _, w, h in found[0].keep)
    assert covered == (box[2] - box[0]) * (box[3] - box[1])  # all of it changed


def test_only_what_changed_is_kept_for_reading():
    highlight = (470, 470, 533, 533)  # the hovered cell lights up...
    cur = draw(draw(BASE, highlight, 90), TOOLTIP)  # ... and the tooltip touches it: one box
    found = find_tooltips(BASE, cur, cur, AREA)
    assert len(found) == 1
    x0, y0, x1, y1 = found[0].box
    assert x0 <= highlight[0] and x1 >= TOOLTIP[2]
    neighbour_label = (x1 - 30, y0 + 2)  # inside the box's outline, but nothing changed there

    def kept(x, y):
        return any(rx <= x < rx + rw and ry <= y < ry + rh for rx, ry, rw, rh in found[0].keep)

    assert not kept(*neighbour_label)
    assert kept(500, 500) and kept(600, 524)


def test_a_tooltip_in_pieces_is_joined():
    left, right = (515, 512, 560, 536), (578, 512, 640, 536)  # 18 px apart on the same line
    cur = draw(draw(BASE, left), right)
    found = find_tooltips(BASE, cur, cur, AREA)
    assert len(found) == 1 and found[0].box[0] <= 515 and found[0].box[2] >= 640


def test_a_tooltip_still_appearing_is_not_read_yet():
    fading = draw(BASE, TOOLTIP, shade=20)
    cur = draw(BASE, TOOLTIP, shade=40)
    assert find_tooltips(BASE, fading, cur, AREA) == []  # changed since the last look: wait
    assert find_tooltips(BASE, BASE, cur, AREA) == []      # first look after it appeared: wait
    assert find_tooltips(BASE, cur, cur, AREA)               # the same twice: read it


def test_nothing_changed_and_the_whole_screen_changed():
    assert find_tooltips(BASE, BASE, BASE, AREA) == []
    other = stash(seed=5)  # scrolled
    assert find_tooltips(BASE, other, other, AREA) == SCREEN_CHANGED
    assert changed_share(BASE, BASE, AREA) == 0 and changed_share(BASE, other, AREA) > 0.9


def test_boxes_that_cant_be_the_tooltip_are_ignored():
    for box in [(520, 512, 528, 536),   # too narrow
                (515, 420, 655, 589),   # too tall
                (900, 512, 1000, 536)]:  # too far from the mouse
        cur = draw(BASE, box)
        assert find_tooltips(BASE, cur, cur, AREA) == [], box


def test_nearest_box_first():
    highlight = (470, 470, 533, 533)  # the hovered cell, with the mouse in it
    far_tooltip = (560, 545, 700, 569)
    cur = draw(draw(BASE, far_tooltip), highlight, shade=90)
    found = find_tooltips(BASE, cur, cur, AREA)
    assert len(found) == 2 and overlaps(found[0].box, highlight) and overlaps(found[1].box, far_tooltip)


def test_moving_scenery_is_not_a_tooltip():
    noisy = (380, 430, 470, 470)  # e.g. a 3D view that keeps moving
    a = draw(BASE, noisy, 10)
    b = draw(draw(BASE, noisy, 70), TOOLTIP)
    c = draw(draw(BASE, noisy, 130), TOOLTIP)
    found = find_tooltips(BASE, b, c, AREA)
    assert len(found) == 1 and overlaps(found[0].box, TOOLTIP)
    assert find_tooltips(BASE, a, b, AREA) == []


def test_changed_blocks_and_groups():
    a = bytes(16 * 16 * 4)
    b = bytearray(a)
    b[(3 * 16 + 3) * 4] = 9      # square (0, 0)
    b[(12 * 16 + 12) * 4] = 9    # square (1, 1)
    blocks = changed_blocks(a, bytes(b), 16, 16, block=8)
    assert blocks == {(0, 0), (1, 1)}
    assert len(groups(blocks)) == 1  # diagonal neighbours touch
    assert len(groups({(0, 0), (5, 5)})) == 2


def test_blank_boxes():
    img = bytes([200]) * (W * H * 4)
    out = blank_boxes(img, W, H, (AREA.x, AREA.y), [(AREA.x + 10, AREA.y + 5, 20, 10)])
    px = lambda x, y: out[(y * W + x) * 4:(y * W + x) * 4 + 4]
    assert px(15, 10) == bytes(4) and px(5, 10) == bytes([200]) * 4 and px(15, 20) == bytes([200]) * 4
    big = blank_boxes(img, W * 2, H * 2, (AREA.x, AREA.y), [(AREA.x + 10, AREA.y + 5, 20, 10)], scale=2)
    assert big[((10 * 2) * W * 2 + 15 * 2) * 4] == 0


def test_keep_only():
    img = bytes([200]) * (W * H * 4)
    out = keep_only(img, W, H, (AREA.x, AREA.y), [(AREA.x + 10, AREA.y + 5, 20, 10)])
    px = lambda x, y: out[(y * W + x) * 4:(y * W + x) * 4 + 4]
    assert px(15, 10) == bytes([200]) * 4 and px(5, 10) == bytes(4) and px(15, 20) == bytes(4)


def test_overlaps():
    assert overlaps((0, 0, 10, 10), (2, 2, 12, 12))
    assert not overlaps((0, 0, 10, 10), (8, 8, 20, 20))
    assert not overlaps((0, 0, 10, 10), (20, 20, 30, 30))


# -- names that are also grid labels -------------------------------------------------


def item(id, name, short):
    return SimpleNamespace(id=id, name=name, short_name=short, is_preset=False)


ITEMS = [item("gpu", "Graphics card", "GPU"), item("toolset", "Toolset", "Toolset"), item("bolts", "Bolts", "Bolts"),
         item("pliers", "Pliers", "Pliers"), item("salewa", "Salewa first aid kit", "Salewa"),
         item("ledx", "LEDX Skin Transilluminator", "LEDX")]
CURSOR = (400, 300)
STASH = [  # what OCR reads around the mouse in the stash
    OcrLine("GPU", 440, 262),            # the hovered item's own grid label
    OcrLine("Toolset", 372, 326),        # the neighbour below-left: its label is right by the mouse
    OcrLine("Bolts Pliers", 560, 262),   # two more labels, read as one line
]
TIP = OcrLine("Graphics card", 470, 322)  # the game's tooltip


def texts(lines):
    return candidate_lines([l.text for l in order_by_distance(lines, *CURSOR)])


def test_a_neighbours_label_doesnt_beat_the_tooltip():
    m = ItemMatcher(ITEMS)
    assert m.match_lines(texts(STASH + [TIP])).item.id == "gpu"
    assert m.match_lines(texts(STASH + [TIP]), strict=True).item.id == "gpu"


def test_strict_reads_ignore_names_that_can_be_grid_labels():
    m = ItemMatcher(ITEMS)
    assert m.match_lines(texts(STASH), strict=True) is None   # before the tooltip shows: nothing
    assert m.match_lines(texts(STASH)).item.id == "toolset"   # Ctrl+Alt+P still gives its best guess


def test_reading_the_tooltip_box():
    m = ItemMatcher(ITEMS)
    assert m.match_tooltip(["Graphics card"]).item.id == "gpu"
    assert m.match_tooltip(["Graphlcs card"]).item.id == "gpu"   # misread, still the tooltip
    assert m.match_tooltip(["Toolset"]).item.id == "toolset"     # a same-name item's tooltip counts here
    assert m.match_tooltip(["GPU"]) is None                      # a short name isn't a tooltip
    assert m.match_tooltip(["Inspect", "Discard"]) is None       # e.g. a context menu
    assert m.match_tooltip([]) is None


def test_random_bytes_never_crash():
    a, b = os.urandom(W * H * 4), os.urandom(W * H * 4)
    assert find_tooltips(a, b, b, AREA) == SCREEN_CHANGED
