"""TarkovTracker (tarkovtracker.org / tarkovtracker.io) integration.

Reads your quest and hideout progress with a personal API token you create
on the TarkovTracker site, and can mark quests as completed there.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Iterable, List, Optional

from . import __version__

DOMAINS = {
    "tarkovtracker.org": "https://api.tarkovtracker.org",
    "tarkovtracker.io": "https://tarkovtracker.io/api/v2",
}
# tarkovtracker.org tokens name their game mode: PVP_/PVE_/SZN_ + 18 hex digits.
ORG_TOKEN = re.compile(r"^(PVP|PVE|SZN)_[0-9a-fA-F]{18}$")
ORG_MODES = {"PVP": "regular", "PVE": "pve", "SZN": "seasonal"}


class TrackerError(RuntimeError):
    pass


def token_mode(domain: str, token: str) -> Optional[str]:
    """The game mode a tarkovtracker.org token belongs to."""
    if domain == "tarkovtracker.org":
        m = ORG_TOKEN.match(token.strip())
        return ORG_MODES[m.group(1).upper()] if m else None
    return None


def check_token(domain: str, token: str, mode: str) -> None:
    token = token.strip()
    if domain not in DOMAINS:
        raise TrackerError("Unknown TarkovTracker site.")
    if not token or len(token) > 200 or any(c.isspace() for c in token):
        raise TrackerError("That doesn't look like a TarkovTracker token.")
    if domain == "tarkovtracker.org":
        found = token_mode(domain, token)
        if not found:
            raise TrackerError("tarkovtracker.org tokens look like PVP_ or PVE_ followed by 18 letters and numbers.")
        if found != mode:
            label = {"regular": "PvP", "pve": "PvE", "seasonal": "seasonal"}[found]
            raise TrackerError(f"That is a {label} token; paste it into the {label} box.")


class TrackerClient:
    def __init__(self, domain: str, token: str, timeout: float = 30) -> None:
        if domain not in DOMAINS:
            raise TrackerError("Unknown TarkovTracker site.")
        self.base = DOMAINS[domain]
        self.token = token.strip()
        self.timeout = timeout

    def _request(self, method: str, path: str, body=None):
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "User-Agent": f"RaidReady/{__version__}",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace").strip()[:200]
            if exc.code in (401, 403):
                raise TrackerError("TarkovTracker refused the request. Check the token and its permissions on the "
                                   "TarkovTracker site (sending quests needs permission to write progress).") from None
            if exc.code == 429:
                raise TrackerError("TarkovTracker is rate-limiting requests; try again in a minute.") from None
            raise TrackerError(f"TarkovTracker answered HTTP {exc.code}" + (f": {detail}" if detail else "")) from None
        except urllib.error.URLError as exc:
            raise TrackerError(f"Couldn't reach TarkovTracker: {exc.reason}") from None
        try:
            return json.loads(raw) if raw.strip() else {}
        except ValueError:
            return {"raw": raw.decode("utf-8", "replace")[:200]}

    def token_info(self) -> dict:
        info = self._request("GET", "/token")
        return {"permissions": info.get("permissions") or [], "gameMode": info.get("gameMode")}

    def progress(self) -> dict:
        res = self._request("GET", "/progress")
        data = res.get("data") if isinstance(res, dict) else None
        if not isinstance(data, dict):
            raise TrackerError("TarkovTracker sent progress in a format this app doesn't understand.")
        return data

    def set_tasks(self, ids: Iterable[str], state: str = "completed") -> None:
        body = [{"id": i, "state": state} for i in ids]
        if body:
            self._request("POST", "/progress/tasks", body)


def merge_progress(progress, data: dict, stations: Optional[List[dict]]) -> dict:
    """Add TarkovTracker progress to ours. Never removes anything: finished
    quests are added, hideout levels and player level only go up."""
    current = progress.snapshot()
    done = set(current["tasks"])
    finished = {
        t["id"] for t in data.get("tasksProgress") or []
        if isinstance(t, dict) and t.get("id") and t.get("complete") and not t.get("failed") and not t.get("invalid")
    }
    new_tasks = sorted(finished - done)
    if new_tasks:
        progress.apply({"op": "tasks", "ids": new_tasks, "done": True})

    built = {m["id"] for m in data.get("hideoutModulesProgress") or [] if isinstance(m, dict) and m.get("complete")}
    raised = 0
    for station in stations or []:
        level = max((l["level"] for l in station.get("levels") or [] if l.get("id") in built), default=0)
        if level > current["hideout"].get(station["id"], 0):
            progress.apply({"op": "hideout", "station": station["id"], "level": level})
            raised += 1

    profile = {}
    level = data.get("playerLevel")
    if isinstance(level, int) and level > current["player_level"]:
        profile["player_level"] = level
    if data.get("pmcFaction") in ("USEC", "BEAR") and data["pmcFaction"] != current["faction"]:
        profile["faction"] = data["pmcFaction"]
    if profile:
        progress.apply({"op": "profile", **profile})
    return {
        "tasks": len(new_tasks), "trackerTasks": len(finished), "hideout": raised,
        "hideoutKnown": stations is not None, "level": profile.get("player_level"), "faction": profile.get("faction"),
        "name": data.get("displayName"),
    }
