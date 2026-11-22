"""Your public Tarkov profile, as tarkov.dev shows it on its Players page.

The game's logs name your account id (AccountId:<digits>); tarkov.dev serves
the matching public profile: level, skills, PMC and Scav raid counts
(survived / killed / ran through), kills, the kit you have on and your
achievements. That covers most of what the logs don't say.

This is the same public data anyone can look up on tarkov.dev; nothing here
touches the game. Profiles are fetched rarely and kept on disk.

The profile is BSG's format, which tarkov.dev passes on mostly as is. Key
names have changed case over the years, so every lookup here ignores case.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .client import TarkovClient

log = logging.getLogger(__name__)

ACCOUNT = re.compile(r"AccountId:\s*(\d{3,12})")
MODES = {"regular": "regular", "pve": "pve"}
# tarkov.dev's own player page asks the first; TarkovMonitor reads the cached
# files (the second). Tried in order.
URLS = (
    "https://player.tarkov.dev/account/{aid}?gameMode={mode}",
    "https://players.tarkov.dev/{folder}/{aid}.json",
)
FOLDERS = {"regular": "profile", "pve": "pve"}
MIN_GAP = 10 * 60          # don't ask tarkov.dev more often than this
LEVELS_QUERY = "query Levels { playerLevels { level exp } }"
# Skills worth naming in the export (others only if they're high).
KEY_SKILLS = ("Strength", "Endurance", "Metabolism", "Health", "Vitality", "StressResistance", "Charisma",
              "HideoutManagement", "Crafting", "Search", "Perception", "Attention", "Sniping", "Troubleshooting")
SKILL_NAMES = {"StressResistance": "Stress Resistance", "HideoutManagement": "Hideout Management",
               "AimDrills": "Aim Drills", "RecoilControl": "Recoil Control", "WeaponTreatment": "Weapon Maintenance",
               "LightVests": "Light Armor", "HeavyVests": "Heavy Armor", "BotSound": "Silent Operations"}


# -- reading the account id from the game logs --------------------------------------------

def account_id(logs_folder: Optional[Path], sessions: int = 5) -> Optional[str]:
    """Your account id, from the newest sessions' application log."""
    if not logs_folder:
        return None
    from .gamelogs import _read_head, log_files, session_folders

    for session in reversed(session_folders(logs_folder)[-sessions:]):
        for path in log_files(session):
            if "application" in path.name.lower():
                m = ACCOUNT.search(_read_head(path, 2 * 1024 * 1024))
                if m:
                    return m.group(1)
    return None


# -- case-insensitive access to BSG's JSON -------------------------------------------------

def _get(data: Any, *path: str, default=None):
    for key in path:
        if not isinstance(data, dict):
            return default
        if key in data:
            data = data[key]
            continue
        low = key.lower()
        match = next((v for k, v in data.items() if isinstance(k, str) and k.lower() == low), None)
        if match is None:
            return default
        data = match
    return data


def _num(value) -> Optional[float]:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def counters(stats: Any) -> Dict[tuple, float]:
    """{("ExitStatus", "Survived", "Pmc"): 12, ...} from an OverallCounters block."""
    items = _get(stats, "Eft", "OverAllCounters", "Items") or _get(stats, "OverAllCounters", "Items") \
        or _get(stats, "Eft", "OverallCounters", "Items") or _get(stats, "OverallCounters", "Items") or []
    out: Dict[tuple, float] = {}
    for it in items if isinstance(items, list) else []:
        key, value = _get(it, "Key"), _num(_get(it, "Value"))
        if isinstance(key, list) and value is not None:
            out[tuple(str(k) for k in key)] = value
    return out


def _count(c: Dict[tuple, float], *names: str) -> int:
    """Sum of the counters whose key holds all ``names`` (ignoring case)."""
    want = {n.lower() for n in names}
    best = [v for k, v in c.items() if want <= {x.lower() for x in k}]
    # The most specific match: e.g. ("Sessions", "Pmc") over a broader total.
    exact = [v for k, v in c.items() if {x.lower() for x in k} == want]
    return int(exact[0] if exact else (min(best) if best else 0))


