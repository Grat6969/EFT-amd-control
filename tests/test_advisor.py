"""The "Ask Claude" export and the raid history it reads from the game logs."""

import json
from datetime import datetime

import pytest

from tarkov_display import advisor, gamelogs
from tarkov_display.progress import Progress, ProgressError

VERSION = "1.3.0.2.48779"


def line(t, kind, msg, day="2026-11-17"):
    return f"{day} {t}.100|{VERSION}|Info|{kind}|{msg}\n"


def status(t, loc, ip, sid):
    return line(t, "application", f"TRACE-NetworkGameCreate profileStatus: 'Profileid: p1, Status: Busy, RaidMode: Online, "
                                  f"Ip: {ip}, Port: 17008, Location: {loc}, Sid: {sid}lgs022_6afc952d_17.11.26_20-55-57, "
                                  "GameMode: deathmatch, shortId: 9R475L'")


def stats(t, ip, rtt="56.125", lose="0"):
    return line(t, "network-connection", f"Statistics (address: {ip}:17008, rtt: {rtt}, lose: {lose}, sent: 1, received: 2)")


def write_session(folder, name, app="", net="", notes=""):
    session = folder / f"log_{name}_{VERSION}"
    session.mkdir(parents=True)
    stamp = f"{name}_{VERSION}"
    (session / f"{stamp} application_000.log").write_text(app, encoding="utf-8")
    (session / f"{stamp} network-connection_000.log").write_text(net, encoding="utf-8")
    (session / f"{stamp} push-notifications_000.log").write_text(notes, encoding="utf-8")
    return session


def sold(t, item, roubles):
    payload = {"type": "new_message", "message": {"type": 4, "templateId": "5bdabfb886f7743e152e867e 0",
               "systemData": {"buyerNickname": "x", "soldItem": item, "itemCount": 1},
               "items": {"data": [{"_tpl": "5449016a4bdc2d6f028b456f", "upd": {"StackObjectsCount": roubles}}]}}}
    return line(t, "push-notifications", "Got notification | ChatMessageReceived") + json.dumps(payload, indent=2) + "\n"


def test_raid_history_from_logs(tmp_path):
    app = (line("12:52:16", "application", "Session mode: Regular")
           + line("13:01:28", "application", "Matching with group id: 967734")
           + status("13:01:53", "bigmap", "148.72.174.198", "us-stl01")
           + line("13:02:49", "application", "GameStarted:65.26(10.62) real:80.39(12.05) diff:15.12")
           + line("13:21:53", "application", "Matching with group id: 967734")
           + status("13:23:16", "Shoreline", "37.19.207.99", "us-ash02")
           + line("13:24:18", "application", "GameStarted:1 real:1 diff:1")
           + status("14:22:03", "Woods", "1.1.1.1", "zz-qqq01"))  # still in it: no end yet
    net = stats("13:13:21", "148.72.174.198") + stats("13:37:54", "37.19.207.99", "41.25", "3")
    notes = sold("13:45:21", "itemA", 24420) + sold("14:14:34", "itemB", 40420)
    write_session(tmp_path, "2026.11.17_12-52-07", app, net, notes)
    write_session(tmp_path, "2026.11.16_9-00-00")  # an older, empty session
    (tmp_path / "not a session").mkdir()

    h = gamelogs.recent_history(tmp_path)
    assert h["gameVersion"] == VERSION and h["sessions"] == 2
    woods, shore, customs = h["raids"]
    assert customs == {"time": "2026-11-17 13:01:53", "map": "bigmap", "mode": "regular", "online": True,
                       "server": "St. Louis (us-stl01)", "queue": 25, "started": "2026-11-17 13:02:49",
                       "end": "2026-11-17 13:13:21", "ping": 56, "loss": 0, "minutes": 11}
    assert (shore["server"], shore["ping"], shore["loss"], shore["minutes"], shore["queue"]) == ("Ashburn (us-ash02)", 41, 3, 14, 83)
    assert woods["end"] is None and woods["minutes"] is None and woods["server"] == "zz-qqq01"
    assert [s["itemId"] for s in h["sales"]] == ["itemB", "itemA"] and h["sales"][0]["roubles"] == 40420


