"""Hover price check: when it checks, what it shows, and when it hides."""

import threading
import time
from types import SimpleNamespace

import pytest

from tarkov_display.hover import LEAVE_PX, RETRY_AFTER, HoverWatcher, is_tooltip_match
from tarkov_display.matching import Match
from tarkov_display.profiles import Config, ScanConfig
from tarkov_display.scanner import ItemScanner, ScanResult
from tarkov_display.screen import blank_area

GPU = SimpleNamespace(id="gpu", name="Graphics card", short_name="GPU")
LEDX = SimpleNamespace(id="ledx", name="LEDX Skin Transilluminator", short_name="LEDX")


def tooltip(item=GPU, score=1.0):
    return ScanResult(Match(item, score, item.name, full=True), [item.name])


def grid_label(item=GPU):
    return ScanResult(Match(item, 0.98, item.short_name, full=False), [item.short_name])


NOTHING = ScanResult(None, ["Stash"])


class Rig:
    """A HoverWatcher with a fake mouse, clock and price check."""

    def __init__(self, results=None, scale=1.0):
        self.cfg = ScanConfig(hover=True, hover_delay=0.35)
        self.focused = True
        self.pos = (500, 500)  # None: the pointer is hidden
        self.scale = scale
        self.results = list(results or [])  # what each check returns, in order (then the last again)
        self.scans = 0
        self.shown = []
        self.leaves = 0
        self.t = 0.0
        self.w = HoverWatcher(lambda: self.cfg, lambda: self.focused, self.pointer, self.scan,
                              self.shown.append, self.leave, clock=lambda: self.t)

    def pointer(self):
        return None if self.pos is None else (self.pos[0], self.pos[1], self.scale)

    def scan(self):
        self.scans += 1
        return self.results.pop(0) if len(self.results) > 1 else (self.results[0] if self.results else NOTHING)

    def leave(self):
        self.leaves += 1

    def run(self, seconds, move=(0, 0), dt=0.08):
        for _ in range(int(round(seconds / dt))):
            if move != (0, 0) and self.pos is not None:
                self.pos = (self.pos[0] + move[0], self.pos[1] + move[1])
            self.w.step()
            self.t += dt


def test_checks_once_when_the_mouse_rests_on_an_item():
    r = Rig([tooltip()])
    r.run(0.3)
    assert r.scans == 0  # not yet: the mouse has to stay still a moment
    r.run(0.2)
    assert r.scans == 1 and [x.match.item.id for x in r.shown] == ["gpu"]
    r.run(5)
    assert r.scans == 1 and len(r.shown) == 1  # resting longer doesn't check again
    assert r.w.status == "on"


def test_no_checks_while_the_mouse_moves():
    r = Rig([tooltip()])
    r.run(3, move=(10, 0))
    assert r.scans == 0
    r.run(3, move=(0, 2))  # slow drift still counts as moving
    assert r.scans == 0


def test_looks_again_if_the_tooltip_was_not_up_yet():
    r = Rig([NOTHING, tooltip()])
    r.run(0.5)
    assert r.scans == 1 and not r.shown
    r.run(RETRY_AFTER)
    assert r.scans == 2 and len(r.shown) == 1
    r.run(3)
    assert r.scans == 2


def test_grid_short_names_and_weak_reads_never_pop_up():
    r = Rig([grid_label()])
    r.run(3)
    assert r.scans == 2 and not r.shown  # two looks, then it waits for the mouse to move
    r = Rig([tooltip(score=0.85)])
    r.run(3)
    assert not r.shown


def test_moving_away_hides_the_price_and_the_next_item_is_checked():
    r = Rig([tooltip(GPU), tooltip(LEDX)])
    r.run(0.5)
    assert len(r.shown) == 1 and r.leaves == 0
    r.pos = (500 + LEAVE_PX * 2, 500)
    r.run(0.08)
    assert r.leaves == 1
    r.run(0.5)
    assert [x.match.item.id for x in r.shown] == ["gpu", "ledx"]


def test_a_small_move_keeps_the_price_up_and_checks_again():
    r = Rig([tooltip(GPU)])
    r.run(0.5)
    r.pos = (508, 500)  # moved, but less than LEAVE_PX
    r.run(0.5)
    assert r.leaves == 0 and r.scans == 2 and len(r.shown) == 2  # the app window keeps the same popup up


