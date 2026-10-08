"""Turns scene brightness readings into a smooth boost for dark areas."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Optional

from .profiles import AutoConfig, Profile

STEP = 0.05  # boost is applied in 5% steps so tiny changes don't hit the driver


def target_boost(brightness: float, auto: AutoConfig) -> float:
    """0 in bright scenes, 1 in dark ones, linear in between."""
    lo, hi = auto.dark_level, auto.bright_level
    if hi <= lo:
        return 1.0 if brightness <= lo else 0.0
    return max(0.0, min(1.0, (hi - brightness) / (hi - lo)))


def boosted_profile(base: Profile, boost: float, auto: AutoConfig) -> Profile:
    if boost <= 0:
        return base
    brightness = (base.brightness or 0) + auto.brightness_boost * boost
    return replace(
        base,
        gamma=round(base.gamma + auto.gamma_boost * boost, 2),
        brightness=int(round(brightness)),
    )


class AutoAdjuster:
    def __init__(self, auto: AutoConfig) -> None:
        self.auto = auto
        self.boost = 0.0       # smoothed, continuous
        self.applied = 0.0     # last value sent to the display (quantised)
        self.scene: Optional[float] = None

    def reset(self) -> None:
        self.boost = 0.0
        self.applied = 0.0
        self.scene = None

    def update(self, brightness: Optional[float], dt: float) -> bool:
        """Feed one averaged reading. Returns True when the display should change."""
        if brightness is None:
            return False  # black frame / loading screen: hold
        self.scene = brightness
        target = target_boost(brightness, self.auto)
        # Exponential smoothing: about 63% of the way there after
        # response_seconds, so a flashlight or muzzle flash barely moves it.
        tau = max(0.05, self.auto.response_seconds)
        self.boost += (target - self.boost) * (1 - math.exp(-dt / tau))
        quantised = round(round(self.boost / STEP) * STEP, 2)
        if quantised != self.applied:
            self.applied = quantised
            return True
        return False
