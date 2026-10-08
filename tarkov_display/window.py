"""Opens the app's page in its own window.

Uses Microsoft Edge (or Chrome) in "app" mode: a plain window with no tabs
or address bar. Edge comes with Windows 10 and 11, so nothing extra needs
installing. Falls back to the default browser.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import List, Optional

log = logging.getLogger(__name__)


def browser_candidates() -> List[Path]:
    roots = [os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    paths = []
    for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
        for root in roots:
            if root:
                paths.append(Path(root) / rel)
    return paths


def find_app_browser() -> Optional[Path]:
    for path in browser_candidates():
        if path.exists():
            return path
    return None


def open_window(url: str) -> str:
    """Open ``url``; returns how it was opened."""
    if sys.platform == "win32":
        exe = find_app_browser()
        if exe:
            try:
                subprocess.Popen(
                    [str(exe), f"--app={url}", "--window-size=1480,940", "--no-first-run",
                     "--no-default-browser-check"],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return f"app window ({exe.name})"
            except OSError as exc:
                log.warning("Could not start %s: %s", exe, exc)
    webbrowser.open(url)
    return "default browser"