def test_distances_scale_with_the_screen():
    r = Rig([tooltip()], scale=2.0)  # 4K: the same movement is twice the pixels
    r.run(0.5)
    r.pos = (506, 500)
    r.run(0.5)
    assert r.scans == 1  # 6 px at 4K is still resting


@pytest.mark.parametrize("change, status", [
    (lambda r: setattr(r, "pos", None), "paused: the mouse pointer is hidden"),
    (lambda r: setattr(r, "focused", False), "waiting for Tarkov"),
    (lambda r: setattr(r.cfg, "hover", False), "off"),
])
def test_stops_and_hides_when_not_in_tarkov_menus(change, status):
    r = Rig([tooltip()])
    r.run(0.5)
    assert len(r.shown) == 1
    change(r)
    r.run(3)
    assert r.leaves == 1 and r.scans == 1 and r.w.status.startswith(status)


def test_waits_for_a_running_ctrl_alt_p_check():
    r = Rig()
    busy = [None, tooltip()]
    r.scan = lambda: (setattr(r, "scans", r.scans + 1), busy.pop(0))[1]
    r.w.scan = r.scan
    r.run(0.48)
    assert r.scans == 1 and not r.shown
    r.run(0.08)
    assert r.scans == 2 and len(r.shown) == 1  # tried again on the next look, not 0.6 s later


def test_errors_show_in_the_status_until_a_check_works():
    r = Rig([ScanResult(None, error="No OCR engine found."), tooltip()])
    r.run(0.5)
    assert r.w.status == "can't check prices: No OCR engine found." and not r.shown
    r.run(1)
    assert r.w.status == "on" and len(r.shown) == 1


def test_tooltip_match():
    assert is_tooltip_match(tooltip())
    assert not is_tooltip_match(tooltip(score=0.89))
    assert not is_tooltip_match(grid_label())
    assert not is_tooltip_match(NOTHING)
    assert not is_tooltip_match(None)


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


# -- leaving our own popup out of the capture ------------------------------------


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
    def cursor_pos(self):
        return 1000, 500

    def target_rect(self):
        return 0, 0, 1920, 1080

    def grab(self, x, y, w, h, scale=1):
        self.box = (x, y, w, h, scale)
        return b"\xff" * (w * scale * h * scale * 4), w * scale, h * scale


class FakeOcr:
    max_dimension = 2600

    def read(self, bgra, w, h):
        self.image = (bgra, w, h)
        return []


def test_scanner_blanks_the_masked_box():
    scanner = object.__new__(ItemScanner)
    scanner.prices = SimpleNamespace(items=[SimpleNamespace(name="Graphics card", short_name="GPU", is_preset=False)])
    scanner.cfg = ScanConfig()
    scanner.debug_dir = None
    scanner.screen, scanner.ocr = FakeScreen(), FakeOcr()
    scanner._matcher = scanner._matcher_for = None
    scanner.scan(mask=[(1000, 420, 100, 50)], quiet=True)  # a popup above-right of the cursor
    x, y, w, h, scale = scanner.screen.box
    bgra, iw, ih = scanner.ocr.image

    def pixel(sx, sy):  # screen point -> captured pixel
        i = (((sy - y) * scale) * iw + (sx - x) * scale) * 4
        return bgra[i:i + 4]

    assert pixel(1050, 440) == bytes(4)        # inside the popup: blanked
    assert pixel(1000, 500) == b"\xff" * 4     # at the cursor: kept
    assert pixel(1150, 440) == b"\xff" * 4     # beside the popup: kept


# -- one check at a time ----------------------------------------------------------


def test_scan_now_takes_turns_and_leaves_the_popup_out(webapp):
    app = webapp.app
    calls = []
    app.scanner = SimpleNamespace(scan=lambda mask=(), quiet=False: calls.append((list(mask), quiet)) or NOTHING)
    app.popup_rect = lambda: (1, 2, 3, 4)
    assert app.scan_now(quiet=True) is NOTHING and calls == [([(1, 2, 3, 4)], True)]

    app._scanning.acquire()
    assert app.scan_now() is None  # hover: skip while Ctrl+Alt+P is checking
    threading.Timer(0.2, app._scanning.release).start()
    started = time.monotonic()
    assert app.scan_now(wait=True) is NOTHING  # Ctrl+Alt+P: wait for the hover check
    assert time.monotonic() - started >= 0.15


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
