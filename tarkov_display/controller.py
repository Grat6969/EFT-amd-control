"""Applies profiles to the display and puts the original settings back."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional

from .adl import COLOR_TYPES, ColorRange
from .gamma import Ramp, build_ramp
from .profiles import Profile

log = logging.getLogger(__name__)


class DisplayController:
    """Owns the AMD colour backend and the gamma backend.

    The first time a profile is applied, the current settings are saved to
    ``state_path``. ``restore()`` writes them back and deletes the file. If
    the app crashes or the PC loses power while a profile is active, calling
    ``recover()`` at the next start puts the desktop back to normal.
    """

    def __init__(self, color=None, gamma=None, state_path: Optional[Path] = None) -> None:
        self.color = color
        self.gamma = gamma
        self.state_path = state_path
        self._lock = threading.RLock()
        self._ranges: Dict[str, Dict[str, ColorRange]] = {}
        self._snapshot: Optional[dict] = None
        self._gamma_warned = False
        self.active: Optional[Profile] = None

    @classmethod
    def create(cls, state_path: Optional[Path] = None) -> "DisplayController":
        color = gamma = None
        try:
            from .adl import ADL

            color = ADL()
            names = ", ".join(d.name for d in color.displays()) or "none found"
            log.info("AMD driver connected (displays: %s)", names)
        except Exception as exc:
            log.warning("AMD colour controls unavailable: %s", exc)
            log.warning("Falling back to gamma-ramp only (brightness/contrast emulated, no saturation).")
        try:
            from .gamma import GammaRamp

            gamma = GammaRamp()
        except Exception as exc:
            log.warning("Gamma ramp unavailable: %s", exc)
        return cls(color, gamma, state_path)

    # -- snapshot -------------------------------------------------------

    def _color_displays(self) -> List:
        return self.color.displays() if self.color else []

    def _gamma_displays(self) -> List[str]:
        return self.gamma.displays() if self.gamma else []

    def _range(self, display, name: str) -> Optional[ColorRange]:
        per = self._ranges.setdefault(display.key, {})
        if name not in per:
            try:
                per[name] = self.color.get_color(display, name)
            except Exception as exc:
                log.debug("%s not supported on %s: %s", name, display.name, exc)
                per[name] = None
        return per[name]

    def _take_snapshot(self) -> None:
        if self._snapshot is not None:
            return
        snap: dict = {"color": {}, "gamma": {}}
        for d in self._color_displays():
            values = {}
            for name in COLOR_TYPES:
                rng = self._range(d, name)
                if rng is not None:
                    values[name] = rng.current
            snap["color"][d.key] = values
        for dev in self._gamma_displays():
            try:
                snap["gamma"][dev] = self.gamma.get(dev)
            except Exception as exc:
                log.debug("Could not read gamma for %s: %s", dev, exc)
        self._snapshot = snap
        self._save_state(snap)

    def _save_state(self, snap: dict) -> None:
        if not self.state_path:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(snap, fh)
        os.replace(tmp, self.state_path)

    # -- public API -----------------------------------------------------

    def apply(self, profile: Profile) -> None:
        with self._lock:
            self._take_snapshot()
            for d in self._color_displays():
                for name in COLOR_TYPES:
                    rng = self._range(d, name)
                    if rng is None:
                        continue
                    target = getattr(profile, name)
                    value = rng.default if target is None else rng.clamp(target)
                    try:
                        self.color.set_color(d, name, value)
                    except Exception as exc:
                        log.warning("Could not set %s on %s: %s", name, d.name, exc)

            if self.color:
                ramp = build_ramp(profile.gamma)
            else:
                ramp = build_ramp(
                    profile.gamma,
                    profile.brightness or 0,
                    100 if profile.contrast is None else profile.contrast,
                )
            self._set_gamma_all(ramp)
            self.active = profile

    def _set_gamma_all(self, ramp: Ramp) -> None:
        for dev in self._gamma_displays():
            ok = False
            try:
                ok = self.gamma.set(dev, ramp)
            except Exception as exc:
                log.debug("SetDeviceGammaRamp error on %s: %s", dev, exc)
            if not ok and not self._gamma_warned:
                self._gamma_warned = True
                log.warning(
                    "Windows refused the gamma setting on %s. Windows limits how far gamma "
                    "can move unless you run 'enable_full_gamma_range.reg' once (then reboot).",
                    dev,
                )

    def restore(self) -> None:
        with self._lock:
            snap = self._snapshot
            if snap is None:
                return
            self._restore_snapshot(snap)
            self._snapshot = None
            self.active = None
            if self.state_path and self.state_path.exists():
                self.state_path.unlink()

    def _restore_snapshot(self, snap: dict) -> None:
        by_key = {d.key: d for d in self._color_displays()}
        for key, values in snap.get("color", {}).items():
            d = by_key.get(key)
            if d is None:
                continue
            for name, value in values.items():
                try:
                    self.color.set_color(d, name, value)
                except Exception as exc:
                    log.warning("Could not restore %s on %s: %s", name, d.name, exc)
        for dev, ramp in snap.get("gamma", {}).items():
            try:
                self.gamma.set(dev, ramp)
            except Exception as exc:
                log.warning("Could not restore gamma on %s: %s", dev, exc)

    def recover(self) -> bool:
        """Undo settings left behind by a previous run that did not exit cleanly."""
        if not self.state_path or not self.state_path.exists():
            return False
        try:
            with open(self.state_path, "r", encoding="utf-8") as fh:
                snap = json.load(fh)
        except (OSError, ValueError) as exc:
            log.warning("Ignoring unreadable state file %s: %s", self.state_path, exc)
            self.state_path.unlink(missing_ok=True)
            return False
        with self._lock:
            self._restore_snapshot(snap)
            self.state_path.unlink(missing_ok=True)
        log.info("Restored display settings left over from a previous session.")
        return True

    def close(self) -> None:
        self.restore()
        if self.color and hasattr(self.color, "close"):
            self.color.close()
