"""Hover price check: the price of the item the mouse rests on (off unless
you turn it on, in the app or with Ctrl+Alt+H).

While a Tarkov window is focused and the mouse pointer is showing (the game
hides it while you play a raid, and shows it in menus and the inventory),
each time the pointer stops over something the app looks for the game's
item tooltip and reads the name in it, with Windows' text recognition.

Text alone can't tell the tooltip from the names printed on the grid (many
short names, like Toolset or Bolts, are also full names, and a neighbour's
label can be nearer the mouse than the tooltip). So the app snapshots the
area around the pointer as soon as it stops and watches for a box that
appears near the pointer and settles: that's the tooltip, wherever the game
draws it and however long it takes (see tooltip.py). Only that box is read.
If no box appears, one full read accepts only a full name that can't be a
grid label. Moving the mouse away, or scrolling the stash under it, hides
the price again.
"""

from __future__ import annotations

import ctypes
import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from .profiles import ScanConfig
from .tooltip import (CHANGED_SHARE, SCREEN_CHANGED, Area, Box, Found, blank_boxes, changed_share, find_tooltips,
                      overlaps)

log = logging.getLogger(__name__)

Pointer = Tuple[int, int, float]  # x, y, and the game window's height / 1080 (to scale distances)

POLL = 0.08          # seconds between looks at the pointer while on
IDLE_POLL = 0.5      # ... and while off
STILL_PX = 4         # the pointer counts as resting while it moves less than this (at 1080p)
STEADY_PX = 1        # ... and as stopped (for the first snapshot) if it moved no more than this since the last look
LEAVE_PX = 16        # moving this far from where a price was shown hides it
LOOK_FOR = 1.2       # after the wait, how long to watch for the tooltip at one spot
BOX_READS = 4        # boxes read at one spot without finding a name, before giving up there
RESTARTS = 4         # screen changes at one spot before treating it as moving scenery
RECHECK_EVERY = 4    # once done at a spot, glance at it every this many looks (in case it scrolls)
STILL_TRIES = 3      # snapshots to wait for the screen to be still before the first one counts
POPUP_GONE_WAIT = 0.4  # seconds to wait for the last item's popup to go before looking
CURSOR_SHOWING = 0x1


def shows_item(result) -> bool:
    """Did a check name an item from its full name (which only the tooltip shows)?
    The scanner decides how sure it has to be (see matching.py)."""
    match = getattr(result, "match", None)
    return bool(match and match.full)


def _far(a, b, limit: float) -> bool:
    return math.hypot(a[0] - b[0], a[1] - b[1]) > limit


@dataclass
class Rest:
    """The mouse resting at one spot, and what's been seen there."""

    anchor: Tuple[int, int]
    since: float
    area: Optional[Area] = None
    base: Optional[bytes] = None   # snapshot taken as soon as the mouse stopped
    prev: Optional[bytes] = None   # the latest snapshot
    masks: List[tuple] = field(default_factory=list)  # our popups, left out of every snapshot
    tried: List[Box] = field(default_factory=list)    # boxes read without finding a name
    early_read: bool = False       # the full read for a tooltip that was up before the mouse stopped
    stilling: int = 0              # snapshots taken waiting for the screen to be still
    restarts: int = 0
    looks: int = 0
    done: bool = False


class ScannerEyes:
    """What hover price check needs from the price-check scanner (scanner.py).
    Each call returns None while another check is using the screen reader."""

    def __init__(self, use: Callable) -> None:
        self.use = use  # App.use_scanner

    def area(self, cursor):
        return self.use(lambda s: s.area_at(cursor))

    def snapshot(self, area: Area, mask):
        return self.use(lambda s: s.snapshot(area, mask))

    def read(self, found: Found, area: Area, mask):
        return self.use(lambda s: s.read_tooltip(found.box, area.cursor, area.k, mask, found.keep))

    def scan(self, mask):
        return self.use(lambda s: s.scan(mask=mask, quiet=True, strict=True))


