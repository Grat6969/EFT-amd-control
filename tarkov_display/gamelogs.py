"""Reads Escape from Tarkov's own log files (read-only).

The game writes plain-text logs to <install folder>/Logs, one folder per
game session. This module finds that folder, follows the current session's
logs as they grow, and turns a few kinds of lines into events:

  * session mode (PvP / PvE)
  * quest started / failed / finished
  * loading into a raid (which map)
  * a flea market item sold

It only ever opens the log files for reading. It never touches the game's
memory, process or other files.
"""

from __future__ import annotations

import codecs
import json
import logging
import os
import re
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

log = logging.getLogger(__name__)

STEAM_APP_ID = "3932890"
UNINSTALL_KEYS = [
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\EscapeFromTarkov",
    rf"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App {STEAM_APP_ID}",
]
ROUBLES = "5449016a4bdc2d6f028b456f"
FLEA_SOLD_TEMPLATE = "5bdabfb886f7743e152e867e"
QUEST_STATUS = {10: "started", 11: "failed", 12: "finished"}
MODES = {"regular": "regular", "pvp": "regular", "pve": "pve", "pvpseason": "seasonal", "seasonal": "seasonal",
         "szn": "seasonal"}

# "2025-11-20 19:45:12.345 +01:00|1.0.0.1.39390|Info|application|Session mode: Regular"
HEADER = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(?:\.\d+)?(?: [+-]\d{2}:\d{2})?\|(.*)$")
LOG_FILE = re.compile(r"(application|notifications)(?:_\d+)?\.log$", re.IGNORECASE)
SESSION_FOLDER = re.compile(r"^log_(\d{4})\.(\d{1,2})\.(\d{1,2})_(\d{1,2})-(\d{1,2})-(\d{1,2})")


@dataclass
class Event:
    kind: str                 # "mode" | "quest" | "raid" | "raid_end" | "flea"
    time: str                 # "2025-11-20 19:45:12" as written in the log (local time)
    data: Dict = field(default_factory=dict)
    mode: Optional[str] = None  # game mode the event happened in, when known

    def to_dict(self) -> dict:
        return {"kind": self.kind, "time": self.time, "mode": self.mode, **self.data}


# -- finding the logs ---------------------------------------------------------------

def _registry_values(paths: Iterable[str], names: Iterable[str]) -> List[str]:
    try:
        import winreg
    except ImportError:
        return []
    found = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (0, winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            for path in paths:
                try:
                    with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view) as key:
                        for name in names:
                            try:
                                value, _ = winreg.QueryValueEx(key, name)
                            except OSError:
                                continue
                            value = value.strip().strip('"') if isinstance(value, str) else ""
                            if value and value not in found:
                                found.append(value)
                except OSError:
                    continue
    return found


def _steam_install_dirs() -> List[Path]:
    dirs = []
    for root in _registry_values([r"SOFTWARE\Valve\Steam"], ["SteamPath", "InstallPath"]):
        root_path = Path(root)
        libraries = [root_path]
        vdf = root_path / "steamapps" / "libraryfolders.vdf"
        try:
            for match in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="replace")):
                libraries.append(Path(match.group(1).replace("\\\\", "\\")))
        except OSError:
            pass
        for lib in libraries:
            manifest = lib / "steamapps" / f"appmanifest_{STEAM_APP_ID}.acf"
            try:
                m = re.search(r'"installdir"\s+"([^"]+)"', manifest.read_text(encoding="utf-8", errors="replace"))
                if m:
                    dirs.append(lib / "steamapps" / "common" / m.group(1))
            except OSError:
                pass
            dirs.append(lib / "steamapps" / "common" / "Escape from Tarkov")
    return dirs


def logs_folder_in(install: Path) -> Optional[Path]:
    for candidate in (install / "Logs", install / "build" / "Logs"):
        if candidate.is_dir():
            return candidate
    return None


def find_logs_folder() -> Optional[Path]:
    """The game's Logs folder, from the launcher or Steam install, if found."""
    if sys.platform != "win32":
        return None
    installs = [Path(p) for p in _registry_values(UNINSTALL_KEYS, ["InstallLocation"])] + _steam_install_dirs()
    for install in installs:
        folder = logs_folder_in(install)
        if folder:
            return folder
    return None


def session_time(folder: Path) -> Optional[tuple]:
    """When a session started, from its folder name ("log_2025.11.20_9-45-12_<version>";
    the hour isn't zero-padded, so names don't sort as text)."""
    m = SESSION_FOLDER.match(folder.name)
    return tuple(int(g) for g in m.groups()) if m else None


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def session_folders(logs: Path) -> List[Path]:
    """Session folders, oldest first, ordered by the time in their names like
    TarkovMonitor does. Other folders are ignored unless no name has a time."""
    try:
        folders = [p for p in logs.iterdir() if p.is_dir()]
    except OSError:
        return []
    named = sorted((session_time(p), p.name, p) for p in folders if session_time(p))
    if named:
        return [p for _, _, p in named]
    return sorted(folders, key=lambda p: (_mtime(p), p.name))


