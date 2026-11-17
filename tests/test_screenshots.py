"""Your position from Tarkov screenshot file names."""

import os
import time

from tarkov_display import screenshots as ss


def test_parse_name():
    assert ss.parse_name("2026-11-17[13-05]_-123.45, 2.1, 56.7_0.0, 0.71, 0.0, 0.71_12.34 (0).png") == {"x": -123.45, "y": 2.1, "z": 56.7}
    assert ss.parse_name("2026-11-17[13-05]-12, 0, 5_0.1, 0.2, 0.3, 0.9 (12).png") == {"x": -12.0, "y": 0.0, "z": 5.0}
    for bad in ("2026-11-17[13-05] (0).png", "holiday.png", "2026-11-17[13-05]_a, b, c (0).png",
                "2026-11-17[13-05]_1e9, 0, 0 (0).png", "2026-11-17[13-05]_999999, 0, 0 (0).png"):
        assert ss.parse_name(bad) is None


def test_watcher_reports_only_new_screenshots(tmp_path):
    old = tmp_path / "2026-11-17[12-00]_1, 2, 3_0, 0, 0, 1 (0).png"
    old.write_bytes(b"x")
    os.utime(old, (time.time() - 60, time.time() - 60))
    seen = []
    w = ss.ScreenshotWatcher(tmp_path, seen.append)
    assert w.check() is None  # what was there already doesn't count
    new = tmp_path / "2026-11-17[13-05]_200, 1, 150_0, 0.7, 0, 0.7_1.5 (0).png"
    new.write_bytes(b"x")
    assert w.check()["x"] == 200 and seen[-1]["file"] == new.name
    assert w.check() is None  # once
    (tmp_path / "menu.png").write_bytes(b"x")  # not a raid screenshot: ignored
    assert w.check() is None and len(seen) == 1


def test_position_goes_to_the_raid_map(webapp, monkeypatch):
    from tarkov_display import gamelogs

    monkeypatch.setattr(webapp, "refresh_after_raid", lambda: False)
    published = []
    webapp.publish = lambda e, d: published.append((e, d))
    webapp.link._on_position({"x": 1, "y": 2, "z": 3, "time": 9})
    assert webapp.position is None  # not in a raid
    webapp.link._on_event(gamelogs.Event("raid", "2026-11-17 13:00:00", {"map": "bigmap", "online": True}), False)
    webapp.link._on_position({"x": 1, "y": 2, "z": 3, "time": 9})
    assert webapp.position == {"x": 1, "y": 2, "z": 3, "time": 9, "map": "customs"}
    assert ("position", {"map": "customs", "time": 9}) in published