def raid_stats(stats: Any, side: str) -> dict:
    c = counters(stats)
    sessions = _count(c, "Sessions", side)
    out = {
        "raids": sessions,
        "survived": _count(c, "ExitStatus", "Survived", side),
        "killed": _count(c, "ExitStatus", "Killed", side),
        "runThrough": _count(c, "ExitStatus", "Runner", side),
        "mia": _count(c, "ExitStatus", "MissingInAction", side) or _count(c, "ExitStatus", "Left", side),
        "kills": _count(c, "Kills"),
        "pmcKills": _count(c, "KilledPmc") or _count(c, "KilledUsec") + _count(c, "KilledBear"),
        "deaths": _count(c, "Deaths"),
    }
    out["survivalRate"] = round(out["survived"] / sessions, 3) if sessions else None
    return out


def level_for(experience: Optional[float], levels: Optional[List[dict]]) -> Optional[int]:
    if experience is None or not levels:
        return None
    level = 1
    for row in sorted((r for r in levels if isinstance(r, dict)), key=lambda r: r.get("level") or 0):
        if isinstance(row.get("exp"), (int, float)) and experience >= row["exp"]:
            level = row.get("level") or level
    return level


def summarize(raw: dict, levels: Optional[List[dict]] = None, item_names: Optional[Dict[str, str]] = None) -> dict:
    """The parts of a profile RaidReady uses."""
    info = _get(raw, "info") or {}
    experience = _num(_get(info, "experience"))
    skills = []
    for s in _get(raw, "skills", "Common") or []:
        sid, progress = _get(s, "Id"), _num(_get(s, "Progress"))
        if isinstance(sid, str) and progress is not None:
            skills.append({"id": sid, "name": SKILL_NAMES.get(sid, re.sub(r"(?<!^)(?=[A-Z])", " ", sid)),
                           "level": int(progress // 100)})
    skills.sort(key=lambda s: -s["level"])
    names = item_names or {}
    gear = []
    equipment = _get(raw, "equipment") or {}
    root = _get(equipment, "Id")
    for it in _get(equipment, "Items") or []:
        if _get(it, "parentId") == root and _get(it, "slotId") not in (None, "Pockets", "SecuredContainer", "Dogtag", "Scabbard", "ArmBand"):
            tpl = _get(it, "_tpl")
            gear.append({"slot": _get(it, "slotId"), "id": tpl, "name": names.get(tpl, tpl)})
    achievements = _get(raw, "achievements") or {}
    return {
        "nickname": _get(info, "nickname"),
        "side": _get(info, "side"),
        "experience": experience,
        "level": level_for(experience, levels) or _num(_get(info, "level")),
        "prestige": _num(_get(info, "prestigeLevel")),
        "memberCategory": _get(info, "memberCategory"),
        "skills": skills,
        "pmc": raid_stats(_get(raw, "pmcStats"), "Pmc"),
        "scav": raid_stats(_get(raw, "scavStats"), "Scav"),
        "gear": gear,
        "achievements": sorted(achievements) if isinstance(achievements, dict) else [],
        "updated": _num(_get(raw, "updated")),
    }


# -- fetching and caching -----------------------------------------------------------------

class ProfileStore:
    def __init__(self, cache_dir: Optional[Path], client_for=lambda mode: TarkovClient(mode)) -> None:
        self.cache_dir = cache_dir
        self.client_for = client_for
        self._levels: Optional[List[dict]] = None

    def _path(self, mode: str) -> Optional[Path]:
        return self.cache_dir / f"profile_{mode}.json" if self.cache_dir else None

    def cached(self, mode: str) -> Optional[dict]:
        path = self._path(mode)
        try:
            with open(path, "r", encoding="utf-8") as fh:  # type: ignore[arg-type]
                return json.load(fh)
        except (OSError, TypeError, ValueError):
            return None

    def _save(self, mode: str, data: dict) -> None:
        path = self._path(mode)
        if not path:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)

    def levels(self, client: TarkovClient) -> Optional[List[dict]]:
        if self._levels is None:
            try:
                self._levels = client.query(LEVELS_QUERY).get("playerLevels") or None
            except Exception as exc:
                log.info("Couldn't get the XP table from tarkov.dev: %s", exc)
        return self._levels

    def fetch(self, aid: str, mode: str, item_names: Optional[Dict[str, str]] = None, force: bool = False) -> dict:
        """Your profile from tarkov.dev (or the copy fetched in the last few minutes)."""
        if not re.fullmatch(r"\d{3,12}", aid or ""):
            raise ValueError("No account id: turn on the game log reader so RaidReady can find it.")
        mode = MODES.get(mode, "regular")
        old = self.cached(mode)
        if old and old.get("accountId") == aid and not force and time.time() - old.get("fetched", 0) < MIN_GAP:
            return old
        client = self.client_for(mode)
        errors = []
        raw = None
        for url in URLS:
            url = url.format(aid=aid, mode=mode, folder=FOLDERS[mode])
            try:
                data = client.get_json(url)
            except Exception as exc:
                errors.append(f"{url.split('/')[2]}: {exc}")
                continue
            if isinstance(data, dict) and (_get(data, "info") or _get(data, "pmcStats")):
                raw = data
                break
            errors.append(f"{url.split('/')[2]}: no profile in the answer")
        if raw is None:
            raise ValueError(not_found_message(aid, mode, errors))
        result = {"accountId": aid, "mode": mode, "fetched": time.time(),
                  "profile": summarize(raw, self.levels(client), item_names)}
        self._save(mode, result)
        return result


def not_found_message(aid: str, mode: str, errors: List[str]) -> str:
    """Why there's no profile, in words (the servers' answers can be whole
    HTML error pages). tarkov.dev's profile service now wants a browser
    check (Cloudflare Turnstile) that an app can't pass, so the only way in
    is the copy tarkov.dev keeps of profiles looked up on its site."""
    checked = any("HTTP 401" in e or "HTTP 403" in e for e in errors if e.startswith("player.tarkov.dev"))
    missing = any("HTTP 404" in e for e in errors if e.startswith("players.tarkov.dev"))
    page = f"tarkov.dev/players/{mode}/{aid}"
    if checked and missing:
        return ("tarkov.dev has no copy of your profile for RaidReady to read: its profile service now asks for a "
                "browser check that apps can't do. Open " + page + " in your browser and let it load; that may "
                "make tarkov.dev keep a copy RaidReady can read, so try again after. Your level and faction can "
                "also be set by hand on the Quests page.")
    short = [re.sub(r"<[^>]+>", " ", e) for e in errors]
    short = [re.sub(r"\s+", " ", e).strip()[:120] for e in short]
    return ("tarkov.dev didn't return your profile (" + "; ".join(short) + "). If it keeps failing, open "
            + page + " in your browser once and try again.")


def export_lines(cached: Optional[dict]) -> List[str]:
    """The profile section of the Ask Claude export."""
    if not cached or not cached.get("profile"):
        return []
    p = cached["profile"]
    out = ["## My profile (public, from tarkov.dev)", ""]
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(cached.get("fetched") or 0))
    head = [f"Level {p['level']}" if p.get("level") else None, p.get("side"),
            f"prestige {int(p['prestige'])}" if p.get("prestige") else None]
    out.append(f"- {', '.join(x for x in head if x)} (fetched {when})")
    for key, label in (("pmc", "PMC"), ("scav", "Scav")):
        s = p.get(key) or {}
        if s.get("raids"):
            rate = f"{s['survivalRate'] * 100:.0f}% survived" if s.get("survivalRate") is not None else ""
            out.append(f"- {label}: {s['raids']} raids, {s['survived']} survived, {s['killed']} killed, "
                       f"{s['runThrough']} run-throughs ({rate}); {s['kills']} kills" + (f", {s['pmcKills']} PMCs" if s.get("pmcKills") else ""))
    skills = p.get("skills") or []
    named = [s for s in skills if s["id"] in KEY_SKILLS or s["level"] >= 10]
    if named:
        out.append("- Skills: " + ", ".join(f"{s['name']} {s['level']}" for s in named[:14]))
    if p.get("gear"):
        out.append("- Kit on my PMC right now: " + ", ".join(f"{g['name']}" for g in p["gear"][:12]))
    return out + [""]