def test_leaving_a_raid_is_read_from_the_connection_log():
    events = gamelogs.parse_text(stats("13:13:21", "148.72.174.198", "52.6"))
    assert [(e.kind, e.data) for e in events] == [("raid_end", {"map": None, "raidId": None, "ping": 53, "loss": 0})]
    assert gamelogs.LOG_FILE.search("2026.11.17_12-52-07_1.3.0.2.48779 network-connection_000.log")


def test_advisor_settings_are_checked():
    p = Progress(None)
    snap = p.apply({"op": "advisor", "settings": {"kit": "mid", "roubles": "2500000", "goal": "  Kappa  ", "notes": "x" * 5000}})
    assert snap["advisor"] == {"kit": "mid", "roubles": 2500000, "goal": "Kappa", "notes": "x" * 1000}
    for bad in ({"kit": "op"}, {"roubles": "lots"}, {"goal": 5}, None):
        with pytest.raises(ProgressError):
            p.apply({"op": "advisor", "settings": bad})
    assert p.snapshot()["advisor"]["kit"] == "mid"
    # Hand-edited or imported files are cleaned, not refused.
    p.apply({"op": "import", "data": {"advisor": {"kit": "op", "roubles": -5, "goal": ["x"]}}})
    assert p.snapshot()["advisor"] == {"kit": "", "roubles": 0, "goal": "", "notes": ""}


def demo_data():
    from tests import demo

    return demo.QUESTS, demo.STATIONS, demo.MAPS


def test_open_quests_by_map_and_keys():
    tasks, _, maps = demo_data()
    aquarius = next(t for t in tasks if t["name"] == "Operation Aquarius - Part 1")
    prereqs = [r["task"]["id"] for r in aquarius["taskRequirements"]]
    progress = {"player_level": 20, "faction": "USEC", "tasks": prereqs, "owned": {}, "objectives": {}, "pinned": [aquarius["id"]]}
    from tarkov_display.linking import prerequisite_ids

    progress["tasks"] = list({x for p in prereqs for x in [p, *prerequisite_ids(p, tasks)]})
    found = advisor.open_quests(tasks, progress, maps)
    assert any(e["task"]["id"] == aquarius["id"] for e in found["groups"]["Customs"])
    dorm = next(k for k in found["keys"] if k["name"] == "Dorm room 206 key")
    assert dorm["have"] is False and "Operation Aquarius - Part 1" in dorm["quests"] and dorm["maps"] == ["Customs"]
    progress["owned"] = {dorm["id"]: 1}
    assert next(k for k in advisor.open_quests(tasks, progress, maps)["keys"] if k["id"] == dorm["id"])["have"] is True
    # Done objectives drop out; with none left the quest is ready to turn in.
    progress["objectives"] = {o["id"]: o.get("count") or 1 for o in aquarius["objectives"]}
    found = advisor.open_quests(tasks, progress, maps)
    assert any(e["task"]["id"] == aquarius["id"] for e in found["groups"]["Ready to turn in"])
    assert not any(e["task"]["id"] == aquarius["id"] for e in found["groups"].get("Customs", []))


