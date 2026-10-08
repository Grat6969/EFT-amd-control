"""Small Tkinter window for picking and tuning profiles."""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .app import App
from .profiles import Profile

log = logging.getLogger(__name__)

SLIDERS = [
    # field, label, min, max, resolution
    ("brightness", "Brightness", -100, 100, 1),
    ("contrast", "Contrast", 0, 200, 1),
    ("saturation", "Saturation (helps spot players)", 0, 200, 1),
    ("gamma", "Gamma (lifts shadows)", 0.5, 2.5, 0.05),
    ("temperature", "Colour temperature (K)", 4000, 10000, 100),
]


class MainWindow:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Tarkov Display")
        self.root.resizable(False, False)
        self.status = tk.StringVar(value="starting...")
        self.app = App()
        self._save_job = None
        self._build()
        self._load_profile()
        self.app.start()
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self._poll()

    def _poll(self) -> None:
        # Tk is not thread-safe, so pick up changes made by the watcher and
        # hotkey threads from here rather than having them call into Tk.
        self.status.set(self.app.watcher.status)
        if self.auto_on.get() != self.app.config.auto.enabled:  # Ctrl+Alt+A
            self.auto_on.set(self.app.config.auto.enabled)
        adj = self.app.watcher.adjuster
        if self.app.config.auto.enabled and adj.scene is not None:
            self.auto_readout.set(f"scene {adj.scene:.0%}, boost {adj.applied:.0%}")
        else:
            self.auto_readout.set("")
        if self.profile_var.get() != self.app.config.active_profile:
            self.profile_var.set(self.app.config.active_profile)
            self._load_profile()
        self.root.after(300, self._poll)

    # -- layout ---------------------------------------------------------

    def _build(self) -> None:
        pad = {"padx": 10, "pady": 4}
        frm = ttk.Frame(self.root, padding=10)
        frm.grid(sticky="nsew")

        ttk.Label(frm, textvariable=self.status, font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", **pad
        )

        ttk.Label(frm, text="Profile").grid(row=1, column=0, sticky="w", **pad)
        self.profile_var = tk.StringVar(value=self.app.config.active_profile)
        self.profile_box = ttk.Combobox(
            frm, textvariable=self.profile_var, state="readonly", values=self.app.config.profile_names()
        )
        self.profile_box.grid(row=1, column=1, sticky="ew", **pad)
        self.profile_box.bind("<<ComboboxSelected>>", lambda e: self._on_profile_selected())
        btns = ttk.Frame(frm)
        btns.grid(row=1, column=2, sticky="e")
        ttk.Button(btns, text="New", width=6, command=self._new_profile).pack(side="left")
        ttk.Button(btns, text="Delete", width=6, command=self._delete_profile).pack(side="left")

        self.vars = {}
        row = 2
        for name, label, lo, hi, res in SLIDERS:
            ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", **pad)
            var = tk.DoubleVar()
            scale = tk.Scale(
                frm, variable=var, from_=lo, to=hi, resolution=res, orient="horizontal",
                length=260, command=lambda _v: self._schedule_save(),
            )
            scale.grid(row=row, column=1, sticky="ew", **pad)
            self.vars[name] = (var, scale)
            row += 1

        self.temp_default = tk.BooleanVar()
        ttk.Checkbutton(
            frm, text="Driver default", variable=self.temp_default, command=self._on_temp_default
        ).grid(row=row - 1, column=2, sticky="w")

        ttk.Separator(frm).grid(row=row, column=0, columnspan=3, sticky="ew", pady=6)
        row += 1

        self.preview = tk.BooleanVar()
        ttk.Checkbutton(
            frm, text="Preview on desktop now", variable=self.preview, command=self._on_preview
        ).grid(row=row, column=0, columnspan=2, sticky="w", **pad)
        row += 1
        self.fg_only = tk.BooleanVar(value=self.app.config.foreground_only)
        ttk.Checkbutton(
            frm, text="Only while the Tarkov window is focused (normal colours when alt-tabbed)",
            variable=self.fg_only, command=self._on_fg_only,
        ).grid(row=row, column=0, columnspan=3, sticky="w", **pad)
        row += 1

        row = self._build_auto(frm, row, pad)

        ttk.Label(
            frm,
            foreground="gray",
            text="Hotkeys in game: Ctrl+Alt+1..9 switch profile, Ctrl+Alt+0 on/off, Ctrl+Alt+A auto",
        ).grid(row=row, column=0, columnspan=3, sticky="w", **pad)
        row += 1
        ttk.Button(frm, text="Reset profile to built-in", command=self._reset_profile).grid(
            row=row, column=0, sticky="w", **pad
        )

    def _build_auto(self, frm, row: int, pad: dict) -> int:
        auto = self.app.config.auto
        ttk.Separator(frm).grid(row=row, column=0, columnspan=3, sticky="ew", pady=6)
        row += 1
        self.auto_on = tk.BooleanVar(value=auto.enabled)
        ttk.Checkbutton(
            frm, text="Auto-boost in dark areas (samples 5 spots on screen)",
            variable=self.auto_on, command=self._on_auto_changed,
        ).grid(row=row, column=0, columnspan=2, sticky="w", **pad)
        self.auto_readout = tk.StringVar()
        ttk.Label(frm, textvariable=self.auto_readout, foreground="gray").grid(row=row, column=2, sticky="w")
        row += 1

        self.auto_vars = {}
        for name, label, lo, hi, res in [
            ("gamma_boost", "Extra gamma when dark", 0.0, 1.0, 0.05),
            ("brightness_boost", "Extra brightness when dark", 0, 50, 1),
            ("response_seconds", "Reaction time (s)", 0.3, 5.0, 0.1),
            ("dark_level", "Counts as fully dark below", 0.0, 0.5, 0.01),
            ("bright_level", "Counts as bright above", 0.05, 0.8, 0.01),
        ]:
            ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", **pad)
            var = tk.DoubleVar(value=getattr(auto, name))
            tk.Scale(
                frm, variable=var, from_=lo, to=hi, resolution=res, orient="horizontal",
                length=260, command=lambda _v: self._on_auto_changed(),
            ).grid(row=row, column=1, sticky="ew", **pad)
            self.auto_vars[name] = var
            row += 1
        return row

    def _on_auto_changed(self) -> None:
        auto = self.app.config.auto
        auto.enabled = self.auto_on.get()
        for name, var in self.auto_vars.items():
            value = var.get()
            setattr(auto, name, int(value) if name == "brightness_boost" else round(float(value), 2))
        self._schedule_save()

    # -- profile editing ------------------------------------------------

    def _current(self) -> Profile:
        return self.app.config.profiles[self.app.config.active_profile]

    def _load_profile(self) -> None:
        p = self._current()
        self._loading = True
        for name, (var, scale) in self.vars.items():
            value = getattr(p, name)
            if name == "temperature":
                self.temp_default.set(value is None)
                scale.configure(state="disabled" if value is None else "normal")
                value = 6500 if value is None else value
            elif value is None:
                value = {"brightness": 0, "contrast": 100, "saturation": 100}.get(name, 0)
            var.set(value)
        self._loading = False

    def _schedule_save(self) -> None:
        if getattr(self, "_loading", False):
            return
        if self._save_job:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(250, self._save_profile)

    def _save_profile(self) -> None:
        self._save_job = None
        p = self._current()
        for name, (var, _) in self.vars.items():
            value = var.get()
            if name == "gamma":
                p.gamma = round(float(value), 2)
            elif name == "temperature":
                p.temperature = None if self.temp_default.get() else int(value)
            else:
                setattr(p, name, int(value))
        self.app.save()
        self.app.watcher.refresh()

    def _on_temp_default(self) -> None:
        self.vars["temperature"][1].configure(state="disabled" if self.temp_default.get() else "normal")
        self._schedule_save()

    def _on_profile_selected(self) -> None:
        self.app.select_profile(self.profile_var.get())
        self._load_profile()

    def _refresh_profile_list(self) -> None:
        self.profile_box.configure(values=self.app.config.profile_names())
        self.profile_var.set(self.app.config.active_profile)

    def _new_profile(self) -> None:
        name = simpledialog.askstring("New profile", "Name (copies the current profile):", parent=self.root)
        if not name:
            return
        name = name.strip()
        if name in self.app.config.profiles:
            messagebox.showerror("Tarkov Display", f"A profile called '{name}' already exists.")
            return
        self.app.config.profiles[name] = Profile.from_dict(self._current().to_dict())
        self.app.select_profile(name)
        self._refresh_profile_list()
        self._load_profile()

    def _delete_profile(self) -> None:
        if len(self.app.config.profiles) <= 1:
            return
        name = self.app.config.active_profile
        if not messagebox.askyesno("Tarkov Display", f"Delete profile '{name}'?"):
            return
        del self.app.config.profiles[name]
        self.app.select_profile(next(iter(self.app.config.profiles)))
        self._refresh_profile_list()
        self._load_profile()

    def _reset_profile(self) -> None:
        from .profiles import BUILTIN_PROFILES

        name = self.app.config.active_profile
        base = BUILTIN_PROFILES.get(name, BUILTIN_PROFILES["balanced"])
        self.app.config.profiles[name] = Profile.from_dict(base.to_dict())
        self.app.save()
        self.app.watcher.refresh()
        self._load_profile()

    def _on_preview(self) -> None:
        self.app.watcher.force = self.preview.get()
        self.app.watcher.refresh()

    def _on_fg_only(self) -> None:
        self.app.config.foreground_only = self.fg_only.get()
        self.app.save()
        self.app.watcher.refresh()

    def quit(self) -> None:
        if self._save_job:
            self.root.after_cancel(self._save_job)
            self._save_profile()
        self.app.shutdown()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    MainWindow().run()