class HoverWatcher:
    """Watches the pointer and checks the item it rests on (see the module docs).

    ``eyes`` reads the screen (ScannerEyes). ``on_result`` gets checks that
    named an item; ``on_leave`` is called when the price shown should go
    away. ``popup_rect`` gives our popup's place on screen, if one is up.
    """

    def __init__(
        self,
        cfg: Callable[[], ScanConfig],
        game_focused: Callable[[], bool],
        pointer: Callable[[], Optional[Pointer]],
        eyes,
        on_result: Callable[[object], None],
        on_leave: Callable[[], None],
        popup_rect: Callable[[], Optional[tuple]] = lambda: None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cfg = cfg
        self.game_focused = game_focused
        self.pointer = pointer
        self.eyes = eyes
        self.on_result = on_result
        self.on_leave = on_leave
        self.popup_rect = popup_rect
        self.clock = clock
        self.status = "off"
        self.error: Optional[str] = None
        self.rest: Optional[Rest] = None
        self.shown_at: Optional[Tuple[int, int]] = None
        self._last: Optional[Tuple[int, int]] = None  # the pointer at the last look
        self._logged: Optional[str] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- one look ---------------------------------------------------------------

    def step(self) -> None:
        """Look at the pointer once, and at the screen if it's resting."""
        cfg = self.cfg()
        if not cfg.hover:
            return self._idle("off")
        if not self.game_focused():
            return self._idle("waiting for Tarkov to be the focused window")
        p = self.pointer()
        if p is None:
            return self._idle("paused: the mouse pointer is hidden (in raid) or outside Tarkov")
        x, y, k = p
        k = max(1.0, k)
        now = self.clock()
        self._set_on()
        steady = self._last is not None and not _far((x, y), self._last, STEADY_PX * k)
        self._last = (x, y)
        if self.rest is None or _far((x, y), self.rest.anchor, STILL_PX * k):
            self.rest = Rest((x, y), now)
        if self.shown_at is not None and _far((x, y), self.shown_at, LEAVE_PX * k):
            self._leave()
        rest = self.rest
        try:
            self._look(rest, cfg, now, steady)
        except Exception as exc:  # e.g. no text reader installed: say so, try again after the mouse moves
            rest.done = True
            self.error = str(exc) or type(exc).__name__
            self._set_on()
            if self.error != self._logged:
                log.warning("Hover price check: %s", self.error, exc_info=True)
                self._logged = self.error

    def _look(self, rest: Rest, cfg: ScanConfig, now: float, steady: bool = True) -> None:
        eyes = self.eyes
        rest.looks += 1
        if rest.done:
            if rest.base is not None and rest.looks % RECHECK_EVERY == 0:
                self._recheck(rest, now)
            return
        if rest.base is None and not steady:
            return  # the mouse may still be moving: nothing is captured until it stops
        if (rest.base is None and self.shown_at is None and self.popup_rect()
                and now - rest.since < POPUP_GONE_WAIT):
            return  # the last item's popup is on its way out: don't let it hide this one's tooltip
        if rest.area is None:
            rest.area = eyes.area(rest.anchor)
            if rest.area is None:
                return
        self._update_masks(rest)
        if rest.base is None:
            # The first snapshot, as soon as the mouse stops, before the
            # tooltip shows; but once the screen is still (the last item's
            # tooltip may still be fading out: that going isn't this one coming).
            snap = eyes.snapshot(rest.area, rest.masks)
            if snap is None:
                return
            if rest.prev is not None and (snap == rest.prev or rest.stilling >= STILL_TRIES):
                rest.base = rest.prev = snap
            else:
                rest.prev = snap
                rest.stilling += 1
            return
        if now < rest.since + cfg.hover_delay:
            return
        cur = eyes.snapshot(rest.area, rest.masks)
        if cur is None:
            return
        boxes = find_tooltips(rest.base, rest.prev, cur, rest.area)
        rest.prev = cur
        if boxes == SCREEN_CHANGED:
            rest.restarts += 1
            if rest.restarts < RESTARTS:
                return self._restart(rest, cur, now)
            # It keeps changing (moving scenery behind the inventory?): one full read.
            result = eyes.scan(rest.masks)
            if result is not None:
                self._result(rest, result)
                rest.done = True
            return
        found = next((f for f in boxes if not any(overlaps(f.box, t) for t in rest.tried)), None)
        if found is not None:
            result = eyes.read(found, rest.area, rest.masks)
            if result is None:
                return
            rest.tried.append(found.box)
            log.debug("Hover: tooltip box %s read %s", found.box, result.lines)
            self._result(rest, result)
            if len(rest.tried) >= BOX_READS:
                rest.done = True
            return
        unchanged = cur == rest.base
        if not rest.early_read and unchanged:
            # Nothing has appeared: the tooltip may have been up before the
            # mouse even stopped. A full read, trusting only names that can't
            # be grid labels.
            result = eyes.scan(rest.masks)
            if result is not None:
                rest.early_read = True
                self._result(rest, result)
            return
        if now >= rest.since + cfg.hover_delay + LOOK_FOR:
            if not unchanged:  # something showed but never settled: one last full read
                result = eyes.scan(rest.masks)
                if result is None:
                    return
                self._result(rest, result)
            rest.done = True

    def _result(self, rest: Rest, result) -> None:
        self.error = getattr(result, "error", None)
        self._set_on()
        if shows_item(result):
            rest.done = True
            self.shown_at = rest.anchor
            self.on_result(result)

    def _restart(self, rest: Rest, cur: bytes, now: float) -> None:
        """The screen under the mouse changed (the stash scrolled, a window
        opened...): what's under it now may be something else."""
        rest.base = rest.prev = cur
        rest.since, rest.tried, rest.early_read, rest.done = now, [], False, False
        if self.shown_at is not None:
            self._leave()

    def _recheck(self, rest: Rest, now: float) -> None:
        self._update_masks(rest)
        cur = self.eyes.snapshot(rest.area, rest.masks)
        if cur is not None and changed_share(rest.base, cur, rest.area) >= CHANGED_SHARE:
            rest.restarts = 0
            self._restart(rest, cur, now)

    def _update_masks(self, rest: Rest) -> None:
        """Leave our popup out of every snapshot at this spot, earlier ones too,
        so its showing or hiding doesn't look like something appearing."""
        r = self.popup_rect()
        if not r or r in rest.masks:
            return
        rest.masks.append(r)
        a = rest.area
        if a is not None and rest.base is not None:
            same = rest.prev is rest.base
            rest.base = blank_boxes(rest.base, a.w, a.h, (a.x, a.y), [r])
            rest.prev = rest.base if same else blank_boxes(rest.prev, a.w, a.h, (a.x, a.y), [r])

    # -- state ------------------------------------------------------------------

    def _set_on(self) -> None:
        # The last check's error (say, no text reader installed) stays up
        # until a check works.
        self.status = f"can't check prices: {self.error}" if self.error else "on"

    def forget(self) -> None:
        """No price is showing any more (it was hidden or replaced)."""
        self.shown_at = None

    def _leave(self) -> None:
        self.forget()
        self.on_leave()

    def _idle(self, status: str) -> None:
        self.status = status
        self.rest = self._last = None
        if self.shown_at is not None:
            self._leave()

    def run(self) -> None:
        error = None
        while not self._stop.is_set():
            try:
                self.step()
                error = None
            except Exception as exc:  # keep watching; log each new problem once
                if str(exc) != error:
                    log.warning("Hover price check failed: %s", exc, exc_info=True)
                error = str(exc)
            self._stop.wait(POLL if self.cfg().hover else IDLE_POLL)

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self.run, name="HoverPriceCheck", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None


class GameFocus:
    """Is a Tarkov window the focused one? Cheap enough to ask many times a
    second: the list of game processes is only refreshed every few seconds."""

    def __init__(self, names: Callable[[], list], refresh: float = 3.0) -> None:
        self.names = names
        self.refresh = refresh
        self._pids: set = set()
        self._at = -1e9

    def __call__(self) -> bool:
        from .winproc import find_pids, foreground_pid

        now = time.monotonic()
        if now - self._at > self.refresh:
            self._pids, self._at = find_pids(self.names()), now
        return bool(self._pids) and foreground_pid() in self._pids


def win_pointer() -> Callable[[], Optional[Pointer]]:
    """A function that returns the mouse pointer's position while it is
    showing over the focused window, else None (Windows only)."""
    from ctypes import wintypes

    from .screen import ScreenSampler

    class CURSORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                    ("hCursor", wintypes.HANDLE), ("ptScreenPos", wintypes.POINT)]

    user32 = ctypes.windll.user32
    user32.GetCursorInfo.argtypes = [ctypes.POINTER(CURSORINFO)]
    sampler = ScreenSampler()

    def pointer() -> Optional[Pointer]:
        info = CURSORINFO()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetCursorInfo(ctypes.byref(info)) or not info.flags & CURSOR_SHOWING:
            return None
        x, y = info.ptScreenPos.x, info.ptScreenPos.y
        left, top, width, height = sampler.target_rect()
        if not (left <= x < left + width and top <= y < top + height):
            return None  # e.g. on another monitor while the game keeps the focus
        return x, y, height / 1080.0

    return pointer
