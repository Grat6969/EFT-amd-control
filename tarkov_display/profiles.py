"""Display profiles and the JSON config file that stores them."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class Profile:
    """One set of display settings.

    The colour values use the same units as the "Display Color" page in
    AMD Software: Adrenalin Edition. ``None`` means "use the driver default".
    Values outside what your driver reports as valid are clamped.
    """

    brightness: Optional[int] = 0      # typically -100 .. 100, default 0
    contrast: Optional[int] = 100      # typically 0 .. 200, default 100
    saturation: Optional[int] = 100    # typically 0 .. 200, default 100
    hue: Optional[int] = None          # leave alone unless you know you want it
    temperature: Optional[int] = None  # colour temperature in Kelvin, default 6500
    gamma: float = 1.0                 # Windows gamma ramp; >1 lifts shadows

    @classmethod
    def from_dict(cls, data: dict) -> "Profile":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self) -> dict:
        return asdict(self)


# Starting points tuned for Tarkov. Saturation is the big one: it makes
# player kits stand out from grass, rocks and concrete. Gamma lifts dark
# corners and night raids without washing out the sky as much as raw
# brightness does.
BUILTIN_PROFILES: Dict[str, Profile] = {
    "balanced": Profile(brightness=10, contrast=110, saturation=135, gamma=1.15),
    "day": Profile(brightness=5, contrast=112, saturation=140, gamma=1.05),
    "interiors": Profile(brightness=15, contrast=115, saturation=135, gamma=1.30),
    "night": Profile(brightness=25, contrast=105, saturation=125, gamma=1.50),
}

DEFAULT_PROCESS_NAMES = ["EscapeFromTarkov.exe", "EscapeFromTarkovArena.exe"]


def default_config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "TarkovDisplay"


@dataclass
class Config:
    active_profile: str = "balanced"
    profiles: Dict[str, Profile] = field(
        default_factory=lambda: {k: Profile(**asdict(v)) for k, v in BUILTIN_PROFILES.items()}
    )
    process_names: List[str] = field(default_factory=lambda: list(DEFAULT_PROCESS_NAMES))
    # Only apply while the game window is focused, so alt-tabbing to a
    # browser or Discord gives you your normal desktop back.
    foreground_only: bool = True
    hotkeys: bool = True
    poll_seconds: float = 1.0

    @property
    def profile(self) -> Profile:
        return self.profiles.get(self.active_profile) or BUILTIN_PROFILES["balanced"]

    def profile_names(self) -> List[str]:
        return list(self.profiles)

    def to_dict(self) -> dict:
        return {
            "active_profile": self.active_profile,
            "profiles": {k: v.to_dict() for k, v in self.profiles.items()},
            "process_names": self.process_names,
            "foreground_only": self.foreground_only,
            "hotkeys": self.hotkeys,
            "poll_seconds": self.poll_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        cfg = cls()
        if isinstance(data.get("profiles"), dict) and data["profiles"]:
            cfg.profiles = {k: Profile.from_dict(v) for k, v in data["profiles"].items()}
        for key in ("active_profile", "process_names", "foreground_only", "hotkeys", "poll_seconds"):
            if key in data:
                setattr(cfg, key, data[key])
        if cfg.active_profile not in cfg.profiles:
            cfg.active_profile = next(iter(cfg.profiles))
        return cfg


def load_config(path: Optional[Path] = None) -> Config:
    path = path or default_config_dir() / "config.json"
    if not path.exists():
        cfg = Config()
        save_config(cfg, path)
        return cfg
    with open(path, "r", encoding="utf-8") as fh:
        return Config.from_dict(json.load(fh))


def save_config(cfg: Config, path: Optional[Path] = None) -> Path:
    path = path or default_config_dir() / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg.to_dict(), fh, indent=2)
    os.replace(tmp, path)
    return path
