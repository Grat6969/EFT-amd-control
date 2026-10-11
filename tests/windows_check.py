"""Checks the Windows-only parts of RaidReady on a real Windows machine.

    python -m tests.windows_check

Run by the "Windows tests" workflow. Each check prints PASS, FAIL or SKIP
(SKIP: the machine can't do it, e.g. a build server without a GPU). Exits 1
if anything failed. The price check is tested end to end: a fake item tooltip
is drawn on screen, the mouse is moved next to it, and the app's own scanner
captures the screen, reads it with Windows OCR and looks the item up.
"""

from __future__ import annotations

import sys
import threading
import time
import traceback

CHECKS = []


class Skip(Exception):
    pass


def check(name):
    def wrap(fn):
        CHECKS.append((name, fn))
        return fn
    return wrap


def price_db():
    sys.path.insert(0, "tests")
    from test_prices import db  # the same made-up price list the unit tests use

    return db()


# Item names to read, and the id each must match (from tests/test_prices.py).
NAMES = [("LEDX Skin Transilluminator", "ledx"), ("Graphics card", "gpu"),
         ("Salewa first aid kit", "salewa"), ("Tetriz portable game console", "tetriz")]


@check("secret store (DPAPI) round trip")
def _():
    from tarkov_display import secretstore

    stored = secretstore.protect("PVP_0123456789abcdef01")
    assert stored != "PVP_0123456789abcdef01" and secretstore.unprotect(stored) == "PVP_0123456789abcdef01"
    try:
        secretstore.unprotect("garbage-not-a-blob")
    except Exception as exc:  # must fail cleanly, not crash the process
        return f"garbage refused with {type(exc).__name__}"
    return "garbage was accepted?"


@check("game Logs folder lookup (registry, Steam)")
def _():
    from tarkov_display import gamelogs

    found = gamelogs.find_logs_folder()
    gamelogs.default_folder("")
    gamelogs.custom_folder(r"C:\Battlestate Games\Escape from Tarkov\Logs")
    return f"found: {found}"


@check("display control without an AMD card")
def _():
    from tarkov_display.controller import DisplayController
    from tarkov_display.profiles import load_config

    ctl = DisplayController.create()
    profile = next(iter(load_config().profiles.values()))
    ctl.apply(profile)
    ctl.restore()
    ctl.close()
    return f"AMD: {'yes' if ctl.color else 'no'}, gamma ramp: {'yes' if getattr(ctl, 'gamma', None) else 'no'}"


@check("global hotkeys register and unregister")
def _():
    from tarkov_display.hotkeys import Hotkeys

    hk = Hotkeys(lambda n: None, lambda: None, lambda: None, lambda: None)
    hk.start()
    time.sleep(1.0)
    hk.stop()
    return f"taken by other programs: {hk.failed or 'none'}"


@check("price popup window")
def _():
    from tarkov_display.popup import create_host, make_dpi_aware

    make_dpi_aware()
    host = create_host()
    if host is None:
        raise Skip("no display for Tk on this machine")
    stop = threading.Event()
    host.show("LEDX Skin Transilluminator", "Flea 1,020,000 ₽", [("Flea", "1,020,000 ₽", "good")],
              [("Needed", "Private Clinic", "warn")], "Ctrl+Alt+P", (400, 400), 5)
    shown = []
    host.root.after(1200, lambda: (shown.append(host.win is not None), stop.set()))
    host.run(stop)
    assert shown == [True], "the popup window never appeared"


def render(text: str, size: int = 13):
    """``text`` in a Tarkov-like tooltip (light text on dark grey), as BGRA."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise Skip("Pillow isn't installed")
    font = None
    for name in ("bahnschrift.ttf", "arial.ttf"):
        try:
            font = ImageFont.truetype(name, size)
            break
        except OSError:
            pass
    font = font or ImageFont.load_default()
    img = Image.new("RGB", (int(size * len(text) * 0.75) + 40, size * 3), (26, 26, 26))
    ImageDraw.Draw(img).text((20, size), text, fill=(220, 220, 210), font=font)
    img = img.resize((img.width * 2, img.height * 2))  # the scanner enlarges captures 2x
    return img.convert("RGBA").tobytes("raw", "BGRA"), img.width, img.height


@check("Windows OCR reads item names")
def _():
    from tarkov_display.matching import ItemMatcher, candidate_lines
    from tarkov_display.ocr import OcrUnavailable, WindowsOcr

    try:
        ocr = WindowsOcr()
    except OcrUnavailable as exc:
        raise Skip(str(exc))
    matcher = ItemMatcher(price_db().items)
    misses = []
    for name, want in NAMES:
        bgra, w, h = render(name)
        texts = [line.text for line in ocr.read(bgra, w, h)]
        match = matcher.match_lines(candidate_lines(texts))
        if not match or match.item.id != want:
            misses.append(f"{name!r} read as {texts} -> {match.item.id if match else None}")
    assert not misses, "; ".join(misses)
    return f"{len(NAMES)}/{len(NAMES)} read and matched"


@check("price check end to end: screen capture, OCR, match")
def _():
    import ctypes
    import tkinter as tk

    from tarkov_display.ocr import OcrUnavailable
    from tarkov_display.popup import make_dpi_aware
    from tarkov_display.profiles import ScanConfig
    from tarkov_display.scanner import ItemScanner

    make_dpi_aware()
    try:
        scanner = ItemScanner(price_db(), ScanConfig())
    except OcrUnavailable as exc:
        raise Skip(str(exc))
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise Skip(f"no display: {exc}")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg="#1a1a1a")
    label = tk.Label(root, text="Graphics card", fg="#dcdcd2", bg="#1a1a1a", font=("Bahnschrift", 13))
    label.pack(padx=12, pady=6)
    root.geometry("+420+400")
    results = {}

    def scan():
        root.update()
        ctypes.windll.user32.SetCursorPos(400, 410)  # just left of the tooltip, as in game
        time.sleep(0.3)
        try:
            bgra, w, h = scanner.screen.grab(380, 380, 300, 60)
            results["blank"] = len(set(bgra[i:i + 3] for i in range(0, len(bgra), 4 * 97))) <= 1
            results["scan"] = scanner.scan()
        except Exception:
            results["error"] = traceback.format_exc()
        root.quit()

    root.after(800, scan)
    root.mainloop()
    root.destroy()
    if "error" in results:
        raise AssertionError(results["error"])
    if results.get("blank"):
        raise Skip("screen capture returns a blank image on this machine")
    result = results["scan"]
    assert result.match and result.match.item.id == "gpu", f"read {result.lines}, matched {result.match}"
    return f"read {result.lines} -> {result.match.item.name}"


def main() -> int:
    if sys.platform != "win32":
        print("These checks only run on Windows.")
        return 0
    results = []
    for name, fn in CHECKS:
        try:
            outcome = ("PASS", fn() or "")
        except Skip as exc:
            outcome = ("SKIP", str(exc))
        except Exception:
            outcome = ("FAIL", traceback.format_exc())
        results.append(outcome[0])
        print(f"{outcome[0]:4}  {name}  {outcome[1]}".rstrip(), flush=True)
    failed = results.count("FAIL")
    print(f"\n{len(results) - failed} of {len(results)} checks passed or skipped, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