def log_files(session: Path) -> List[Path]:
    try:
        return sorted(p for p in session.iterdir() if p.is_file() and LOG_FILE.search(p.name))
    except OSError:
        return []


# -- parsing ---------------------------------------------------------------------------

def split_entries(text: str) -> List[tuple]:
    """(date time, header text, body) for each entry. The body holds any lines
    after the header, e.g. a JSON block."""
    entries = []
    for line in text.splitlines():
        m = HEADER.match(line.lstrip("﻿"))
        if m:
            entries.append([f"{m.group(1)} {m.group(2)}", m.group(3), []])
        elif entries:
            entries[-1][2].append(line)
    return [(t, header, "\n".join(body).strip()) for t, header, body in entries]


def _json(body: str):
    if not body.startswith("{"):
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None


def parse_entry(when: str, header: str, body: str) -> Optional[Event]:
    if "Session mode:" in header:
        m = re.search(r"Session mode:\s*([^\s|]+)", header)
        mode = MODES.get(m.group(1).lower(), "unknown") if m else "unknown"
        return Event("mode", when, {"gameMode": mode}, mode)
    if "TRACE-NetworkGameCreate profileStatus" in header:
        loc = re.search(r"Location:\s*([^,'\s]+)", header)
        raid = re.search(r"shortId:\s*([A-Za-z0-9]+)", header)
        return Event("raid", when, {
            "map": loc.group(1) if loc else None,
            "online": "RaidMode: Online" in header,
            "raidId": raid.group(1) if raid else None,
        })
    if "Got notification | UserMatchOver" in header:
        data = _json(body) or {}
        return Event("raid_end", when, {"map": data.get("location"), "raidId": data.get("shortId")})
    if "Got notification | ChatMessageReceived" in header:
        data = _json(body)
        message = (data or {}).get("message") or {}
        kind = message.get("type")
        template = str(message.get("templateId") or "")
        if kind in QUEST_STATUS and template:
            return Event("quest", when, {"questId": template.split(" ")[0], "status": QUEST_STATUS[kind]})
        if kind == 4 and template.split(" ")[0] == FLEA_SOLD_TEMPLATE:
            sold = message.get("systemData") or {}
            roubles = sum(
                ((i.get("upd") or {}).get("StackObjectsCount") or 0)
                for i in ((message.get("items") or {}).get("data") or [])
                if i.get("_tpl") == ROUBLES
            )
            return Event("flea", when, {"itemId": sold.get("soldItem"), "count": sold.get("itemCount") or 1,
                                        "buyer": sold.get("buyerNickname"), "roubles": roubles})
    return None


def parse_text(text: str, mode: Optional[str] = None) -> List[Event]:
    """Events in a block of log text; ``mode`` is the session mode so far."""
    events = []
    for when, header, body in split_entries(text):
        ev = parse_entry(when, header, body)
        if not ev:
            continue
        if ev.kind == "mode":
            mode = ev.mode
        else:
            ev.mode = mode
        events.append(ev)
    return events


def _entry_complete(header: str, body: str) -> bool:
    """Can the last entry in a file be handled yet, or might more of it follow?"""
    if body:
        return _json(body) is not None
    return "Got notification" not in header  # notifications are followed by JSON


# -- following the current session -------------------------------------------------------

class _FileTail:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.offset = 0
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.buffer = ""

    def read_new(self) -> str:
        try:
            size = self.path.stat().st_size
        except OSError:
            return ""
        if size < self.offset:  # file was replaced
            self.offset, self.buffer = 0, ""
            self.decoder.reset()
        if size == self.offset:
            return ""
        with open(self.path, "rb") as fh:  # shared read; the game keeps writing
            fh.seek(self.offset)
            data = fh.read(size - self.offset)
        self.offset += len(data)
        return self.decoder.decode(data)

    def complete_text(self) -> str:
        """New text that forms whole entries; an unfinished last entry waits."""
        self.buffer += self.read_new()
        if not self.buffer:
            return ""
        starts = [m.start() for m in re.finditer(r"(?m)^﻿?\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", self.buffer)]
        if not starts:
            return ""
        last = starts[-1]
        tail = self.buffer[last:]
        entries = split_entries(tail)
        if entries and tail.endswith("\n") and _entry_complete(entries[0][1], entries[0][2]):
            done, self.buffer = self.buffer, ""
        else:
            done, self.buffer = self.buffer[:last], tail
        return done