def test_export_text(tmp_path):
    tasks, stations, maps = demo_data()
    progress = {"player_level": 12, "faction": "BEAR", "tasks": [], "owned": {}, "objectives": {}, "pinned": [],
                "hideout": {}, "advisor": {"kit": "budget", "roubles": 1200000, "goal": "Unlock flea", "notes": "Duo with a friend"}}
    history = {"gameVersion": VERSION, "raids": [{"time": "2026-11-17 13:01:53", "map": "bigmap", "mode": "regular", "online": True,
                                                  "server": "St. Louis (us-stl01)", "queue": 25, "minutes": 11, "ping": 56, "loss": 0}],
               "sales": [{"time": "2026-11-17 14:14:34", "itemId": "i1", "count": 1, "roubles": 40420}]}
    text = advisor.build(progress=progress, tasks=tasks, stations=stations, maps=maps, history=history,
                         item_names={"i1": "Graphics card"}, app_version="9.9", now=datetime(2026, 11, 17, 17, 0))
    assert text.startswith("# RaidReady export for Claude")
    assert "search current Reddit" in text and "_Exported 2026-11-17 17:00 from RaidReady 9.9, game 1.3.0.2.48779._" in text
    for part in ("Level 12, BEAR", "Budget (", "1,200,000 ₽", "Goal: Unlock flea", "Notes: Duo with a friend",
                 "## Open quests by map", "### Customs", "## Keys my open quests use", "## Hideout: next level",
                 "| 11-17 13:01 | Customs | PvP | 25 s | 11 min | 56 ms | St. Louis (us-stl01) |",
                 "Graphics card for 40,420 ₽", "**Customs**: 8-12 players"):
        assert part in text, part
    # No data yet: still a usable file.
    bare = advisor.build(progress={"player_level": 1}, tasks=None, stations=None, maps=None)
    assert "hadn't downloaded" in bare and "## Me" in bare

    path = advisor.save(text, tmp_path, datetime(2026, 11, 17, 17, 0))
    assert path.name == "raidready-2026-11-17_1700.md" and path.read_text(encoding="utf-8") == text
    for n in range(25):
        advisor.save("x", tmp_path, datetime(2026, 11, 1 + n, 9, 0))
    (tmp_path / "mine.md").write_text("keep")
    names = sorted(p.name for p in tmp_path.iterdir())
    assert len([n for n in names if n.startswith("raidready-")]) == advisor.KEEP_EXPORTS and "mine.md" in names


def test_export_api(webapp, monkeypatch, tmp_path):
    from tests.test_server import body, call

    monkeypatch.setattr(advisor, "export_folder", lambda: tmp_path / "exports")
    s = webapp.server
    state = body(call(s, "/api/advisor"))
    assert state["tasksLoaded"] and state["available"] > 0 and state["settings"]["kit"] == ""
    assert body(call(s, "/api/progress", "POST", {"op": "advisor", "settings": {"kit": "geared"}}))["advisor"]["kit"] == "geared"
    result = body(call(s, "/api/advisor/export", "POST"))
    assert result["name"].startswith("raidready-") and "Geared (" in result["text"]
    assert (tmp_path / "exports" / result["name"]).read_text(encoding="utf-8") == result["text"]
    assert body(call(s, "/api/advisor/open", "POST"))["folder"] == str(tmp_path / "exports")


def test_raid_end_from_both_logs_is_listed_once(webapp, monkeypatch):
    monkeypatch.setattr(webapp, "refresh_after_raid", lambda: False)
    link = webapp.link
    link._on_event(gamelogs.Event("raid", "2026-11-17 13:01:53", {"map": "bigmap", "online": True, "raidId": "9R475L"}), False)
    link._on_event(gamelogs.Event("raid_end", "2026-11-17 13:13:21", {"map": None, "raidId": None, "ping": 56, "loss": 0}), False)
    assert webapp.state()["raid"] is None
    link._on_event(gamelogs.Event("raid_end", "2026-11-17 13:13:22", {"map": "bigmap", "raidId": "9R475L"}), False)
    ends = [e for e in link.events if e["kind"] == "raid_end"]
    assert len(ends) == 1 and ends[0]["name"] == "Customs" and ends[0]["ping"] == 56
    # The next raid's end is listed again.
    link._on_event(gamelogs.Event("raid", "2026-11-17 13:23:16", {"map": "Shoreline", "online": True}), False)
    link._on_event(gamelogs.Event("raid_end", "2026-11-17 13:37:54", {"map": None, "raidId": None}), False)
    assert len([e for e in link.events if e["kind"] == "raid_end"]) == 2


# -- trader standing, accepted/failed quests, export trimming ---------------------------------

def _trader_task():
    return {"id": "q-lk", "name": "LK quest", "trader": {"id": "t-lk", "name": "Lightkeeper", "normalizedName": "lightkeeper"},
            "traderRequirements": [], "taskRequirements": [], "objectives": []}


