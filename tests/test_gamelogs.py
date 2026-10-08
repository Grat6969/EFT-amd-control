import json
import os
import time

from tarkov_display import gamelogs
from tarkov_display.gamelogs import LogFollower, logs_folder_in, parse_text, scan_history

VERSION = "1.0.0.1.39390"


def line(t, kind, msg, day="2025-11-20", tz=" +01:00"):
    return f"{day} {t}.123{tz}|{VERSION}|Info|{kind}|{msg}\n"


def notification(t, message, day="2025-11-20"):
    payload = {"type": "new_message", "eventId": "e1", "dialogId": "d1", "message": message}
    return line(t, "notifications", "Got notification | ChatMessageReceived", day) + json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def quest(t, quest_id, status=12, day="2025-11-20"):
    return notification(t, {"_id": "m", "type": status, "dt": 1, "hasRewards": True,
                            "templateId": f"{quest_id} successMessageText 5ac3477486f7741d651d6885"}, day)


FLEA = notification("20:30:00", {
    "_id": "m2", "type": 4, "templateId": "5bdabfb886f7743e152e867e 0", "hasRewards": True,
    "systemData": {"buyerNickname": "Ёжик", "soldItem": "5c0530ee86f774697952d952", "itemCount": 2},
    "items": {"data": [{"_id": "x", "_tpl": "5449016a4bdc2d6f028b456f", "upd": {"StackObjectsCount": 1500000}},
                       {"_id": "y", "_tpl": "5449016a4bdc2d6f028b456f", "upd": {"StackObjectsCount": 450000}}]},
})
RAID = line("20:10:00", "application",
            "TRACE-NetworkGameCreate profileStatus: 'Profileid: abc, Status: Busy, RaidMode: Online, Ip: 1.2.3.4, "
            "Port: 17000, Location: bigmap, Sid: s1, GameMode: deathmatch, shortId: AB12CD'")


def test_parse_events():
    text = ("﻿" + line("19:45:12", "application", "Session mode: Regular")
            + line("19:45:13", "application", "Something unrelated | with pipes")
            + RAID
            + quest("20:20:00", "5936d90786f7742b1420ba5b")
            + quest("20:21:00", "59674cd986f7744ab26e32f2", 10)
            + quest("20:22:00", "5967530a86f77462ba22226b", 11)
            + FLEA
            + line("20:40:00", "notifications", "Got notification | UserMatchOver")
            + json.dumps({"location": "bigmap", "shortId": "AB12CD"}, indent=2) + "\n")
    events = parse_text(text)
    kinds = [e.kind for e in events]
    assert kinds == ["mode", "raid", "quest", "quest", "quest", "flea", "raid_end"]
    assert events[0].mode == "regular" and all(e.mode == "regular" for e in events)
    assert events[1].data == {"map": "bigmap", "online": True, "raidId": "AB12CD"}
    assert [e.data["status"] for e in events[2:5]] == ["finished", "started", "failed"]
    assert events[2].data["questId"] == "5936d90786f7742b1420ba5b"
    assert events[2].time == "2025-11-20 20:20:00"
    assert events[5].data == {"itemId": "5c0530ee86f774697952d952", "count": 2, "buyer": "Ёжик", "roubles": 1950000}
    assert events[6].data["map"] == "bigmap"


def test_modes_and_odd_lines():
    text = (line("10:00:00", "application", "Session mode: Pve", tz="")
            + quest("10:05:00", "q1")
            + line("10:06:00", "application", "Session mode: PvpSeason")
            + quest("10:07:00", "q2")
            + line("10:08:00", "notifications", "Got notification | ChatMessageReceived") + "{ broken json\n")
    events = parse_text(text)
    assert [(e.kind, e.mode) for e in events] == [("mode", "pve"), ("quest", "pve"), ("mode", "seasonal"), ("quest", "seasonal")]


def make_session(logs, name, mtime=None):
    folder = logs / name
    folder.mkdir(parents=True)
    app = folder / f"{name} application_000.log"
    notes = folder / f"{name} notifications_000.log"
    (folder / f"{name} backend_000.log").write_text("ignored\n")
    app.write_text("")
    notes.write_text("")
    if mtime:
        os.utime(folder, (mtime, mtime))
    return app, notes


def append(path, text, encoding="utf-8"):
    with open(path, "ab") as fh:
        fh.write(text.encode(encoding) if isinstance(text, str) else text)


def test_follower_reads_history_then_live(tmp_path):
    logs = tmp_path / "Logs"
    app, notes = make_session(logs, "log_2025.11.20_19-45-12_1.0.0.1", time.time() - 100)
    append(app, line("19:45:12", "application", "Session mode: Regular"))
    append(notes, quest("19:50:00", "old-quest"))
    seen = []
    follower = LogFollower(logs, lambda ev, history: seen.append((ev.kind, ev.data.get("questId"), ev.mode, history)))
    follower.check()
    assert seen == [("mode", None, "regular", True), ("quest", "old-quest", "regular", True)]

    # A notification whose JSON is still being written waits for the rest.
    seen.clear()
    text = quest("20:00:00", "new-quest")
    half = len(text) // 2
    append(notes, text[:half])
    follower.check()
    assert seen == []
    append(notes, text[half:])
    follower.check()
    assert seen == [("quest", "new-quest", "regular", False)]

    # A line without its newline yet is not read half-way.
    seen.clear()
    raid = RAID
    append(app, raid[:-1])
    follower.check()
    append(app, raid[-1:])
    follower.check()
    assert [s[0] for s in seen] == ["raid"]


