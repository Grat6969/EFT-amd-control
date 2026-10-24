"""Hover price check: when it looks, what it reads, what it shows, and when it hides."""

import os
import threading
import time
from types import SimpleNamespace

import pytest

from tarkov_display.hover import BOX_READS, LEAVE_PX, LOOK_FOR, HoverWatcher, shows_item
from tarkov_display.matching import Match
from tarkov_display.ocr import OcrUnavailable
from tarkov_display.profiles import Config, ScanConfig
from tarkov_display.scanner import ItemScanner, ScanResult
from tarkov_display.screen import blank_area
from tarkov_display.tooltip import Area, blank_boxes, overlaps

GPU = SimpleNamespace(id="gpu", name="Graphics card", short_name="GPU")
LEDX = SimpleNamespace(id="ledx", name="LEDX Skin Transilluminator", short_name="LEDX")


def named(item=GPU, score=1.0):
    return ScanResult(Match(item, score, item.name, full=True), [item.name])


def grid_label(item=GPU):
    return ScanResult(Match(item, 0.98, item.short_name, full=False), [item.short_name])


NOTHING = ScanResult(None, ["Stash"])
W, H = 680, 180  # the area read around the mouse at 1080p


def background(seed):
    buf = bytearray(W * H * 4)
    for y in range(H):
        for x in range(0, W, 4):
            v = (x * 5 + y * 11 * seed) % 241
            i = (y * W + x) * 4
            buf[i:i + 4] = bytes((v, 255 - v, v // 3, 0))
    return bytes(buf)


BACKGROUNDS = {1: background(1), 2: background(2)}


class Scene:
    """What's on screen: a still stash, plus boxes that show from a given time."""

    def __init__(self):
        self.background = 1
        self.boxes = []      # (screen box, shade, shown from, shown until, what reading it gives)
        self.noise = False

    def add(self, box, start, result=NOTHING, until=float("inf"), shade=40):
        self.boxes.append((box, shade, start, until, result))

    def draw(self, area, t):
        if self.noise:
            return os.urandom(W * H * 4)
        out = bytearray(BACKGROUNDS[self.background])
        for (x0, y0, x1, y1), shade, start, until, _ in self.boxes:
            if not start <= t < until:
                continue
            for y in range(max(0, y0 - area.y), min(H, y1 - area.y)):
                a = (y * W + max(0, x0 - area.x)) * 4
                b = (y * W + min(W, x1 - area.x)) * 4
                out[a:b] = bytes((shade, shade, shade, 0)) * ((b - a) // 4)
        return bytes(out)


class Eyes:
    """Stands in for ScannerEyes: reads the Scene."""

    def __init__(self, rig):
        self.rig = rig
        self.snapshots = 0
        self.reads = []          # boxes read
        self.scans = 0           # full reads
        self.full_read = NOTHING  # what a full read gives
        self.busy = 0            # calls to answer "busy" (None) first
        self.fail = None         # an exception to raise

    def _busy(self):
        if self.fail:
            raise self.fail
        if self.busy:
            self.busy -= 1
            return True
        return False

    def area(self, cursor):
        if self._busy():
            return None
        return Area(cursor[0] - 160, cursor[1] - 90, W, H, tuple(cursor), self.rig.k)

    def snapshot(self, area, mask):
        if self._busy():
            return None
        self.snapshots += 1
        return blank_boxes(self.rig.scene.draw(area, self.rig.t), W, H, (area.x, area.y), mask)

    def read(self, found, area, mask):
        """Like the real reader: everything in the box is read, and a full
        name wins (see ItemMatcher.match_tooltip)."""
        if self._busy():
            return None
        box = found.box
        self.reads.append(box)
        found = [result for b, _, start, until, result in self.rig.scene.boxes
                 if start <= self.rig.t < until and b[0] < box[2] and box[0] < b[2] and b[1] < box[3] and box[1] < b[3]]
        return next((x for x in found if shows_item(x)), NOTHING)

    def scan(self, mask):
        if self._busy():
            return None
        self.scans += 1
        return self.full_read


class Rig:
    """A HoverWatcher with a fake mouse, clock, screen and popup."""

    def __init__(self, k=1.0):
        self.cfg = ScanConfig(hover=True, hover_delay=0.35)
        self.focused = True
        self.pos = (500, 500)  # None: the pointer is hidden
        self.k = k
        self.t = 0.0
        self.scene = Scene()
        self.eyes = Eyes(self)
        self.popup, self.popup_until = None, float("inf")  # our popup's place on screen, while it's up
        self.shown = []
        self.leaves = 0
        self.w = HoverWatcher(lambda: self.cfg, lambda: self.focused, self.pointer, self.eyes,
                              self.shown.append, self.leave, popup_rect=self.popup_rect, clock=lambda: self.t)

    def popup_rect(self):
        return self.popup if self.t < self.popup_until else None

    def pointer(self):
        return None if self.pos is None else (self.pos[0], self.pos[1], self.k)

    def leave(self):
        self.leaves += 1

    def run(self, seconds, move=(0, 0), dt=0.08):
        for _ in range(int(round(seconds / dt))):
            if move != (0, 0) and self.pos is not None:
                self.pos = (self.pos[0] + move[0], self.pos[1] + move[1])
            self.w.step()
            self.t = round(self.t + dt, 6)

    def ids(self):
        return [r.match.item.id for r in self.shown]


TOOLTIP = (515, 512, 655, 536)  # below-right of the mouse at (500, 500)


def test_reads_the_tooltip_once_it_has_appeared():
    r = Rig()
    r.scene.add(TOOLTIP, start=0.6, result=named(GPU))
    r.run(0.6)
    assert r.shown == [] and r.eyes.reads == []  # it isn't up yet: nothing read, nothing guessed
    r.run(0.3)
    assert r.ids() == ["gpu"] and len(r.eyes.reads) == 1 and overlaps(r.eyes.reads[0], TOOLTIP)
    r.run(3)
    assert len(r.shown) == 1 and len(r.eyes.reads) == 1  # resting longer doesn't read it again


def test_a_late_tooltip_is_still_caught():
    r = Rig()
    r.scene.add(TOOLTIP, start=1.3, result=named(GPU))
    r.run(1.6)
    assert r.ids() == ["gpu"]


def test_a_tooltip_already_up_when_the_mouse_stopped():
    r = Rig()
    r.scene.add(TOOLTIP, start=0, result=named(GPU))
    r.eyes.full_read = named(GPU)  # the full read finds its name (not one that can be a grid label)
    r.run(0.5)
    assert r.ids() == ["gpu"] and r.eyes.reads == [] and r.eyes.scans == 1


def test_gives_up_quietly_when_nothing_shows():
    r = Rig()
    r.run(0.35 + LOOK_FOR + 1)
    assert r.shown == [] and r.eyes.reads == [] and r.eyes.scans == 1
    snapshots = r.eyes.snapshots
    r.run(2)
    assert r.eyes.scans == 1 and r.eyes.snapshots <= snapshots + 7  # only a glance now and then


def test_skips_a_box_that_isnt_the_tooltip():
    r = Rig()
    highlight = (470, 470, 533, 533)  # the hovered cell lighting up, with the mouse in it
    tooltip = (560, 550, 700, 574)    # apart from it
    r.scene.add(highlight, start=0.5, result=grid_label(GPU), shade=90)
    r.scene.add(tooltip, start=0.5, result=named(GPU))
    r.run(1.2)
    assert r.ids() == ["gpu"] and len(r.eyes.reads) == 2 and overlaps(r.eyes.reads[0], highlight)


def test_a_tooltip_touching_the_highlight_is_read_with_it():
    r = Rig()
    r.scene.add((470, 470, 533, 533), start=0.5, result=grid_label(GPU), shade=90)
    r.scene.add(TOOLTIP, start=0.5, result=named(GPU))  # overlaps the highlight: one box
    r.run(1.2)
    assert r.ids() == ["gpu"] and len(r.eyes.reads) == 1


def test_stops_after_a_few_boxes_without_a_name():
    r = Rig()
    boxes = [(520, 430, 640, 450), (520, 470, 640, 490), (520, 510, 640, 530), (520, 550, 640, 570),
             (380, 470, 480, 490), (380, 520, 480, 540)]  # e.g. a context menu's lines, one after another
    for i, box in enumerate(boxes):
        r.scene.add(box, start=0.5 + i * 0.2)
    r.run(4)
    assert r.shown == [] and len(r.eyes.reads) == BOX_READS


def test_no_captures_while_the_mouse_moves():
    r = Rig()
    r.scene.add(TOOLTIP, start=0, result=named(GPU))
    r.run(3, move=(10, 0))
    r.run(3, move=(0, 2))  # slow drift still counts as moving
    assert r.eyes.snapshots == 0 and r.eyes.reads == [] and r.eyes.scans == 0


def test_moving_away_hides_the_price_and_the_next_item_is_read():
    r = Rig()
    r.scene.add(TOOLTIP, start=0.4, until=1.0, result=named(GPU))
    r.run(1.0)
    assert r.ids() == ["gpu"] and r.leaves == 0
    r.pos = (500 + LEAVE_PX * 3, 500)
    r.scene.add((563, 512, 760, 536), start=1.5, result=named(LEDX))
    r.run(1.2)
    assert r.leaves == 1 and r.ids() == ["gpu", "ledx"]


def test_a_small_move_keeps_the_price_up():
    r = Rig()
    r.scene.add(TOOLTIP, start=0.4, result=named(GPU))
    r.run(1.0)
    r.pos = (508, 500)  # moved, but less than LEAVE_PX
    r.run(2)
    assert r.leaves == 0 and r.ids() == ["gpu"]


def test_scrolling_under_a_still_mouse_hides_and_reads_again():
    r = Rig()
    r.scene.add(TOOLTIP, start=0.4, until=2.0, result=named(GPU))
    r.run(2.0)
    assert r.ids() == ["gpu"]
    r.scene.background = 2  # the stash scrolled: something else is under the mouse now
    r.scene.add(TOOLTIP, start=2.6, result=named(LEDX), shade=60)
    r.run(1.6)
    assert r.leaves == 1 and r.ids() == ["gpu", "ledx"]


def test_moving_scenery_gets_one_full_read():
    r = Rig()
    r.scene.noise = True
    r.eyes.full_read = named(GPU)
    r.run(3)
    assert r.eyes.reads == [] and r.eyes.scans == 1 and r.ids() == ["gpu"]


def test_our_own_popup_appearing_isnt_mistaken_for_a_tooltip():
    r = Rig()
    popup = (530, 380, 730, 470)  # above-right of the mouse, partly inside the area
    r.scene.add(popup, start=0.6, shade=200)
    r.run(0.6)
    r.popup = (popup[0], popup[1], popup[2] - popup[0], popup[3] - popup[1])  # it's ours: left out
    r.run(1.5)
    assert r.eyes.reads == [] and r.shown == []


@pytest.mark.parametrize("change, status", [
    (lambda r: setattr(r, "pos", None), "paused: the mouse pointer is hidden"),
    (lambda r: setattr(r, "focused", False), "waiting for Tarkov"),
    (lambda r: setattr(r.cfg, "hover", False), "off"),
])
def test_stops_and_hides_when_not_in_tarkov_menus(change, status):
    r = Rig()
    r.scene.add(TOOLTIP, start=0.4, result=named(GPU))
    r.run(1.0)
    assert len(r.shown) == 1
    change(r)
    snapshots = r.eyes.snapshots
    r.run(2)
    assert r.leaves == 1 and r.eyes.snapshots == snapshots and r.w.status.startswith(status)


def test_waits_its_turn_when_the_screen_reader_is_busy():
    r = Rig()
    r.scene.add(TOOLTIP, start=0.7, result=named(GPU))
    r.eyes.busy = 3  # Ctrl+Alt+P is reading
    r.run(1.6)
    assert r.ids() == ["gpu"]


TOOLSET = SimpleNamespace(id="toolset", name="Toolset", short_name="Toolset")


def test_the_last_tooltip_fading_out_isnt_read_as_this_one():
    r = Rig()
    label = (430, 470, 490, 486)  # a neighbour's grid label: "Toolset", which is also a full name
    r.scene.add(label, start=0, result=named(TOOLSET), shade=120)
    old = (420, 462, 560, 492)    # the last item's tooltip, on top of it, fading out
    r.scene.add(old, start=0, until=0.12, shade=40)
    r.scene.add(old, start=0.12, until=0.2, shade=25)
    r.scene.add(TOOLTIP, start=0.7, result=named(GPU))
    r.run(1.6)
    assert r.ids() == ["gpu"] and len(r.eyes.reads) == 1 and overlaps(r.eyes.reads[0], TOOLTIP)


def test_waits_for_the_last_popup_to_go_before_looking():
    r = Rig()
    old_popup = (505, 505, 700, 560)  # our popup for the last item, where this one's tooltip will show
    r.scene.add(old_popup, start=0, until=0.25, shade=200)
    r.popup, r.popup_until = (505, 505, 195, 55), 0.25
    r.scene.add(TOOLTIP, start=0.7, result=named(GPU))
    r.run(1.6)
    assert r.ids() == ["gpu"]


def test_errors_show_in_the_status_until_a_check_works():
    r = Rig()
    r.eyes.fail = OcrUnavailable("No OCR engine found.")
    r.run(1)
    assert r.w.status == "can't check prices: No OCR engine found." and r.shown == []
    r.eyes.fail = None
    r.scene.add(TOOLTIP, start=1.5, result=named(GPU))
    r.pos = (501, 540)  # it tries again once the mouse moves
    r.run(1.5)
    assert r.w.status == "on" and r.ids() == ["gpu"]


def test_distances_scale_with_the_screen():
    r = Rig(k=2.0)  # 4K: the same movement is twice the pixels
    r.scene.add(TOOLTIP, start=0.4, result=named(GPU))
    r.run(1.0)
    r.pos = (506, 500)
    r.run(1)
    assert len(r.eyes.reads) == 1  # 6 px at 4K is still the same spot


def test_shows_item():
    assert shows_item(named())
    assert not shows_item(grid_label())
    assert not shows_item(NOTHING)
    assert not shows_item(None)


def test_thread_starts_and_stops():
    r = Rig()
    r.cfg.hover = False
    r.w.start()
    time.sleep(0.05)
    r.w.stop()
    assert r.w.status == "off" and r.w._thread is None


def test_settings_round_trip():
    cfg = Config.from_dict({"scan": {"hover": True, "hover_delay": 0.5}})
    assert cfg.scan.hover is True and cfg.scan.hover_delay == 0.5
    assert Config.from_dict(cfg.to_dict()).scan.hover is True
    bad = Config.from_dict({"scan": {"hover": "yes", "hover_delay": "soon"}})
    assert bad.scan.hover is False and bad.scan.hover_delay == 0.35


# -- the scanner's side --------------------------------------------------------------


def test_blank_area():
    w, h = 4, 3
    img = bytes(range(1, w * h * 4 + 1))
    out = blank_area(img, w, h, 1, 1, 3, 2)
    for y in range(h):
        for x in range(w):
            px = out[(y * w + x) * 4:(y * w + x) * 4 + 4]
            inside = 1 <= x < 3 and y == 1
            assert (px == bytes(4)) == inside
    assert blank_area(img, w, h, 5, 5, 9, 9) is img        # off the image
    assert blank_area(img, w, h, -5, -5, 99, 99) == bytes(len(img))  # clipped to it


class FakeScreen:
    def __init__(self):
        self.grabs = []

    def cursor_pos(self):
        return 1000, 500

    def target_rect(self):
        return 0, 0, 1920, 1080

    def grab(self, x, y, w, h, scale=1):
        self.grabs.append((x, y, w, h, scale))
        return b"\xff" * (w * scale * h * scale * 4), w * scale, h * scale


class FakeOcr:
    max_dimension = 2600

    def __init__(self, lines=()):
        self.lines = list(lines)

    def read(self, bgra, w, h):
        self.image = (bgra, w, h)
        return list(self.lines)


def scanner_with(lines=(), items=None):
    from tarkov_display.ocr import OcrLine

    scanner = object.__new__(ItemScanner)
    items = items or [SimpleNamespace(id="gpu", name="Graphics card", short_name="GPU", is_preset=False),
                      SimpleNamespace(id="toolset", name="Toolset", short_name="Toolset", is_preset=False)]
    scanner.prices = SimpleNamespace(items=items)
    scanner.cfg = ScanConfig()
    scanner.debug_dir = None
    scanner.screen, scanner.ocr = FakeScreen(), FakeOcr([OcrLine(t, 10, 10) for t in lines])
    scanner._matcher = scanner._matcher_for = None
    return scanner


def test_scanner_blanks_the_masked_box():
    scanner = scanner_with()
    scanner.scan(mask=[(1000, 420, 100, 50)], quiet=True)  # a popup above-right of the cursor
    x, y, w, h, scale = scanner.screen.grabs[-1]
    bgra, iw, ih = scanner.ocr.image

    def pixel(sx, sy):  # screen point -> captured pixel
        i = (((sy - y) * scale) * iw + (sx - x) * scale) * 4
        return bgra[i:i + 4]

    assert pixel(1050, 440) == bytes(4)        # inside the popup: blanked
    assert pixel(1000, 500) == b"\xff" * 4     # at the cursor: kept
    assert pixel(1150, 440) == b"\xff" * 4     # beside the popup: kept


def test_scanner_reads_just_the_tooltip_box():
    scanner = scanner_with(["Graphlcs card"])  # slightly misread
    result = scanner.read_tooltip((1015, 512, 1155, 536), (1000, 500))
    assert result.match.item.id == "gpu"
    x, y, w, h, scale = scanner.screen.grabs[-1]
    assert (x, y, w, h, scale) == (1009, 506, 152, 36, 3)  # the box plus a small margin, enlarged 3x
    assert scanner_with(["GPU"]).read_tooltip((1015, 512, 1155, 536), (1000, 500)).match is None


def test_scanner_reads_only_the_parts_that_changed():
    scanner = scanner_with(["Graphics card"])
    scanner.read_tooltip((1015, 512, 1155, 536), (1000, 500), keep=[(1015, 512, 140, 24)])
    bgra, iw, ih = scanner.ocr.image
    px = lambda x, y: bgra[(y * iw + x) * 4:(y * iw + x) * 4 + 4]
    assert px(0, 0) == bytes(4)              # the margin around it: nothing changed there, left out
    assert px(iw // 2, ih // 2) == b"\xff" * 4  # the tooltip itself: read


def test_strict_full_reads_ignore_possible_grid_labels():
    assert scanner_with(["Toolset"]).scan(strict=True).match is None
    assert scanner_with(["Toolset"]).scan().match.item.id == "toolset"
    assert scanner_with(["Graphics card"]).scan(strict=True).match.item.id == "gpu"


def test_snapshots_and_areas():
    scanner = scanner_with()
    area = scanner.area_at((1000, 500))
    assert (area.x, area.y, area.w, area.h, area.cursor, area.k) == (840, 410, 680, 180, (1000, 500), 1.0)
    snap = scanner.snapshot(area, [(840, 410, 10, 10)])
    assert scanner.screen.grabs[-1] == (840, 410, 680, 180, 1)
    assert snap[:4] == bytes(4) and snap[-4:] == b"\xff" * 4


# -- one use of the screen reader at a time ----------------------------------------


def test_use_scanner_takes_turns_and_scan_now_leaves_the_popup_out(webapp):
    app = webapp.app
    calls = []
    app.scanner = SimpleNamespace(scan=lambda mask=(), quiet=False: calls.append((list(mask), quiet)) or NOTHING)
    app.popup_rect = lambda: (1, 2, 3, 4)
    assert app.scan_now(quiet=True) is NOTHING and calls == [([(1, 2, 3, 4)], True)]

    app._scanning.acquire()
    assert app.scan_now() is None  # hover: skip while Ctrl+Alt+P is checking
    assert app.use_scanner(lambda s: "used") is None
    threading.Timer(0.2, app._scanning.release).start()
    started = time.monotonic()
    assert app.scan_now(wait=True) is NOTHING  # Ctrl+Alt+P: wait for the hover check
    assert time.monotonic() - started >= 0.15

    def boom(scanner):
        raise OcrUnavailable("No OCR engine found.")

    with pytest.raises(OcrUnavailable):
        app.use_scanner(boom)
    app.scanner = SimpleNamespace(scan=lambda mask=(), quiet=False: boom(None))
    assert app.scan_now().error == "No OCR engine found."


# -- the app window's side ----------------------------------------------------------


class FakePopup:
    def __init__(self):
        self.shown, self.hidden, self.rect = [], 0, None

    def show(self, title, subtitle, rows, notes, footer, cursor, seconds):
        self.shown.append((title, seconds))
        self.rect = (10, 10, 100, 50)

    def hide_soon(self):
        self.hidden += 1
        self.rect = None


def test_hover_results_in_the_app(webapp, monkeypatch):
    popup = webapp.popup = FakePopup()
    events = []
    monkeypatch.setattr(webapp, "publish", lambda event, data: events.append((event, data)))
    monkeypatch.setattr(webapp, "item_needs", lambda item_id, limit=6: [])
    gpu = next(i for i in webapp.app.prices.items if i.name)

    def result(item):
        return ScanResult(Match(item, 1.0, item.name, full=True), [item.name], (500, 500))

    webapp._hover_result(result(gpu))
    webapp._hover_result(result(gpu))  # the mouse moved a little over the same item
    assert popup.shown == [(gpu.name, 60)]
    scans = [d for e, d in events if e == "scan"]
    assert len(scans) == 1 and scans[0]["auto"] is True and scans[0]["item"]["id"] == gpu.id

    webapp._hover_leave()
    webapp._hover_leave()
    assert popup.hidden == 1

    webapp._hover_toggled(False)  # Ctrl+Alt+H
    assert popup.shown[-1][0] == "Hover price check off"
    assert any(e == "display" for e, _ in events)
    webapp._hover_leave()  # must not hide the "off" notice
    assert popup.hidden == 1
    assert webapp._popup_rect() == (6, 6, 108, 58)


def test_hover_settings_and_status(webapp):
    from tests.test_server import body, call

    s = webapp.server
    state = body(call(s, "/api/display", "POST", {"op": "scan", "settings": {"hover": True, "hover_delay": 9}}))
    assert state["scan"]["hover"] is True and state["scan"]["hover_delay"] == 2.0
    state = body(call(s, "/api/display", "POST", {"op": "scan", "settings": {"hover_delay": 0}}))
    assert state["scan"]["hover_delay"] == 0.15
    assert body(call(s, "/api/state"))["hover"] == {"enabled": True, "status": "unavailable on this PC"}
    body(call(s, "/api/display", "POST", {"op": "scan", "settings": {"hover": False}}))
    assert body(call(s, "/api/state"))["hover"] == {"enabled": False, "status": "off"}