class LogFollower:
    """Follows the newest session folder and reports events.

    The newest session already on disk is read in full first (``history``
    events); after that only new lines produce live events.
    """

    def __init__(self, folder: Path, on_event: Callable[[Event, bool], None], poll: float = 2.0) -> None:
        self.folder = folder
        self.on_event = on_event
        self.poll = poll
        self.session: Optional[Path] = None
        self.modes: List[tuple] = []  # (time, mode) changes seen in this session
        self.tails: Dict[Path, _FileTail] = {}
        self.last_event: Optional[Event] = None
        self.error: Optional[str] = None
        self._stop = threading.Event()
        self._check_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="GameLogs", daemon=True)
        self._thread.start()

    def stop(self, wait: bool = True) -> None:
        """Stop following; by default waits for a read in progress to finish
        so a replacement follower can't report the same lines twice."""
        self._stop.set()
        if wait and self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=10)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.check()
                self.error = None
            except Exception as exc:  # keep following whatever happens
                self.error = str(exc)
                log.debug("game log reader: %s", exc, exc_info=True)
            self._stop.wait(self.poll)

    @property
    def mode(self) -> Optional[str]:
        """The game mode Tarkov is in now, as far as the logs say."""
        return self.modes[-1][1] if self.modes else None

    def mode_at(self, when: str) -> Optional[str]:
        """Mode in effect at a log time. Files are read one after another, so
        a quest in the notifications log must not pick up a mode switch the
        application log recorded later."""
        earlier = [m for t, m in self.modes if t <= when]
        if earlier:
            return earlier[-1]
        return self.modes[0][1] if self.modes else None

    def check(self) -> None:
        with self._check_lock:
            self._check()

    def _check(self) -> None:
        sessions = session_folders(self.folder)
        if not sessions:
            return
        newest = sessions[-1]
        history = False
        if newest != self.session:
            history = self.session is None  # first look: what's there already is history
            self.session, self.tails, self.modes = newest, {}, []
            log.info("Following game logs in %s", newest.name)
        files = log_files(newest)
        # Application log first: it carries the session mode.
        files.sort(key=lambda p: (0 if "application" in p.name.lower() else 1, p.name))
        for path in files:
            tail = self.tails.setdefault(path, _FileTail(path))
            text = tail.complete_text()
            if not text:
                continue
            for ev in parse_text(text):
                if ev.kind == "mode":
                    self.modes.append((ev.time, ev.mode))
                    self.modes.sort(key=lambda m: m[0])
                else:
                    ev.mode = self.mode_at(ev.time)
                self.last_event = ev
                self.on_event(ev, history)


# -- reading old sessions ------------------------------------------------------------------

APP_LOG_SCAN_BYTES = 4 * 1024 * 1024    # the session mode is near the start
NOTIFICATION_SCAN_BYTES = 64 * 1024 * 1024


def _read_head(path: Path, limit: int) -> str:
    try:
        with open(path, "rb") as fh:
            return fh.read(limit).decode("utf-8", errors="replace")
    except OSError:
        return ""


def scan_history(folder: Path) -> dict:
    """Quests finished in every session still on disk, per game mode."""
    result = {"sessions": 0, "first": None, "last": None, "modes": {}}
    for session in session_folders(folder):
        files = log_files(session)
        modes = []  # (time, mode) in the order they were chosen
        for path in (p for p in files if "application" in p.name.lower()):
            modes += [(ev.time, ev.mode) for ev in parse_text(_read_head(path, APP_LOG_SCAN_BYTES)) if ev.kind == "mode"]
        modes.sort()
        quests = []
        for path in (p for p in files if "notifications" in p.name.lower()):
            quests += [ev for ev in parse_text(_read_head(path, NOTIFICATION_SCAN_BYTES)) if ev.kind == "quest"]
        if not quests and not modes:
            continue
        result["sessions"] += 1
        result["first"] = result["first"] or session.name
        result["last"] = session.name
        for ev in quests:
            earlier = [m for t, m in modes if t <= ev.time]
            mode = earlier[-1] if earlier else (modes[0][1] if modes else "regular")
            bucket = result["modes"].setdefault(mode, {"finished": [], "failed": [], "started": []})
            if ev.data["questId"] not in bucket[ev.data["status"]]:
                bucket[ev.data["status"]].append(ev.data["questId"])
    return result


def default_folder(custom: str = "") -> Optional[Path]:
    if custom:
        path = Path(os.path.expandvars(custom)).expanduser()
        return path if path.is_dir() else None
    return find_logs_folder()