def test_trader_requirements_lock_quests():
    pk = {"id": "t-pk", "name": "Peacekeeper", "normalizedName": "peacekeeper"}
    task = {"id": "q1", "name": "Needs PK3", "trader": pk, "objectives": [], "taskRequirements": [],
            "traderRequirements": [{"trader": pk, "requirementType": "level", "compareMethod": ">=", "value": 3},
                                   {"trader": pk, "requirementType": "reputation", "compareMethod": ">=", "value": 0.5}]}
    lk = _trader_task()
    base = {"player_level": 40, "faction": "USEC", "tasks": []}
    # Nothing entered: trader requirements are ignored, as before.
    assert advisor.quest_states([task, lk], base) == {"q1": "available", "q-lk": "available"}
    standing = dict(base, traders={"t-pk": {"level": 2}})
    assert advisor.trader_blocks(task, standing) == ["Peacekeeper LL3"]  # rep not entered: not held against you
    assert advisor.trader_blocks(lk, standing) == ["Lightkeeper not unlocked"]
    standing["traders"]["t-pk"] = {"level": 3, "rep": 0.4}
    assert advisor.trader_blocks(task, standing) == ["Peacekeeper rep 0.5"]
    standing["traders"]["t-pk"]["rep"] = 0.51
    standing["traders"]["t-lk"] = {"level": 1}
    assert advisor.quest_states([task, lk], standing) == {"q1": "available", "q-lk": "available"}


def test_lightkeeper_checklist():
    traders = [{"id": f"t-{k}", "name": k.title(), "normalizedName": k} for k in advisor.LK_MAIN_TRADERS + ("fence",)]
    tasks = [{"id": "ttl1", "name": "To the Light - Trust but Verify", "trader": {"name": "Mechanic"}}]
    progress = {"traders": {"t-prapor": {"level": 3}, "t-skier": {"level": 2}, "t-fence": {"rep": 2.5}},
                "tasks": ["ttl1"], "story": {"steps": ["tour-13"]}}
    rows = {r["label"]: r for r in advisor.lightkeeper_checklist(tasks, traders, progress)}
    assert rows["Prapor loyalty level 3"]["ok"] is True and rows["Skier loyalty level 3"]["ok"] is False
    assert rows["Jaeger loyalty level 3"]["ok"] is None and rows["Jaeger loyalty level 3"]["detail"] == "not set"
    assert rows["Fence reputation 2 or more"]["ok"] is True
    assert rows["Lighthouse unlocked (Tour: pay Mechanic)"]["ok"] is True
    assert rows["Quest: To the Light - Trust but Verify"]["ok"] is True


def test_export_orders_accepted_and_trims():
    tasks, stations, maps = demo_data()
    maps = maps + [{"id": "tut", "name": "Ground Zero Tutorial", "normalizedName": "gzt"}]
    shoot = next(t for t in tasks if t["name"] == "Shootout Picnic")
    tasks = tasks + [dict(shoot, id="tut-q", name="Tutorial thing",
                          objectives=[dict(shoot["objectives"][0], id="o-tut", maps=[{"id": "tut", "name": "Ground Zero Tutorial"}])])]
    from tarkov_display.linking import prerequisite_ids

    done = list({x for p in [shoot["id"]] for x in prerequisite_ids(p, tasks)})
    progress = {"player_level": 30, "faction": "USEC", "tasks": done, "accepted": [shoot["id"]],
                "failed": [], "pinned": [], "objectives": {}, "owned": {}, "advisor": {"goal": "Lightkeeper"}}
    text = advisor.build(progress=progress, tasks=tasks, stations=stations, maps=maps,
                         history={"sales": [{"time": "2026-11-17 13:00:00", "itemId": "x", "roubles": 5, "needed": ["Vents 3 x5"]}]})
    assert "Ground Zero Tutorial" not in text.split("## Maps (tarkov.dev)")[0]
    assert "**Shootout Picnic** (Prapor, Kappa, accepted in game)" in text
    assert "## Road to Lightkeeper" in text and "Trader levels: not entered" in text
    assert "⚠️ still needed: Vents 3 x5" in text
    progress["failed"] = [shoot["id"]]
    assert "## Failed quests (restart at the trader)" in advisor.build(progress=progress, tasks=tasks, stations=stations, maps=maps)


