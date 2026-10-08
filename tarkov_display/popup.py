"""The price-check popup shown next to the mouse in game (Ctrl+Alt+P).

A small always-on-top window that never takes focus, so the game keeps
your mouse and keyboard. Drawn with Tk, which comes with Python.
"""

from __future__ import annotations

import ctypes
import logging
import queue
import sys
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)

BG = "#121518"
PANEL = "#181c20"
BORDER = "#c8b27d"
TEXT = "#e6dfcd"
MUTED = "#8f8b7e"
ACCENT = "#d8c48f"
GOOD = "#7cc47f"
BAD = "#e0675f"

Line = Tuple[str, str, str]  # (label, value, colour)


def _font(size: int, bold: bool = False):
    family = "Bahnschrift" if sys.platform == "win32" else "Helvetica"
    return (family, size, "bold" if bold else "normal")


def place_beside(cursor, size, bounds, gap: int = 30):
    """Top-left corner for the popup: beside the cursor (away from the game's
    own tooltip), kept inside the monitor ``bounds`` = (left, top, right, bottom)."""
    (x, y), (w, h), (left, top, right, bottom) = cursor, size, bounds
    px = x + gap if x + gap + w <= right else x - gap - w
    py = y - h - gap
    px = max(left, min(px, right - w))
    py = max(top, min(py, bottom - h))
    return px, py


def monitor_bounds(point):
    """Work area of the monitor under ``point`` (Windows), or None."""
    if sys.platform != "win32":
        return None
    try:
        from ctypes import wintypes

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        user32 = ctypes.windll.user32
        user32.MonitorFromPoint.restype = wintypes.HMONITOR
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
        monitor = user32.MonitorFromPoint(wintypes.POINT(int(point[0]), int(point[1])), 2)  # nearest
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(info)
        if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        r = info.rcWork
        return r.left, r.top, r.right, r.bottom
    except Exception:
        return None


def make_dpi_aware() -> None:
    """Use real pixels everywhere (mouse position, screenshots, popup position).
    Must run before any window is created, or they disagree on scaled displays."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class PopupHost:
    """Owns the hidden Tk root on the main thread and shows popups that
    other threads ask for via ``show()``."""

    def __init__(self) -> None:
        import tkinter as tk

        self.tk = tk
        self.root = tk.Tk()
        self.root.withdraw()
        self.requests: "queue.Queue" = queue.Queue()
        self.win = None
        self._hide_job = None

    def show(self, title: str, subtitle: str, rows: List[Line], notes: List[Line], footer: str,
             cursor: Tuple[int, int], seconds: float) -> None:
        self.requests.put((title, subtitle, rows, notes, footer, cursor, seconds))

    def run(self, stop) -> None:
        def poll():
            if stop.is_set():
                self.root.quit()
                return
            try:
                while True:
                    self._show(*self.requests.get_nowait())
            except queue.Empty:
                pass
            except Exception:
                log.exception("popup failed")
            self.root.after(100, poll)

        self.root.after(100, poll)
        self.root.mainloop()
        try:
            self.root.destroy()
        except Exception:
            pass

    def _show(self, title, subtitle, rows, notes, footer, cursor, seconds) -> None:
        tk = self.tk
        self.hide()
        win = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", 0.97)
        except tk.TclError:
            pass
        outer = tk.Frame(win, bg=BORDER, padx=1, pady=1)
        outer.pack()
        body = tk.Frame(outer, bg=BG, padx=14, pady=10)
        body.pack()
        tk.Frame(body, bg=BORDER, height=2, width=40).pack(anchor="w", pady=(0, 6))
        tk.Label(body, text=title, bg=BG, fg=ACCENT, font=_font(13, True), anchor="w", justify="left",
                 wraplength=380).pack(anchor="w")
        if subtitle:
            tk.Label(body, text=subtitle, bg=BG, fg=MUTED, font=_font(9), anchor="w").pack(anchor="w", pady=(0, 6))

        grid = tk.Frame(body, bg=BG)
        grid.pack(anchor="w", fill="x")
        for r, (label, value, colour) in enumerate(rows):
            tk.Label(grid, text=label.upper(), bg=BG, fg=MUTED, font=_font(8, True), anchor="w").grid(
                row=r, column=0, sticky="w", padx=(0, 14), pady=1)
            tk.Label(grid, text=value, bg=BG, fg=colour or TEXT, font=_font(11, r == 0), anchor="w").grid(
                row=r, column=1, sticky="w", pady=1)

        if notes:
            box = tk.Frame(body, bg=PANEL, padx=8, pady=6)
            box.pack(anchor="w", fill="x", pady=(8, 0))
            for label, value, colour in notes:
                line = tk.Frame(box, bg=PANEL)
                line.pack(anchor="w", fill="x")
                if label:
                    tk.Label(line, text=label, bg=PANEL, fg=colour or ACCENT, font=_font(9, True)).pack(side="left")
                tk.Label(line, text=value, bg=PANEL, fg=TEXT, font=_font(9), justify="left",
                         wraplength=360).pack(side="left", padx=(4, 0))
        if footer:
            tk.Label(body, text=footer, bg=BG, fg=MUTED, font=_font(8), anchor="w").pack(anchor="w", pady=(8, 0))

        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        bounds = monitor_bounds(cursor) or (0, 0, win.winfo_screenwidth(), win.winfo_screenheight())
        px, py = place_beside(cursor, (w, h), bounds)
        win.geometry(f"+{px}+{py}")
        self.win = win
        self._show_no_activate(win)
        self._hide_job = self.root.after(int(seconds * 1000), self.hide)

    @staticmethod
    def _show_no_activate(win) -> None:
        if sys.platform != "win32":
            win.deiconify()
            return
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_NOACTIVATE = 0x08000000
        WS_EX_TOPMOST = 0x00000008
        SW_SHOWNOACTIVATE = 4
        user32 = ctypes.windll.user32
        hwnd = int(win.wm_frame(), 16)
        user32.GetWindowLongW.restype = ctypes.c_long
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST)
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)

    def hide(self) -> None:
        if self._hide_job:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None
        if self.win is not None:
            self.win.destroy()
            self.win = None


def create_host() -> Optional[PopupHost]:
    try:
        return PopupHost()
    except Exception as exc:  # no tkinter, or no display
        log.warning("In-game price popup unavailable: %s", exc)
        return None
