"""Opens the app's page in its own window.

Uses Microsoft Edge (or Chrome) in "app" mode: a plain window with no tabs
or address bar. Edge comes with Windows 10 and 11, so nothing extra needs
installing. Falls back to the default browser.
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)

WINDOW_SIZE = (1480, 940)


def fit_window(size: Tuple[int, int], work_area: Tuple[int, int], dpi: int) -> Tuple[int, int]:
    """``size`` (in DIPs, as the browser takes it), shrunk to fit a screen
    work area given in pixels at ``dpi``, with a little room to spare."""
    scale = max(1, dpi or 96) / 96
    return (min(size[0], int(work_area[0] / scale * 0.94)), min(size[1], int(work_area[1] / scale * 0.94)))


def window_size() -> Tuple[int, int]:
    """The app window's size: the default, or less on a small or scaled screen."""
    if sys.platform != "win32":
        return WINDOW_SIZE
    try:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        rect = wintypes.RECT()
        if not user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA, main screen
            return WINDOW_SIZE
        try:
            dpi = user32.GetDpiForSystem()
        except AttributeError:  # before Windows 10 1607
            dpi = 96
        return fit_window(WINDOW_SIZE, (rect.right - rect.left, rect.bottom - rect.top), dpi)
    except Exception:
        return WINDOW_SIZE


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
                width, height = window_size()
                subprocess.Popen(
                    [str(exe), f"--app={url}", f"--window-size={width},{height}", "--no-first-run",
                     "--no-default-browser-check"],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return f"app window ({exe.name})"
            except OSError as exc:
                log.warning("Could not start %s: %s", exe, exc)
    webbrowser.open(url)
    return "default browser"
