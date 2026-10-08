"""Command line entry point. With no arguments, opens the settings window."""

from __future__ import annotations

import argparse
import logging
import sys
import time

from .app import App, setup_logging
from .controller import DisplayController
from .profiles import default_config_dir, load_config

log = logging.getLogger(__name__)


def cmd_gui(args) -> int:
    from .gui import main

    main()
    return 0


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
    print("Running. Ctrl+Alt+1..9 switch profile, Ctrl+Alt+0 on/off, Ctrl+C here to quit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        app.shutdown()
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
        description="Automatically switch AMD display colour settings while Escape from Tarkov is running.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("gui", help="open the settings window (default)").set_defaults(func=cmd_gui)

    p = sub.add_parser("watch", help="run in the console without a window")
    p.add_argument("--profile", help="profile to use")
    p.add_argument("--always", action="store_true", help="apply whenever the game runs, even when alt-tabbed")
    p.set_defaults(func=cmd_watch)

    sub.add_parser("list", help="list profiles").set_defaults(func=cmd_list)
    sub.add_parser("displays", help="show AMD displays and their current colour values").set_defaults(
        func=cmd_displays
    )

    p = sub.add_parser("apply", help="apply a profile right now and leave it on")
    p.add_argument("profile")
    p.set_defaults(func=cmd_apply)

    sub.add_parser("restore", help="put back the settings saved before the last apply").set_defaults(
        func=cmd_restore
    )

    args = parser.parse_args(argv)
    if sys.platform != "win32" and args.command not in ("list",):
        print("tarkov-display controls Windows display drivers and only runs on Windows.")
        return 1
    setup_logging(args.verbose)
    func = getattr(args, "func", cmd_gui)
    return func(args)


if __name__ == "__main__":
    sys.exit(main())
