"""Prices tab and the price-check popup."""

from __future__ import annotations

import ctypes
import sys
import tkinter as tk
import webbrowser
from tkinter import ttk
from typing import Dict, List, Optional

from .prices import Item, PriceDB, age_text, rub


COLUMNS = [
    # id, heading, width, sort key
    ("name", "Item", 260, lambda i: i.name.lower()),
    ("flea", "Flea (24h avg)", 110, lambda i: i.flea_price or 0),
    ("low", "Lowest now", 100, lambda i: i.last_low or 0),
    ("trader", "Best trader", 150, lambda i: i.best_trader_price),
    ("slot", "Per slot", 100, lambda i: i.per_slot),
    ("needed", "Needed for", 220, lambda i: i.needed_for),
]


class PricesTab:
    def __init__(self, parent, prices: PriceDB) -> None:
        self.prices = prices
        self.frame = ttk.Frame(parent, padding=10)
        self._rows: Dict[str, Item] = {}
        self._items: List[Item] = []
        self._sort = ("flea", True)

        top = ttk.Frame(self.frame)
        top.pack(fill="x")
        ttk.Label(top, text="Search").pack(side="left")
        self.query = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.query, width=40)
        entry.pack(side="left", padx=6)
        self.query.trace_add("write", lambda *_: self.search())
        ttk.Button(top, text="Update prices", command=self._refresh).pack(side="right")
        self.info = tk.StringVar()
        ttk.Label(top, textvariable=self.info, foreground="gray").pack(side="right", padx=8)

        table = ttk.Frame(self.frame)
        table.pack(fill="both", expand=True, pady=(8, 0))
        self.tree = ttk.Treeview(table, columns=[c[0] for c in COLUMNS], show="headings", height=16)
        for cid, heading, width, _ in COLUMNS:
            self.tree.heading(cid, text=heading, command=lambda c=cid: self._sort_by(c))
            self.tree.column(cid, width=width, anchor="w" if cid in ("name", "trader", "needed") else "e")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._open_wiki)

        ttk.Label(
            self.frame, foreground="gray",
            text="Prices from tarkov.dev, before flea fees. Double-click a row to open it on tarkov.dev. "
                 "In game: hover an item and press Ctrl+Alt+P.",
        ).pack(anchor="w", pady=(6, 0))
        self.update_info()

    def update_info(self) -> None:
        if self.prices.error and not self.prices.items:
            self.info.set(f"Couldn't download prices: {self.prices.error[:150]} (retrying every minute)")
        elif self.prices.error:
            self.info.set(
                f"{len(self.prices.items)} items, updated {age_text(self.prices.age)} "
                "(tarkov.dev not responding, retrying)"
            )
        else:
            self.info.set(f"{len(self.prices.items)} items, updated {age_text(self.prices.age)}")

    def _refresh(self) -> None:
        import threading

        self.info.set("updating...")
        threading.Thread(target=self.prices.refresh, daemon=True).start()

    def search(self, query: Optional[str] = None) -> None:
        if query is not None:
            self.query.set(query)  # triggers search() again through the trace
            return
        self._items = self.prices.search(self.query.get(), limit=200)
        self._render()

    def _sort_by(self, cid: str) -> None:
        col, desc = self._sort
        self._sort = (cid, not desc if col == cid else cid != "name")
        self._render()

    def _render(self) -> None:
        cid, desc = self._sort
        key = next(c[3] for c in COLUMNS if c[0] == cid)
        items = sorted(self._items, key=key, reverse=desc) if self.query.get().strip() else []
        self.tree.delete(*self.tree.get_children())
        self._rows.clear()
        for item in items:
            trader = f"{item.best_trader} {rub(item.best_trader_price)}" if item.best_trader else "-"
            flea = "banned" if item.flea_banned else rub(item.flea_price)
            iid = self.tree.insert(
                "", "end",
                values=(item.name, flea, rub(item.last_low), trader, rub(item.per_slot), item.needed_for),
            )
            self._rows[iid] = item

    def _open_wiki(self, _event) -> None:
        sel = self.tree.selection()
        if sel and self._rows.get(sel[0]) and self._rows[sel[0]].link:
            webbrowser.open(self._rows[sel[0]].link)


class ScanPopup:
    """Small always-on-top window next to the cursor that doesn't take focus,
    so the game keeps keyboard and mouse input."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.win: Optional[tk.Toplevel] = None
        self._hide_job = None

    def show(self, lines: List[str], cursor, seconds: float) -> None:
        self.hide()
        win = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        body = tk.Frame(win, bg="#1b1d1f", padx=12, pady=8, highlightthickness=1, highlightbackground="#9a8866")
        body.pack()
        for i, text in enumerate(lines):
            tk.Label(
                body, text=text, bg="#1b1d1f", fg="#e8e2d0" if i else "#d8c48f", justify="left", anchor="w",
                font=("Segoe UI", 11 if i == 0 else 10, "bold" if i == 0 else "normal"),
            ).pack(anchor="w")
        win.update_idletasks()
        x, y = cursor
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        # Beside the cursor, away from the game's own tooltip.
        px = x - w - 30 if x + 30 + w > sw else x + 30
        py = min(max(0, y - h - 30), sh - h)
        win.geometry(f"+{px}+{py}")
        self.win = win
        self._show_no_activate(win)
        self._hide_job = self.root.after(int(seconds * 1000), self.hide)

    @staticmethod
    def _show_no_activate(win: tk.Toplevel) -> None:
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