def test_quest_status_from_logs(webapp):
    from tarkov_display import gamelogs as gl

    tasks = webapp.store.refresh("tasks")["data"]
    qid = tasks[3]["id"]
    webapp.link._on_event(gl.Event("quest", "2026-11-17 13:00:00", {"questId": qid, "status": "started"}, "regular"), True)
    assert qid in webapp.progress.snapshot()["accepted"]
    webapp.link._on_event(gl.Event("quest", "2026-11-17 13:30:00", {"questId": qid, "status": "failed"}, "regular"), False)
    snap = webapp.progress.snapshot()
    assert qid in snap["failed"] and qid not in snap["accepted"]
    webapp.link._on_event(gl.Event("quest", "2026-11-17 14:00:00", {"questId": qid, "status": "finished"}, "regular"), False)
    snap = webapp.progress.snapshot()
    assert qid in snap["tasks"] and qid not in snap["failed"]


def test_selling_a_needed_item_warns(webapp):
    from tarkov_display import gamelogs as gl

    webapp.store.refresh("tasks"), webapp.store.refresh("hideout")
    published = []
    webapp.publish = lambda event, data: published.append((event, data))
    ledx = next(i for i in webapp.app.prices.items if i.short_name == "LEDX")
    webapp.link._on_event(gl.Event("flea", "2026-11-17 13:00:00", {"itemId": ledx.id, "count": 1, "roubles": 1}, "regular"), False)
    event = [d for e, d in published if e == "gamelog"][-1]
    assert any("Private Clinic" in n for n in event["needed"])


# -- pre-raid pack check ----------------------------------------------------------------------

def test_matching_event_from_scene_preset():
    text = line("13:01:30", "application", "scene preset path:maps/customs_preset.bundle rcid:bigmap.scenespreset.asset")
    (ev,) = gamelogs.parse_text(text)
    assert (ev.kind, ev.data) == ("matching", {"map": "bigmap"})


def test_raid_kit_for_pinned_quests():
    tasks, _, maps = demo_data()
    customs = next(m for m in maps if m["name"] == "Customs")
    aquarius = next(t for t in tasks if t["name"] == "Operation Aquarius - Part 1")
    progress = {"player_level": 30, "faction": "USEC", "tasks": [], "pinned": [aquarius["id"]], "owned": {}, "objectives": {}}
    kit = advisor.raid_kit(tasks, progress, customs["id"])
    assert kit["source"] == "pinned" and kit["quests"] == [aquarius["name"]]
    key = next(e for e in kit["bring"] if e["kind"] == "Key")
    assert "Dorm room 206 key" in key["items"] and key["have"] is False
    assert any("Dorm room 206 key" in l and "not ticked" in l for l in advisor.kit_lines(kit))
    other = next(m for m in maps if m["name"] == "Woods")
    assert advisor.raid_kit(tasks, progress, other["id"])["bring"] == []
    # Nothing pinned: accepted quests count instead.
    progress.update(pinned=[], accepted=[aquarius["id"]])
    from tarkov_display.linking import prerequisite_ids

    progress["tasks"] = prerequisite_ids(aquarius["id"], tasks)
    assert advisor.raid_kit(tasks, progress, customs["id"])["source"] == "accepted"


def test_pack_check_on_queue(webapp):
    tasks = webapp.store.refresh("tasks")["data"]
    webapp.store.refresh("maps")
    aquarius = next(t for t in tasks if t["name"] == "Operation Aquarius - Part 1")
    webapp.progress.apply({"op": "pin", "ids": [aquarius["id"]], "pinned": True})
    published = []
    webapp.publish = lambda event, data: published.append((event, data))
    webapp.link._on_event(gamelogs.Event("matching", "2026-11-17 13:01:30", {"map": "bigmap"}, "regular"), False)
    event = [d for e, d in published if e == "gamelog"][-1]
    assert event["name"] == "Customs" and any("Dorm room 206 key" in l for l in event["kit"]["lines"])
    assert not any(e["kind"] == "matching" for e in webapp.link.events)  # not listed
    webapp.app.config.logs.pack_check = False
    published.clear()
    webapp.link._on_event(gamelogs.Event("matching", "2026-11-17 13:21:56", {"map": "bigmap"}, "regular"), False)
    assert "kit" not in [d for e, d in published if e == "gamelog"][-1]
