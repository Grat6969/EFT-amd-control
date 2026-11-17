"""Where you are, from your own in-raid screenshots.

When you press Tarkov's screenshot key in a raid, the game names the file
after your position, e.g.
``2026-11-17[13-05]_-123.4, 2.1, 56.7_0.0, 0.71, 0.0, 0.71_12.34 (0).png``
(x, height, z, then which way you face). RaidReady reads only the file NAME
of the newest screenshot and puts a dot on the Maps page.

It never presses the key for you (that would be input automation) and never
opens the images. TarkovMonitor (tarkov.dev) and Tarkov Market's Pilot do
the same. Off unless you turn it on.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)

NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\[\d{2}-\d{2}\]_?(?P<pos>.+?) \(\d+\)\.png$", re.IGNORECASE)
NUMBER = r"-?\d+(?:\.\d+)?"
COORDS = re.compile(rf"^\s*({NUMBER}),\s*({NUMBER}),\s*({NUMBER})")


def parse_name(name: str) -> Optional[dict]:
    """{x, y, z} from a Tarkov screenshot file name, or None."""
    m = NAME.match(name)
    if not m:
        return None
    c = COORDS.match(m.group("pos"))
    if not c:
        return None
    x, y, z = (float(v) for v in c.groups())
    if max(abs(x), abs(y), abs(z)) > 100_000:
        return None
    return {"x": x, "y": y, "z": z}


def default_folder() -> Path:
    """Documents\\Escape From Tarkov\\Screenshots (Documents may be moved)."""
    from .advisor import export_folder

    return export_folder().parent / "Escape From Tarkov" / "Screenshots"


class ScreenshotWatcher:
    """Looks for a new screenshot every couple of seconds."""

    def __init__(self, folder: Path, on_position: Callable[[dict], None], poll: float = 2.0) -> None:
        self.folder = folder
        self.on_position = on_position
        self.poll = poll
        self._stop = threading.Event()
        self._seen = self._newest()[1] if folder.is_dir() else 0.0  # only screenshots taken from now on
        self._thread: Optional[threading.Thread] = None

    def _newest(self):
        best, best_time = None, 0.0
        try:
            with os.scandir(self.folder) as it:
                for entry in it:
                    if entry.is_file() and entry.name.lower().endswith(".png"):
                        t = entry.stat().st_mtime
                        if t > best_time:
                            best, best_time = entry.name, t
        except OSError:
            pass
        return best, best_time

    def check(self) -> Optional[dict]:
        name, when = self._newest()
        if not name or when <= self._seen:
            return None
        self._seen = when
        pos = parse_name(name)
        if pos:
            pos.update(time=when, file=name)
            self.on_position(pos)
        return pos

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="Screenshots", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self.poll):
            try:
                self.check()
            except Exception:
                log.debug("screenshot check failed", exc_info=True)
