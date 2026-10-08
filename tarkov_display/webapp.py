"""The app: display control and hotkeys from ``App``, tarkov.dev data, your
progress, and the window (a local web page shown in an Edge app window)."""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections import deque
from dataclasses import asdict
from typing import List, Optional

from . import APP_NAME, __version__
from .app import App
from .datasets import DATASETS, DataStore
from .linking import GameLink
from .prices import PriceDB, rub
from .profiles import BUILTIN_PROFILES, Profile, load_config
from .progress import Progress
from .server import Server, find_running
from .updater import DEFAULT_BRANCH, Updater
from .window import open_window

log = logging.getLogger(__name__)

NEED_TYPES = ("giveItem", "plantItem", "mark")
CLOSE_GRACE = 8.0          # seconds after the last window closes before quitting
REOPEN_AFTER = 40.0        # open a window if none connected this long after start
UPDATE_CHECK_EVERY = 6 * 3600


def _clamp(value, lo, hi, kind=float):
    try:
        return max(lo, min(hi, kind(value)))
    except (TypeError, ValueError):
        raise ValueError(f"not a number: {value!r}") from None


def _opt(value, lo, hi):
    return None if value is None else _clamp(value, lo, hi, int)


class WebApp:
    def __init__(self, open_on_start: bool = True, restarted: bool = False, port: Optional[int] = None) -> None:
        self.app = App()
        cfg = self.app.config
        self.cfg_dir = self.app.config_path.parent
        self.store = self._make_store(cfg.game_mode)
        self.progress = Progress(self.cfg_dir / f"progress_{cfg.game_mode}.json")
        self.updater = Updater(cfg.update_branch or DEFAULT_BRANCH)
        self.stop_event = threading.Event()
        self.scans: deque = deque(maxlen=25)
        self.update_status = {"running": False, "message": "", "error": None, "done": False}
        self.open_on_start = open_on_start
        self._lock = threading.Lock()
        self._clients = 0
        self._ever_connected = False
        self._last_left: Optional[float] = None
        self._started = time.time()
        self._displays = self._display_names()
        self.popup = None
        self.link = GameLink(self)
        self.server = self._bind(port or cfg.port, restarted)

    # -- setup ----------------------------------------------------------

    def _make_store(self, mode: str) -> DataStore:
        return DataStore(self.cfg_dir, mode, on_update=self._on_data)

    def _display_names(self) -> List[str]:
        try:
            ctl = self.app.controller
            return [d.name for d in ctl.color.displays()] if ctl.color else []
        except Exception:
            return []

    def _bind(self, port: int, restarted: bool) -> Server:
        if restarted:  # the previous copy is still shutting down
            for _ in range(80):
                if not find_running(port, 0.5):
                    break
                time.sleep(0.25)
        try:
            return Server(self, port)
        except OSError:
            log.info("Port %d is busy; using a random one", port)
            return Server(self, 0)

    # -- events ---------------------------------------------------------

    def publish(self, event: str, data) -> None:
        self.server.events.publish(event, data)

    def _on_data(self, name: str) -> None:
        if hasattr(self, "server"):
            snap = self.store.snapshot(name)
            self.publish("data", {"name": name, "updated": snap["updated"], "error": snap["error"]})

    def on_clients(self, count: int) -> None:
        with self._lock:
            self._clients = count
            if count:
                self._ever_connected = True
                self._last_left = None
            elif self._last_left is None:
                self._last_left = time.time()

    # -- state ----------------------------------------------------------

    def state(self) -> dict:
        app, cfg = self.app, self.app.config
        w, adj, prices = app.watcher, app.watcher.adjuster, app.prices
        last = self.updater.last_check or {}
        return {
            "watcher": w.status,
            "paused": w.paused,
            "preview": w.force,
            "profile": cfg.active_profile,
            "auto": {
                "enabled": cfg.auto.enabled,
                "scene": None if adj.scene is None else round(adj.scene, 3),
                "boost": adj.applied,
            },
            "prices": {"count": len(prices.items), "updated": prices.updated, "error": prices.error},
            "gameMode": cfg.game_mode,
            "update": {"available": bool(last.get("available")), "latest": last.get("latest")},
            "updating": dict(self.update_status),
        }

    def bootstrap(self) -> dict:
        cfg = self.app.config
        return {
            "appName": APP_NAME,
            "version": __version__,
            "platform": sys.platform,
            "settings": {"gameMode": cfg.game_mode, "keepRunning": cfg.keep_running},
            "progress": self.progress.snapshot(),
            "display": self.display_state(),
            "update": self.updater.last_check or None,
            "state": self.state(),
        }

    def items_payload(self) -> dict:
        prices = self.app.prices
        return {
            "updated": prices.updated,
            "error": prices.error,
            "items": [
                {
                    "id": i.id, "name": i.name, "short": i.short_name, "icon": i.icon,
                    "avg": i.avg24h, "low": i.last_low, "change": i.change48h, "base": i.base_price,
                    "slots": i.slots, "size": i.size, "trader": i.best_trader, "traderPrice": i.best_trader_price,
                    "banned": i.flea_banned, "tags": i.tags, "link": i.link, "wiki": i.wiki,
                }
                for i in prices.items
            ],
        }

    def item_detail(self, item_id: str) -> dict:
        try:
            return self.store.item(item_id)
        except ValueError:
            raise
        except Exception as exc:
            return {"item": None, "history": [], "error": str(exc)}

    def dataset(self, name: str, wait: float) -> dict:
        if name not in DATASETS:
            raise KeyError(f"unknown dataset {name}")
        return self.store.get(name, wait)

    def refresh_dataset(self, name: str) -> dict:
        if name == "prices":
            threading.Thread(target=self.app.prices.refresh, daemon=True).start()
            return {"name": "prices"}
        if name not in DATASETS:
            raise KeyError(f"unknown dataset {name}")
        self.store.refresh_async(name)
        return self.store.snapshot(name)

    def data_status(self) -> dict:
        prices = self.app.prices
        return {
            "datasets": self.store.status(),
            "prices": {"updated": prices.updated, "error": prices.error, "count": len(prices.items)},
        }

    def progress_snapshot(self) -> dict:
        return self.progress.snapshot()

    def progress_change(self, op) -> dict:
        snap = self.progress.apply(op)
        self.publish("progress", snap)
        return snap

    def recent_scans(self) -> list:
        return list(self.scans)

    # -- display --------------------------------------------------------

    def display_state(self) -> dict:
        app, cfg = self.app, self.app.config
        ctl = app.controller
        return {
            "profiles": {name: p.to_dict() for name, p in cfg.profiles.items()},
            "active": cfg.active_profile,
            "builtin": list(BUILTIN_PROFILES),
            "foregroundOnly": cfg.foreground_only,
            "auto": asdict(cfg.auto),
            "scan": asdict(cfg.scan),
            "paused": app.watcher.paused,
            "preview": app.watcher.force,
            "status": app.watcher.status,
            "amd": bool(ctl.color),
            "gamma": bool(ctl.gamma),
            "displays": self._displays,
            "hotkeys": cfg.hotkeys,
        }

    def display_change(self, op) -> dict:
        if not isinstance(op, dict):
            raise ValueError("bad request")
        app, cfg, kind = self.app, self.app.config, op.get("op")
        name = op.get("name")
        if kind == "select":
            if name not in cfg.profiles:
                raise KeyError(f"no profile {name}")
            app.select_profile(name)
        elif kind == "save_profile":
            if name not in cfg.profiles:
                raise KeyError(f"no profile {name}")
            v = op.get("profile") or {}
            cfg.profiles[name] = Profile(
                brightness=_opt(v.get("brightness"), -100, 100),
                contrast=_opt(v.get("contrast"), 0, 200),
                saturation=_opt(v.get("saturation"), 0, 200),
                hue=_opt(v.get("hue"), -180, 180),
                temperature=_opt(v.get("temperature"), 1000, 12000),
                gamma=round(_clamp(v.get("gamma", 1.0), 0.3, 3.0), 2),
            )
            app.save()
            app.watcher.refresh()
        elif kind == "new_profile":
            name = (name or "").strip()
            if not name or len(name) > 30:
                raise ValueError("profile name must be 1-30 characters")
            if name in cfg.profiles:
                raise ValueError(f"'{name}' already exists")
            base = cfg.profiles.get(op.get("copy_of")) or cfg.profile
            cfg.profiles[name] = Profile.from_dict(base.to_dict())
            app.select_profile(name)
        elif kind == "delete_profile":
            if name not in cfg.profiles or len(cfg.profiles) <= 1:
                raise ValueError("can't delete that profile")
            del cfg.profiles[name]
            if cfg.active_profile == name:
                cfg.active_profile = next(iter(cfg.profiles))
            app.save()
            app.watcher.refresh()
        elif kind == "reset_profile":
            if name not in BUILTIN_PROFILES:
                raise ValueError("only built-in profiles can be reset")
            cfg.profiles[name] = Profile.from_dict(BUILTIN_PROFILES[name].to_dict())
            app.save()
            app.watcher.refresh()
        elif kind == "preview":
            app.watcher.force = bool(op.get("on"))
            app.watcher.refresh()
        elif kind == "pause":
            app.watcher.paused = bool(op.get("on"))
            app.watcher.refresh()
        elif kind == "foreground_only":
            cfg.foreground_only = bool(op.get("on"))
            app.save()
            app.watcher.refresh()
        elif kind == "auto":
            s, a = op.get("settings") or {}, cfg.auto
            if "enabled" in s:
                a.enabled = bool(s["enabled"])
            for key, lo, hi, kind_ in (("dark_level", 0, 1, float), ("bright_level", 0, 1, float),
                                       ("gamma_boost", 0, 1.5, float), ("brightness_boost", 0, 60, int),
                                       ("response_seconds", 0.2, 10, float)):
                if key in s:
                    setattr(a, key, _clamp(s[key], lo, hi, kind_))
            app.save()
            app.watcher.refresh()
        elif kind == "scan":
            s, sc = op.get("settings") or {}, cfg.scan
            if "debug" in s:
                sc.debug = bool(s["debug"])
            if "popup_seconds" in s:
                sc.popup_seconds = _clamp(s["popup_seconds"], 2, 30)
            app.save()
        else:
            raise ValueError(f"unknown display change {kind!r}")
        state = self.display_state()
        self.publish("display", state)
        return state

    # -- settings -------------------------------------------------------

    def settings_change(self, body) -> dict:
        if not isinstance(body, dict):
            raise ValueError("bad request")
        cfg = self.app.config
        if "keepRunning" in body:
            cfg.keep_running = bool(body["keepRunning"])
            self.app.save()
        if "gameMode" in body:
            if body["gameMode"] not in ("regular", "pve"):
                raise ValueError("game mode must be regular or pve")
            self.set_game_mode(body["gameMode"])
        return self.bootstrap()

    def set_game_mode(self, mode: str) -> None:
        app, cfg = self.app, self.app.config
        if mode == cfg.game_mode:
            return
        cfg.game_mode = mode
        app.save()
        old = app.prices
        old.stop()
        app.prices = PriceDB(self.cfg_dir / f"prices_{mode}.json", mode)
        app.prices.start()
        app.scanner = None
        self.store = self._make_store(mode)
        self.progress = Progress(self.cfg_dir / f"progress_{mode}.json")
        log.info("Game mode -> %s", mode)
        self.publish("reload", {"gameMode": mode})

    # -- updates --------------------------------------------------------

    def update_check(self, force: bool = False) -> dict:
        last = self.updater.last_check
        if force or not last or time.time() - last.get("checked", 0) > 3600:
            last = self.updater.check()
        return last

    def update_apply(self) -> dict:
        if self.update_status["running"]:
            return dict(self.update_status)

        def say(message: str, **extra) -> None:
            self.update_status.update(message=message, **extra)
            self.publish("update", dict(self.update_status))

        def run() -> None:
            self.update_status.update(running=True, error=None, done=False)
            try:
                self.updater.apply(say)
                say("Update installed. Restarting...", done=True)
                time.sleep(1.0)
                self.restart()
            except Exception as exc:
                log.warning("Update failed: %s", exc)
                say("Update failed.", error=str(exc), running=False)

        threading.Thread(target=run, name="Update", daemon=True).start()
        return {"running": True, "message": "Starting update..."}

    def restart(self) -> None:
        self.publish("restarting", {})
        self.updater.restart(["gui", "--restarted", "--no-window", "--port", str(self.server.port)])
        self.stop_event.set()

    def quit(self) -> None:
        threading.Timer(0.3, self.stop_event.set).start()

    # -- price checks ---------------------------------------------------

    def item_needs(self, item_id: str, limit: int = 6) -> Optional[List[tuple]]:
        """Open quests and unbuilt hideout levels that still need an item;
        None when the quest/hideout data hasn't been downloaded."""
        tasks = self.store.snapshot("tasks")["data"]
        stations = self.store.snapshot("hideout")["data"]
        if tasks is None and stations is None:
            return None
        prog = self.progress.snapshot()
        done, faction = set(prog["tasks"]), prog["faction"]
        out = []
        for task in tasks or []:
            if task["id"] in done or task.get("factionName") not in (None, "Any", faction):
                continue
            count, fir = 0, False
            for obj in task.get("objectives") or []:
                if obj.get("type") not in NEED_TYPES:
                    continue
                ids = [i["id"] for i in obj.get("items") or [] if i] + (
                    [obj["markerItem"]["id"]] if obj.get("markerItem") else [])
                if item_id in ids:
                    count = max(count, obj.get("count") or 1)
                    fir = fir or bool(obj.get("foundInRaid"))
            if count:
                trader = (task.get("trader") or {}).get("name", "")
                out.append(("QUEST", f"{task['name']} x{count}{' FiR' if fir else ''}  ({trader})"))
        for station in stations or []:
            built = prog["hideout"].get(station["id"], 0)
            for level in station.get("levels") or []:
                if level["level"] <= built:
                    continue
                for req in level.get("itemRequirements") or []:
                    if (req.get("item") or {}).get("id") == item_id:
                        out.append(("HIDEOUT", f"{station['name']} {level['level']} x{req.get('count', 1)}"))
        if len(out) > limit:
            out = out[:limit] + [("", f"+{len(out) - limit} more")]
        return out

    def _scan_entry(self, result) -> dict:
        entry = {"time": time.time(), "lines": result.lines, "error": result.error, "item": None}
        if result.match:
            item = result.match.item
            entry.update(item={"id": item.id, "name": item.name, "short": item.short_name},
                         score=result.match.score, text=result.match.text)
        if result.debug_file:
            entry["debugFile"] = str(result.debug_file)
        return entry

    def _popup(self, result) -> None:
        if not self.popup:
            return
        seconds = self.app.config.scan.popup_seconds
        from .popup import ACCENT, BAD, GOOD, MUTED

        if result.match:
            item = result.match.item
            size = item.size or (f"{item.slots} slots" if item.slots > 1 else "1 slot")
            rows = []
            if item.flea_banned:
                rows.append(("Flea", "Can't be sold on flea", MUTED))
            else:
                low = f"   lowest {rub(item.last_low)}" if item.last_low else ""
                rows.append(("Flea", f"{rub(item.flea_price)}{low}", ACCENT))
            if item.best_trader:
                rows.append(("Trader", f"{item.best_trader}  {rub(item.best_trader_price)}", ""))
            rows.append(("Per slot", rub(item.per_slot), ""))
            rows.append(("Sell to", item.best_place, GOOD))
            needs = self.item_needs(item.id)
            if needs is None:  # quest data not downloaded: use the price list's notes
                notes = [("QUEST", q, ACCENT) for q in item.quests[:4]] + [("HIDEOUT", h, ACCENT) for h in item.hideout[:3]]
            else:
                notes = [(label, text, ACCENT) for label, text in needs] or [
                    ("", "Not needed for your open quests or hideout", MUTED)]
            footer = f"Read “{result.match.text}” · {result.match.score:.0%} sure"
            self.popup.show(item.name, f"{item.short_name}  ·  {size}", rows, notes, footer, result.cursor, seconds)
        elif result.error:
            self.popup.show("Price check failed", "", [], [("", result.error, BAD)], "", result.cursor, seconds)
        else:
            read = ", ".join(result.lines[:3])[:90] or "nothing"
            self.popup.show("Couldn't identify the item", "", [], [
                ("", f"Read: {read}", MUTED),
                ("", "Hover until the name tooltip shows, then press Ctrl+Alt+P again.", MUTED),
            ], "", result.cursor, seconds)

    # -- background loops -----------------------------------------------

    def _scan_loop(self) -> None:
        import queue

        while not self.stop_event.is_set():
            try:
                result = self.app.scan_results.get(timeout=0.5)
            except queue.Empty:
                continue
            entry = self._scan_entry(result)
            self.scans.appendleft(entry)
            self.publish("scan", entry)
            try:
                self._popup(result)
            except Exception:
                log.exception("popup failed")

    def _monitor_loop(self) -> None:
        last_state, reopened, last_check = None, False, 0.0
        while not self.stop_event.wait(0.5):
            state = self.state()
            if state != last_state:
                self.publish("state", state)
                last_state = state
            now = time.time()
            with self._lock:
                clients, ever, left = self._clients, self._ever_connected, self._last_left
            if not clients:
                if ever and left and now - left > CLOSE_GRACE and not self.app.config.keep_running:
                    log.info("Window closed; quitting")
                    self.stop_event.set()
                elif not ever and not reopened and now - self._started > REOPEN_AFTER:
                    reopened = True
                    open_window(self.server.url)
            if now - last_check > UPDATE_CHECK_EVERY and now - self._started > 5:
                last_check = now
                threading.Thread(target=self.update_check, kwargs={"force": True}, daemon=True).start()

    def run(self) -> None:
        self.app.start()
        self.server.start()
        for target, name in ((self._scan_loop, "ScanResults"), (self._monitor_loop, "Monitor")):
            threading.Thread(target=target, name=name, daemon=True).start()
        self.link.start_logs()
        threading.Thread(target=self.link.auto_import, name="TrackerImport", daemon=True).start()
        if self.open_on_start:
            log.info("Opened %s", open_window(self.server.url))
        from .popup import create_host

        self.popup = create_host()
        try:
            if self.popup:
                self.popup.run(self.stop_event)
            else:
                while not self.stop_event.wait(0.5):
                    pass
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self.stop_event.set()
        self.link.stop_logs()
        try:
            self.server.stop()
        except Exception:
            pass
        self.app.shutdown()


def main(open_on_start: bool = True, restarted: bool = False, port: Optional[int] = None) -> int:
    port = port or load_config().port
    if not restarted:
        running = find_running(port)
        if running:  # already open: just show another window
            log.info("Already running (version %s); opening a window", running.get("version"))
            open_window(f"http://127.0.0.1:{port}/")
            return 0
    WebApp(open_on_start=open_on_start, restarted=restarted, port=port).run()
    return 0
