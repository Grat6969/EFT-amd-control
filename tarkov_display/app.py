"""Wires config, display controller, game watcher and hotkeys together."""

from __future__ import annotations

import atexit
import logging
import queue
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

from .controller import DisplayController
from .prices import PriceDB
from .profiles import Config, default_config_dir, load_config, save_config
from .watcher import GameWatcher

log = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> Path:
    log_dir = default_config_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "tarkov_display.log"
    handlers = [logging.FileHandler(path, encoding="utf-8")]
    if sys.stderr is not None:  # None in the windowed .exe
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )
    return path


class App:
    def __init__(self, config_path: Optional[Path] = None, on_status: Optional[Callable[[str], None]] = None):
        self.config_path = config_path or default_config_dir() / "config.json"
        self.config: Config = load_config(self.config_path)
        self.controller = DisplayController.create(self.config_path.parent / "original_settings.json")
        self.controller.recover()
        self.watcher = GameWatcher(self.controller, self.config, on_change=on_status)
        self.prices = PriceDB(self.config_path.parent / f"prices_{self.config.game_mode}.json", self.config.game_mode)
        self.scanner = None
        self.scan_results: "queue.Queue" = queue.Queue()
        self._scanning = threading.Lock()
        self.hotkeys = None
        atexit.register(self.shutdown)

    def save(self) -> None:
        save_config(self.config, self.config_path)

    def select_profile(self, name: str) -> None:
        if name not in self.config.profiles:
            return
        self.config.active_profile = name
        self.save()
        log.info("Profile -> %s", name)
        self.watcher.refresh()

    def select_profile_index(self, index: int) -> None:
        names = self.config.profile_names()
        if 0 <= index < len(names):
            self.select_profile(names[index])

    def toggle_pause(self) -> None:
        self.watcher.paused = not self.watcher.paused
        log.info("Paused" if self.watcher.paused else "Resumed")
        self.watcher.refresh()

    def toggle_auto(self) -> None:
        self.config.auto.enabled = not self.config.auto.enabled
        self.save()
        log.info("Auto-adjust %s", "on" if self.config.auto.enabled else "off")
        self.watcher.refresh()

    def request_scan(self) -> None:
        """Price-check the item under the cursor (runs off the calling thread)."""
        if not self._scanning.acquire(blocking=False):
            return  # a scan is already running
        threading.Thread(target=self._scan, name="Scan", daemon=True).start()

    def _scan(self) -> None:
        from .scanner import ItemScanner, ScanResult

        try:
            if self.scanner is None:
                self.scanner = ItemScanner(self.prices, self.config.scan, self.config_path.parent / "scans")
            result = self.scanner.scan()
        except Exception as exc:
            log.warning("Scan failed: %s", exc)
            result = ScanResult(None, error=str(exc))
        finally:
            self._scanning.release()
        self.scan_results.put(result)

    def start(self) -> None:
        self.watcher.start()
        self.prices.start()
        if self.config.hotkeys:
            from .hotkeys import Hotkeys

            self.hotkeys = Hotkeys(self.select_profile_index, self.toggle_pause, self.toggle_auto, self.request_scan)
            self.hotkeys.start()

    def shutdown(self) -> None:
        if self.hotkeys:
            self.hotkeys.stop()
            self.hotkeys = None
        self.prices.stop()
        self.watcher.stop()
        self.controller.restore()
