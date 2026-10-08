"""Background loop that switches the profile on and off with the game."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional, Tuple

from .auto import AutoAdjuster, boosted_profile
from .controller import DisplayController
from .profiles import Config

log = logging.getLogger(__name__)

Probe = Callable[[], Tuple[bool, bool]]
Sampler = Callable[[], Optional[float]]


class GameWatcher:
    def __init__(
        self,
        controller: DisplayController,
        config: Config,
        probe: Optional[Probe] = None,
        on_change: Optional[Callable[[str], None]] = None,
        sampler: Optional[Sampler] = None,
    ) -> None:
        self.controller = controller
        self.config = config
        if probe is None:
            from .winproc import game_state

            probe = lambda: game_state(self.config.process_names)
        self.probe = probe
        self._sampler = sampler
        self.adjuster = AutoAdjuster(config.auto)
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

    def _scene_brightness(self) -> Optional[float]:
        try:
            if self._sampler is None:
                from .screen import ScreenSampler

                self._sampler = ScreenSampler().scene_brightness
            return self._sampler()
        except Exception as exc:
            log.debug("screen sample failed: %s", exc)
            return None

    def tick(self, dt: Optional[float] = None) -> None:
        try:
            running, focused = self.probe()
        except Exception as exc:
            log.debug("probe failed: %s", exc)
            return
        name = self.config.active_profile
        auto = self.config.auto
        if self.should_apply(running, focused):
            changed = self._applied != name
            if auto.enabled:
                self.adjuster.auto = auto
                if self.adjuster.update(self._scene_brightness(), dt or auto.sample_interval):
                    changed = True
            elif self.adjuster.applied:
                self.adjuster.reset()
                changed = True
            if changed:
                boost = self.adjuster.applied if auto.enabled else 0.0
                self.controller.apply(boosted_profile(self.config.profile, boost, auto))
            if self._applied != name:
                self._applied = name
                where = "preview" if self.force and not running else "game active"
                self._set_status(f"{where} - profile '{name}' applied")
        else:
            self.adjuster.reset()
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
        last = time.monotonic()
        error = None
        while not self._stop.is_set():
            now = time.monotonic()
            try:
                self.tick(now - last)
                error = None
            except Exception as exc:  # e.g. the graphics driver restarted: keep watching
                if str(exc) != error:
                    log.warning("Display update failed: %s", exc, exc_info=True)
                error = str(exc)
            last = now
            fast = self.config.auto.enabled and self.controller.active is not None
            self._wake.wait(self.config.auto.sample_interval if fast else self.config.poll_seconds)
            self._wake.clear()
        try:
            self.controller.restore()
        except Exception as exc:
            log.warning("Could not put the desktop display settings back: %s", exc)
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
