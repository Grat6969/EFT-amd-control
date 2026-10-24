"""Hover price check: the price of the item the mouse rests on (off unless
you turn it on, in the app or with Ctrl+Alt+H).

While a Tarkov window is focused and the mouse pointer is showing (the game
hides it while you play a raid, and shows it in menus and the inventory),
each time the pointer stops over something for a moment the app runs the
same price check as Ctrl+Alt+P: one screenshot around the pointer, read
with Windows' text recognition. A price is shown only when an item's full
name was read, which only the game's hover tooltip shows, so menu text and
the short names printed on the grid don't pop anything up. Moving the mouse
away hides the price again.
"""

from __future__ import annotations

import ctypes
import logging
import math
import threading
import time
from typing import Callable, Optional, Tuple

from .matching import FULL_NAME_SCORE
from .profiles import ScanConfig

log = logging.getLogger(__name__)

Pointer = Tuple[int, int, float]  # x, y, and the game window's height / 1080 (to scale distances)

POLL = 0.08          # seconds between looks at the pointer while on
IDLE_POLL = 0.5      # ... and while off
STILL_PX = 4         # the pointer counts as resting while it moves less than this (at 1080p)
LEAVE_PX = 16        # moving this far from where a price was shown hides it
RETRY_AFTER = 0.6    # a second look at the same spot, in case the tooltip wasn't up yet
TRIES = 2
CURSOR_SHOWING = 0x1


def is_tooltip_match(result) -> bool:
    """Did the check read an item's full name (which only the hover tooltip shows)?"""
    match = getattr(result, "match", None)
    return bool(match and match.full and match.score >= FULL_NAME_SCORE)


def _far(a, b, limit: float) -> bool:
    return math.hypot(a[0] - b[0], a[1] - b[1]) > limit


class HoverWatcher:
    """Watches the pointer and runs ``scan`` when it rests (see the module docs).

    ``scan`` returns a scan result, or None when another check is running.
    ``on_result`` gets results that read a tooltip; ``on_leave`` is called
    when the pointer moves away from where the last one was shown.
    """

    def __init__(
        self,
        cfg: Callable[[], ScanConfig],
        game_focused: Callable[[], bool],
        pointer: Callable[[], Optional[Pointer]],
        scan: Callable[[], object],
        on_result: Callable[[object], None],
        on_leave: Callable[[], None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cfg = cfg
        self.game_focused = game_focused
        self.pointer = pointer
        self.scan = scan
        self.on_result = on_result
        self.on_leave = on_leave
        self.clock = clock
        self.status = "off"
        self.anchor: Optional[Tuple[int, int]] = None  # where the pointer is resting
        self.since = 0.0                               # ... since when
        self.tries = 0                                 # checks done at this spot
        self.shown_at: Optional[Tuple[int, int]] = None
        self.error: Optional[str] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def step(self) -> None:
        """Look at the pointer once and check the item if it has come to rest."""
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
        if self.anchor is None or _far((x, y), self.anchor, STILL_PX * k):
            self.anchor, self.since, self.tries = (x, y), now, 0
        if self.shown_at is not None and _far((x, y), self.shown_at, LEAVE_PX * k):
            self.forget()
            self.on_leave()
        if self.tries >= TRIES or now < self.since + cfg.hover_delay + self.tries * RETRY_AFTER:
            return
        result = self.scan()
        if result is None:  # a Ctrl+Alt+P check is running: try again on the next look
            return
        self.tries += 1
        self.error = getattr(result, "error", None)
        self._set_on()
        if is_tooltip_match(result):
            self.tries = TRIES
            self.shown_at = (x, y)
            self.on_result(result)

    def _set_on(self) -> None:
        # The last check's error (say, no text reader installed) stays up
        # until a check works.
        self.status = f"can't check prices: {self.error}" if self.error else "on"

    def forget(self) -> None:
        """No price is showing any more (it was hidden or replaced)."""
        self.shown_at = None

    def _idle(self, status: str) -> None:
        self.status = status
        self.anchor = None
        if self.shown_at is not None:
            self.forget()
            self.on_leave()

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