def test_follower_handles_split_utf8_and_new_sessions(tmp_path):
    logs = tmp_path / "Logs"
    app, notes = make_session(logs, "log_a", time.time() - 100)
    follower = LogFollower(logs, lambda ev, history: seen.append((ev.kind, ev.data, ev.mode, history)))
    seen = []
    follower.check()
    raw = FLEA.encode("utf-8")
    cut = raw.index("Ёжик".encode()) + 1  # in the middle of a 2-byte character
    append(notes, raw[:cut])
    follower.check()
    append(notes, raw[cut:])
    follower.check()
    assert seen[0][0] == "flea" and seen[0][1]["buyer"] == "Ёжик"

    # The game restarts: a newer session folder appears and is followed live.
    seen.clear()
    app2, notes2 = make_session(logs, "log_b", time.time())
    append(app2, line("21:00:00", "application", "Session mode: Pve"))
    append(notes2, quest("21:05:00", "pve-quest"))
    follower.check()
    assert ("quest", {"questId": "pve-quest", "status": "finished"}, "pve", False) in seen
    assert follower.session.name == "log_b"


def test_quest_keeps_the_mode_it_happened_in(tmp_path):
    logs = tmp_path / "Logs"
    app, notes = make_session(logs, "log_a")
    seen = []
    follower = LogFollower(logs, lambda ev, history: seen.append((ev.kind, ev.mode)))
    # Both files grow before the next read: the quest came before the switch.
    append(app, line("10:00:00", "application", "Session mode: Regular") + line("10:30:00", "application", "Session mode: Pve"))
    append(notes, quest("10:10:00", "pvp-quest") + quest("10:40:00", "pve-quest"))
    follower.check()
    assert seen == [("mode", "regular"), ("mode", "pve"), ("quest", "regular"), ("quest", "pve")]
    assert follower.mode == "pve"


def test_scan_history_per_mode(tmp_path):
    logs = tmp_path / "Logs"
    app, notes = make_session(logs, "log_2025.11.01_10-00-00", time.time() - 300)
    append(app, line("10:00:00", "application", "Session mode: Regular", day="2025-11-01")
           + line("12:00:00", "application", "Session mode: Pve", day="2025-11-01"))
    append(notes, quest("11:00:00", "pvp-1", day="2025-11-01") + quest("13:00:00", "pve-1", day="2025-11-01")
           + quest("13:30:00", "pve-1", day="2025-11-01") + quest("13:40:00", "pve-2", 11, day="2025-11-01"))
    app2, notes2 = make_session(logs, "log_2025.11.05_18-00-00", time.time() - 100)
    append(app2, line("18:00:00", "application", "Session mode: Regular", day="2025-11-05"))
    append(notes2, quest("18:30:00", "pvp-2", day="2025-11-05"))
    make_session(logs, "log_empty", time.time() - 50)

    result = scan_history(logs)
    assert result["sessions"] == 2
    assert result["first"] == "log_2025.11.01_10-00-00" and result["last"] == "log_2025.11.05_18-00-00"
    assert result["modes"]["regular"]["finished"] == ["pvp-1", "pvp-2"]
    assert result["modes"]["pve"]["finished"] == ["pve-1"]
    assert result["modes"]["pve"]["failed"] == ["pve-2"]


def test_sessions_ordered_by_folder_name_time(tmp_path):
    logs = tmp_path / "Logs"
    now = time.time()
    # Modified times say the opposite of the names; the names win.
    make_session(logs, "log_2025.11.20_19-45-12_1.0.0.1", now - 300)
    make_session(logs, "log_2025.11.20_9-05-00_1.0.0.1", now - 100)    # hour isn't zero-padded
    make_session(logs, "log_2025.11.21_0-10-00_1.0.0.2", now - 400)
    (logs / "Crashes").mkdir()                                       # not a session: ignored
    assert [p.name for p in gamelogs.session_folders(logs)] == [
        "log_2025.11.20_9-05-00_1.0.0.1", "log_2025.11.20_19-45-12_1.0.0.1", "log_2025.11.21_0-10-00_1.0.0.2"]
    assert gamelogs.session_folders(tmp_path / "missing") == []


def test_logs_folder_locations(tmp_path):
    assert logs_folder_in(tmp_path) is None
    (tmp_path / "build" / "Logs").mkdir(parents=True)
    assert logs_folder_in(tmp_path) == tmp_path / "build" / "Logs"
    (tmp_path / "Logs").mkdir()
    assert logs_folder_in(tmp_path) == tmp_path / "Logs"
    assert gamelogs.default_folder(str(tmp_path / "Logs")) == tmp_path / "Logs"
    assert gamelogs.default_folder(str(tmp_path / "missing")) is None
