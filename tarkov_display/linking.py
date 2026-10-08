"""Links the app to your game: the game-log reader and TarkovTracker.

Both feed the same progress store the Quests and Hideout pages use. Nothing
here ever removes progress; it only adds finished quests and raises levels.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import List, Optional

from . import gamelogs, secretstore
from .datasets import DataStore
from .progress import Progress
from .tracker import DOMAINS, TrackerClient, TrackerError, check_token, merge_progress

log = logging.getLogger(__name__)

GAME_MODES = ("regular", "pve")
MODE_NAMES = {"regular": "PvP", "pve": "PvE", "seasonal": "seasonal"}


def prerequisite_ids(task_id: str, tasks: Optional[List[dict]]) -> List[str]:
    """Quests that must be finished before ``task_id`` (all the way back)."""
    by_id = {t["id"]: t for t in tasks or []}
    out, stack, seen = [], [task_id], {task_id}
    while stack:
        task = by_id.get(stack.pop())
        for req in (task or {}).get("taskRequirements") or []:
            rid = (req.get("task") or {}).get("id")
            if rid and rid not in seen and "complete" in (req.get("status") or []):
                seen.add(rid)
                out.append(rid)
                stack.append(rid)
    return out


class GameLink:
    def __init__(self, web) -> None:
        self.web = web
        self.follower: Optional[gamelogs.LogFollower] = None
        self.folder: Optional[Path] = None
        self.events: deque = deque(maxlen=40)
        self.history_quests = 0
        self.game_mode: Optional[str] = None  # mode Tarkov is in, from its logs
        self.scan_result: Optional[dict] = None
        self.tracker_status: dict = {}
        self.lock = threading.Lock()  # held while progress is written and while the app switches mode
        self._stores: dict = {}  # tarkov.dev data for the mode the app isn't showing

    @property
    def cfg(self):
        return self.web.app.config

    # -- per-mode data --------------------------------------------------------

    def progress_for(self, mode: str) -> Progress:
        if mode == self.cfg.game_mode:
            return self.web.progress
        return Progress(self.web.cfg_dir / f"progress_{mode}.json")

    def data_for(self, mode: str, name: str, fetch: bool = False):
        """A tarkov.dev dataset for a game mode; with ``fetch``, downloads it
        (waiting a little) if the app hasn't loaded it yet."""
        mode = mode if mode in GAME_MODES else "regular"  # tarkov.dev has PvP and PvE data only
        if mode == self.cfg.game_mode:
            store = self.web.store
        else:
            store = self._stores.get(mode) or self._stores.setdefault(mode, DataStore(self.web.cfg_dir, mode))
        data = store.snapshot(name)["data"]
        if data is None and fetch:
            data = store.get(name, wait=20)["data"]
        return data

    def finish_quests(self, mode: str, ids: List[str]) -> List[str]:
        """Mark quests (and everything before them) done; returns what's new."""
        tasks = self.data_for(mode, "tasks", fetch=True)
        wanted = []
        for qid in ids:
            for x in [qid, *prerequisite_ids(qid, tasks)]:
                if x not in wanted:
                    wanted.append(x)
        with self.lock:
            progress = self.progress_for(mode)
            done = set(progress.snapshot()["tasks"])
            new = [x for x in wanted if x not in done]
            if new:
                snap = progress.apply({"op": "tasks", "ids": new, "done": True})
                if mode == self.cfg.game_mode:
                    self.web.publish("progress", snap)
        return new

    # -- game logs --------------------------------------------------------------

    def start_logs(self) -> None:
        self.stop_logs()
        if not self.cfg.logs.enabled:
            return
        self.folder = gamelogs.default_folder(self.cfg.logs.path)
        if not self.folder:
            log.info("Game log reader: Tarkov's Logs folder wasn't found")
            return
        self.follower = gamelogs.LogFollower(self.folder, self._on_event)
        self.follower.start()

    def stop_logs(self) -> None:
        if self.follower:
            self.follower.stop()
            self.follower = None

    def logs_state(self) -> dict:
        logs = self.cfg.logs
        found = self.folder or (gamelogs.default_folder(logs.path) if logs.enabled else None)
        f = self.follower
        return {
            "enabled": logs.enabled, "path": logs.path, "autoMap": logs.auto_map,
            "folder": str(found) if found else None,
            "detected": str(gamelogs.find_logs_folder() or "") or None,
            "session": f.session.name if f and f.session else None,
            "gameMode": self.game_mode,
            "error": f.error if f else None,
            "running": bool(f),
            "historyQuests": self.history_quests,
            "events": list(self.events),
        }

    def logs_change(self, body) -> dict:
        if not isinstance(body, dict):
            raise ValueError("bad request")
        logs = self.cfg.logs
        restart = False
        if "path" in body:
            path = str(body["path"] or "").strip()
            if path and not Path(path).expanduser().is_dir():
                raise ValueError("That folder doesn't exist.")
            logs.path, restart = path, True
        if "enabled" in body:
            logs.enabled, restart = bool(body["enabled"]), True
        if "autoMap" in body:
            logs.auto_map = bool(body["autoMap"])
        self.web.app.save()
        if restart:
            self.start_logs()
        return self.logs_state()

    def _quest_name(self, qid: str, mode: Optional[str]):
        for t in self.data_for(mode or self.cfg.game_mode, "tasks", fetch=True) or []:
            if t["id"] == qid:
                return t["name"], (t.get("trader") or {}).get("name")
        return None, None

    def _on_event(self, ev: gamelogs.Event, history: bool) -> None:
        try:
            self._handle(ev, history)
        except Exception:
            log.exception("game log event failed")

    def _handle(self, ev: gamelogs.Event, history: bool) -> None:
        payload = ev.to_dict()
        if ev.kind == "mode":
            self.game_mode = ev.mode
            if history:
                return
            payload["appMode"] = self.cfg.game_mode
        elif ev.kind == "quest":
            mode = ev.mode or self.cfg.game_mode
            name, trader = self._quest_name(ev.data["questId"], mode)
            payload.update(name=name, trader=trader)
            if ev.data["status"] == "finished" and mode in GAME_MODES:
                new = self.finish_quests(mode, [ev.data["questId"]])
                payload["added"] = len(new)
                if history:
                    self.history_quests += len(new)
                elif new:
                    self.push_completed(mode, new)
            if history:
                return
        elif ev.kind in ("raid", "raid_end"):
            if history:
                return
            for m in self.data_for(ev.mode or self.cfg.game_mode, "maps", fetch=True) or []:
                if (m.get("nameId") or "").lower() == (ev.data.get("map") or "").lower():
                    payload.update(name=m["name"], normalizedName=m["normalizedName"])
                    break
            payload["autoMap"] = self.cfg.logs.auto_map
        elif ev.kind == "flea":
            if history:
                return
            item = next((i for i in self.web.app.prices.items if i.id == ev.data.get("itemId")), None)
            payload["name"] = item.name if item else None
        self.events.appendleft(payload)
        self.web.publish("gamelog", payload)

    def scan(self) -> dict:
        folder = gamelogs.default_folder(self.cfg.logs.path)
        if not folder:
            raise ValueError("Tarkov's Logs folder wasn't found. Set it in the box above.")
        result = gamelogs.scan_history(folder)
        summary = {"sessions": result["sessions"], "first": result["first"], "last": result["last"], "modes": {}}
        for mode, found in result["modes"].items():
            if mode not in GAME_MODES:
                continue
            done = set(self.progress_for(mode).snapshot()["tasks"])
            tasks = self.data_for(mode, "tasks", fetch=True)
            implied = {p for q in found["finished"] for p in prerequisite_ids(q, tasks)}
            summary["modes"][mode] = {
                "finished": len(found["finished"]),
                "new": len([q for q in set(found["finished"]) | implied if q not in done]),
            }
        self.scan_result = {"folder": str(folder), "result": result, "summary": summary}
        return summary

    def apply_scan(self) -> dict:
        if not self.scan_result:
            raise ValueError("Scan the logs first.")
        added = {}
        for mode, found in self.scan_result["result"]["modes"].items():
            if mode in GAME_MODES and found["finished"]:
                added[mode] = len(self.finish_quests(mode, found["finished"]))
        return {"added": added}

    # -- TarkovTracker -------------------------------------------------------------

    def _token(self, mode: str) -> str:
        stored = self.cfg.tracker.tokens.get(mode, "")
        try:
            return secretstore.unprotect(stored)
        except Exception as exc:
            log.warning("Couldn't read the saved TarkovTracker token: %s", exc)
            return ""

    def client(self, mode: str) -> TrackerClient:
        token = self._token(mode)
        if not token:
            raise ValueError(f"Add your {MODE_NAMES.get(mode, mode)} TarkovTracker token first.")
        return TrackerClient(self.cfg.tracker.domain, token)

    def tracker_state(self) -> dict:
        t = self.cfg.tracker
        return {
            "domain": t.domain, "domains": list(DOMAINS),
            "tokens": {m: secretstore.mask(self._token(m)) or None for m in GAME_MODES},
            "autoImport": t.auto_import, "push": t.push, "last": t.last, "status": self.tracker_status,
        }

    def tracker_change(self, body) -> dict:
        if not isinstance(body, dict):
            raise ValueError("bad request")
        t = self.cfg.tracker
        if "domain" in body:
            if body["domain"] not in DOMAINS:
                raise ValueError("Unknown TarkovTracker site.")
            if body["domain"] != t.domain:
                t.domain, t.tokens = body["domain"], {}  # tokens belong to one site
        if "token" in body:
            mode, value = (body["token"] or {}).get("mode"), str((body["token"] or {}).get("value") or "").strip()
            if mode not in GAME_MODES:
                raise ValueError("bad game mode")
            if value:
                try:
                    check_token(t.domain, value, mode)
                except TrackerError as exc:
                    raise ValueError(str(exc)) from None
                t.tokens[mode] = secretstore.protect(value)
            else:
                t.tokens.pop(mode, None)
            self.tracker_status.pop(mode, None)
        if "autoImport" in body:
            t.auto_import = bool(body["autoImport"])
        if "push" in body:
            t.push = bool(body["push"])
        self.web.app.save()
        return self.tracker_state()

    def tracker_test(self, mode: str) -> dict:
        try:
            info = self.client(mode).token_info()
        except TrackerError as exc:
            self.tracker_status[mode] = {"ok": False, "message": str(exc), "time": time.time()}
            raise ValueError(str(exc)) from None
        perms = info["permissions"]
        message = "Token works." + ("" if "WP" in perms else " It can read progress but not update it.")
        self.tracker_status[mode] = {"ok": True, "message": message, "permissions": perms, "time": time.time()}
        return self.tracker_status[mode]

    def tracker_import(self, mode: str) -> dict:
        if mode not in GAME_MODES:
            raise ValueError("bad game mode")
        try:
            data = self.client(mode).progress()
        except TrackerError as exc:
            self.tracker_status[mode] = {"ok": False, "message": str(exc), "time": time.time()}
            raise ValueError(str(exc)) from None
        stations = self.data_for(mode, "hideout", fetch=True)
        with self.lock:
            progress = self.progress_for(mode)
            summary = merge_progress(progress, data, stations)
            if mode == self.cfg.game_mode:
                self.web.publish("progress", progress.snapshot())
        self.cfg.tracker.last[mode] = {"time": time.time(), "summary": summary}
        self.web.app.save()
        log.info("Imported from TarkovTracker (%s): %s", mode, summary)
        return summary

    def auto_import(self) -> None:
        t = self.cfg.tracker
        if not t.auto_import:
            return
        mode = self.cfg.game_mode
        if mode not in GAME_MODES or not self._token(mode):
            return
        try:
            summary = self.tracker_import(mode)
            if summary["tasks"] or summary["hideout"] or summary["level"]:
                self.web.publish("gamelog", {"kind": "tracker", "mode": mode, **summary})
        except Exception as exc:
            log.warning("TarkovTracker auto-import failed: %s", exc)

    def push_completed(self, mode: str, ids: List[str]) -> None:
        """Send quests finished in game to TarkovTracker (if turned on)."""
        if not self.cfg.tracker.push or not self._token(mode):
            return

        def send():
            try:
                self.client(mode).set_tasks(ids, "completed")
                self.tracker_status[mode] = {"ok": True, "message": f"Sent {len(ids)} quest(s).", "time": time.time()}
            except Exception as exc:
                self.tracker_status[mode] = {"ok": False, "message": str(exc), "time": time.time()}
                self.web.publish("gamelog", {"kind": "tracker_error", "mode": mode, "message": str(exc)})

        threading.Thread(target=send, name="TrackerPush", daemon=True).start()
