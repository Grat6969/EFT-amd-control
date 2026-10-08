"""Global hotkeys (work while the game is focused).

Ctrl+Alt+1..9  switch to profile 1..9 (in the order they appear in the config)
Ctrl+Alt+0     turn the overlay off/on (back to desktop settings)
"""

from __future__ import annotations

import ctypes
import logging
import threading
from typing import Callable, Optional

log = logging.getLogger(__name__)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012


class Hotkeys:
    def __init__(self, on_profile: Callable[[int], None], on_toggle: Callable[[], None]) -> None:
        self.on_profile = on_profile
        self.on_toggle = on_toggle
        self._thread: Optional[threading.Thread] = None
        self._thread_id = 0

    def _run(self) -> None:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        mods = MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
        registered = []
        for digit in range(10):
            vk = 0x30 + digit  # '0'..'9'
            if user32.RegisterHotKey(None, digit + 1, mods, vk):
                registered.append(digit + 1)
            else:
                log.warning("Ctrl+Alt+%d is already used by another program", digit)

        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message != WM_HOTKEY:
                    continue
                digit = msg.wParam - 1
                try:
                    if digit == 0:
                        self.on_toggle()
                    else:
                        self.on_profile(digit - 1)
                except Exception:
                    log.exception("hotkey handler failed")
        finally:
            for hid in registered:
                user32.UnregisterHotKey(None, hid)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="Hotkeys", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread and self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(timeout=2)
        self._thread = None
