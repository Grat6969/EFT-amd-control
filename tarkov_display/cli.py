"""Command line entry point. With no arguments, opens the settings window."""

from __future__ import annotations

import argparse
import ctypes
import logging
import queue
import sys
import time

from .app import App, setup_logging
from .controller import DisplayController
from .profiles import default_config_dir, load_config

log = logging.getLogger(__name__)


def cmd_gui(args) -> int:
    from .webapp import main

    return main(
        open_on_start=not getattr(args, "no_window", False),
        restarted=getattr(args, "restarted", False),
        port=getattr(args, "port", None),
    )


def cmd_watch(args) -> int:
    app = App()
    if args.profile:
        if args.profile not in app.config.profiles:
            print(f"Unknown profile '{args.profile}'. Try: {', '.join(app.config.profile_names())}")
            return 2
        app.select_profile(args.profile)
    if args.always:
        app.config.foreground_only = False
    app.start()
    print("Running. Ctrl+Alt+1..9 switch profile, Ctrl+Alt+0 on/off, Ctrl+Alt+P price check, Ctrl+C to quit.")
    try:
        while True:
            try:
                print_scan(app.scan_results.get(timeout=1))
            except queue.Empty:
                pass
    except KeyboardInterrupt:
        pass
    finally:
        app.shutdown()
    return 0


def print_scan(result) -> None:
    from .prices import describe

    if result.match:
        print("\n".join(describe(result.match.item)))
        print(f"  (read {result.match.text!r}, {result.match.score:.0%} sure)")
    else:
        print(f"No item identified. {result.error or ''} OCR read: {result.lines}")
    if result.debug_file:
        print(f"  saved {result.debug_file}")
    print()


def _prices():
    from .prices import PriceDB

    cfg = load_config()
    db = PriceDB(default_config_dir() / f"prices_{cfg.game_mode}.json", cfg.game_mode)
    if db.age >= db.max_age:
        print("Downloading prices from tarkov.dev...")
        if not db.refresh() and not db.items:
            print(f"Couldn't download prices: {db.error}")
    return db


def cmd_price(args) -> int:
    from .prices import describe

    db = _prices()
    found = db.search(" ".join(args.query), limit=args.limit)
    if not found:
        print("No matching items.")
    for item in found:
        print("\n".join(describe(item)))
        print()
    return 0


def cmd_scan(args) -> int:
    from .scanner import ItemScanner

    cfg = load_config()
    if args.debug:
        cfg.scan.debug = True
    scanner = ItemScanner(_prices(), cfg.scan, default_config_dir() / "scans")
    print(f"Hover over an item in Tarkov. Scanning every {args.every:g}s; Ctrl+C to stop.")
    try:
        while True:
            time.sleep(args.every)
            print_scan(scanner.scan())
    except KeyboardInterrupt:
        pass
    return 0


def cmd_list(args) -> int:
    cfg = load_config()
    for name, p in cfg.profiles.items():
        mark = "*" if name == cfg.active_profile else " "
        print(f"{mark} {name:<12} {p.to_dict()}")
    print(f"\nConfig file: {default_config_dir() / 'config.json'}")
    return 0


def cmd_displays(args) -> int:
    from .adl import ADL, COLOR_TYPES

    with ADL() as adl:
        displays = adl.displays()
        if not displays:
            print("No AMD-driven displays found.")
        for d in displays:
            print(f"{d.name}  ({d.os_name}, adapter {d.adapter_index}, display {d.display_index})")
            for name in COLOR_TYPES:
                try:
                    r = adl.get_color(d, name)
                    print(f"    {name:<12} current={r.current:<6} default={r.default:<6} "
                          f"range={r.minimum}..{r.maximum} step={r.step}")
                except Exception as exc:
                    print(f"    {name:<12} unsupported ({exc})")
    return 0


def cmd_scene(args) -> int:
    from .auto import target_boost
    from .screen import ScreenSampler, average_samples

    sampler = ScreenSampler()
    auto = load_config().auto
    print("Sampling the focused window at 5 spots. Alt-tab into Tarkov; Ctrl+C to stop.")
    try:
        while True:
            values = sampler.sample()
            avg = average_samples(values)
            spots = "  ".join(f"{v:4.0%}" for v in values)
            if avg is None:
                print(f"{spots}  -> black (loading screen or exclusive fullscreen)")
            else:
                print(f"{spots}  -> average {avg:4.0%}, boost {target_boost(avg, auto):4.0%}")
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    return 0


def cmd_apply(args) -> int:
    cfg = load_config()
    profile = cfg.profiles.get(args.profile)
    if profile is None:
        print(f"Unknown profile '{args.profile}'. Try: {', '.join(cfg.profile_names())}")
        return 2
    ctl = DisplayController.create(default_config_dir() / "original_settings.json")
    ctl.apply(profile)
    print(f"Applied '{args.profile}'. Run 'restore' to go back to your normal settings.")
    return 0


def cmd_restore(args) -> int:
    ctl = DisplayController.create(default_config_dir() / "original_settings.json")
    if ctl.recover():
        print("Restored your original display settings.")
    else:
        print("Nothing to restore.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="tarkov-display",
        description="Tarkov Companion: tarkov.dev prices, quests, hideout and maps, plus automatic AMD "
                    "display settings for Escape from Tarkov.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("gui", help="open the app window (default)")
    p.add_argument("--no-window", action="store_true", help="start without opening a window")
    p.add_argument("--restarted", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--port", type=int, help="local port for the app window")
    p.set_defaults(func=cmd_gui)

    p = sub.add_parser("watch", help="run in the console without a window")
    p.add_argument("--profile", help="profile to use")
    p.add_argument("--always", action="store_true", help="apply whenever the game runs, even when alt-tabbed")
    p.set_defaults(func=cmd_watch)

    sub.add_parser("list", help="list profiles").set_defaults(func=cmd_list)
    sub.add_parser("displays", help="show AMD displays and their current colour values").set_defaults(
        func=cmd_displays
    )

    sub.add_parser("scene", help="print live screen-brightness readings used by auto-boost").set_defaults(
        func=cmd_scene
    )

    p = sub.add_parser("price", help="look up flea/trader prices by name")
    p.add_argument("query", nargs="+")
    p.add_argument("--limit", type=int, default=5)
    p.set_defaults(func=cmd_price)

    p = sub.add_parser("scan", help="repeatedly price-check the item under the mouse (for testing)")
    p.add_argument("--every", type=float, default=3.0, help="seconds between scans")
    p.add_argument("--debug", action="store_true", help="save each capture to the scans folder")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("apply", help="apply a profile right now and leave it on")
    p.add_argument("profile")
    p.set_defaults(func=cmd_apply)

    sub.add_parser("restore", help="put back the settings saved before the last apply").set_defaults(
        func=cmd_restore
    )

    args = parser.parse_args(argv)
    from .popup import make_dpi_aware

    make_dpi_aware()  # before any window or screenshot
    if sys.platform != "win32" and args.command not in (None, "gui", "list", "price"):
        print("tarkov-display controls Windows display drivers and only runs on Windows.")
        return 1
    log_file = setup_logging(args.verbose)
    func = getattr(args, "func", cmd_gui)
    try:
        return func(args)
    except Exception as exc:
        log.exception("Tarkov Companion stopped because of an error")
        if sys.platform == "win32" and sys.stderr is None:  # no console to show it in
            ctypes.windll.user32.MessageBoxW(
                None, f"Tarkov Companion stopped because of an error:\n\n{exc}\n\nDetails are in {log_file}",
                "Tarkov Companion", 0x10)  # MB_ICONERROR
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
