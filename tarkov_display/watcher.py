"""Background loop that switches the profile on and off with the game."""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional, Tuple

from .controller import DisplayController
from .profiles import Config

log = logging.getLogger(__name__)

Probe = Callable[[], Tuple[bool, bool]]


class GameWatcher:
    def __init__(
        self,
        controller: DisplayController,
        config: Config,
        probe: Optional[Probe] = None,
        on_change: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.controller = controller
        self.config = config
        if probe is None:
            from .winproc import game_state

            probe = lambda: game_state(self.config.process_names)
        self.probe = probe
        self.on_change = on_change or (lambda status: None)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._applied: Optional[str] = None
        self._thread: Optional[threading.Thread] = None
        self.paused = False
        self.force = False  # apply even without the game (desktop preview)
        self.status = "waiting for game"

    def _set_status(self, status: str) -> None:
        if status != self.status:
            self.status = status
            log.info(status)
            self.on_change(status)

    def should_apply(self, running: bool, focused: bool) -> bool:
        if self.force:
            return True
        if self.paused:
            return False
        return running and (focused or not self.config.foreground_only)

    def tick(self) -> None:
        try:
            running, focused = self.probe()
        except Exception as exc:
            log.debug("probe failed: %s", exc)
            return
        name = self.config.active_profile
        if self.should_apply(running, focused):
            if self._applied != name:
                self.controller.apply(self.config.profile)
                self._applied = name
                where = "preview" if self.force and not running else "game active"
                self._set_status(f"{where} - profile '{name}' applied")
        else:
            if self._applied is not None or self.controller.active is not None:
                self.controller.restore()
                self._applied = None
            if self.paused:
                self._set_status("paused - desktop settings")
            elif running:
                self._set_status("game in background - desktop settings")
            else:
                self._set_status("waiting for game")

    def refresh(self) -> None:
        """Re-apply on the next tick, e.g. after the profile was edited."""
        self._applied = None
        self._wake.set()

    def run(self) -> None:
        log.info("Watching for %s", ", ".join(self.config.process_names))
        while not self._stop.is_set():
            self.tick()
            self._wake.wait(self.config.poll_seconds)
            self._wake.clear()
        self.controller.restore()
        self._applied = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self.run, name="GameWatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
