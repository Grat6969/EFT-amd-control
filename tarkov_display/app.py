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


LOG_MAX_BYTES = 5 * 1024 * 1024


def setup_logging(verbose: bool = False) -> Path:
    log_dir = default_config_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "tarkov_display.log"
    try:
        fresh = path.stat().st_size > LOG_MAX_BYTES  # start over instead of growing forever
    except OSError:
        fresh = False
    handlers = [logging.FileHandler(path, mode="w" if fresh else "a", encoding="utf-8")]
    if sys.stderr is not None:  # None under pythonw and in the windowed .exe
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )
    # Without a console, errors nobody catches would vanish: log them.
    def log_uncaught(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            return sys.__excepthook__(exc_type, exc, tb)
        log.critical("Unexpected error", exc_info=(exc_type, exc, tb))

    def log_thread_error(args):
        if not issubclass(args.exc_type, SystemExit):
            name = args.thread.name if args.thread else "?"
            log.critical("Unexpected error in thread %s", name, exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = log_uncaught
    threading.excepthook = log_thread_error
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
        self.hover = None
        # Set by the app window (webapp.py); the defaults suit the command line.
        self.on_hover_result: Callable = self.scan_results.put
        self.on_hover_leave: Callable[[], None] = lambda: None
        self.on_hover_toggled: Callable[[bool], None] = lambda on: None
        self.popup_rect: Callable[[], Optional[tuple]] = lambda: None  # our popup, left out of captures
        from .ai import AiReader

        self.ai = AiReader(lambda: self.config.ai, self.ai_key)  # Claude, if you turn it on
        atexit.register(self.shutdown)

    def ai_key(self) -> str:
        """The saved Anthropic API key, or "" (none, or saved by another Windows account)."""
        from . import secretstore

        try:
            return secretstore.unprotect(self.config.ai.key)
        except Exception as exc:
            log.warning("Couldn't read the saved Anthropic API key: %s", exc)
            return ""

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

    def toggle_hover(self) -> None:
        self.config.scan.hover = not self.config.scan.hover
        self.save()
        log.info("Hover price check %s", "on" if self.config.scan.hover else "off")
        self.on_hover_toggled(self.config.scan.hover)

    def request_scan(self) -> None:
        """Price-check the item under the cursor (runs off the calling thread)."""
        threading.Thread(target=self._scan, name="Scan", daemon=True).start()

    def _scan(self) -> None:
        result = self.scan_now(wait=True)
        if result is not None:
            self.scan_results.put(result)

    def use_scanner(self, fn: Callable, wait: bool = False):
        """Run ``fn(scanner)``, one use of the screen reader at a time: with
        ``wait``, waits for a running one to finish (Ctrl+Alt+P), else returns
        None at once (hover checks just try again a moment later). Errors,
        such as no text reader being installed, are raised."""
        from .scanner import ItemScanner

        got = self._scanning.acquire(timeout=5) if wait else self._scanning.acquire(blocking=False)
        if not got:
            return None
        try:
            if self.scanner is None:
                self.scanner = ItemScanner(self.prices, self.config.scan, self.config_path.parent / "scans")
                self.scanner.ai = self.ai
            return fn(self.scanner)
        finally:
            self._scanning.release()

    def scan_now(self, wait: bool = False, quiet: bool = False):
        """Price-check the item under the cursor now (None if busy, see use_scanner)."""
        from .scanner import ScanResult

        popup = self.popup_rect()
        try:
            return self.use_scanner(lambda s: s.scan(mask=[popup] if popup else (), quiet=quiet), wait)
        except Exception as exc:
            (log.debug if quiet else log.warning)("Scan failed: %s", exc)
            return ScanResult(None, error=str(exc))

    def start(self) -> None:
        self.watcher.start()
        self.prices.start()
        if sys.platform != "win32":
            return
        if self.config.hotkeys:
            from .hotkeys import Hotkeys

            self.hotkeys = Hotkeys(self.select_profile_index, self.toggle_pause, self.toggle_auto, self.request_scan,
                                   on_toggle_hover=self.toggle_hover)
            self.hotkeys.start()
        try:
            from .hover import GameFocus, HoverWatcher, ScannerEyes, win_pointer

            # Idles until hover price check is turned on.
            self.hover = HoverWatcher(
                lambda: self.config.scan, GameFocus(lambda: self.config.process_names), win_pointer(),
                ScannerEyes(self.use_scanner),
                on_result=lambda result: self.on_hover_result(result), on_leave=lambda: self.on_hover_leave(),
                popup_rect=lambda: self.popup_rect())
            self.hover.start()
        except Exception as exc:  # the rest of the app works without it
            log.warning("Hover price check unavailable: %s", exc)
            self.hover = None

    def shutdown(self) -> None:
        if self.hover:
            self.hover.stop()
            self.hover = None
        if self.hotkeys:
            self.hotkeys.stop()
            self.hotkeys = None
        self.prices.stop()
        self.watcher.stop()
        self.controller.restore()
