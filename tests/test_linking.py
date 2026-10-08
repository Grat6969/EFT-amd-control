import io
import json
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from tarkov_display import secretstore, tracker
from tarkov_display.linking import prerequisite_ids
from tarkov_display.progress import Progress
from tarkov_display.tracker import TrackerClient, TrackerError, check_token, merge_progress

from test_gamelogs import RAID, append, line, make_session, quest

ORG_PVP = "PVP_0123456789abcdef01"
ORG_PVE = "PVE_abcdef0123456789ab"


# -- tokens ---------------------------------------------------------------------------

def test_secret_round_trip_and_mask():
    stored = secretstore.protect(ORG_PVP)
    assert stored != ORG_PVP and secretstore.unprotect(stored) == ORG_PVP
    assert secretstore.protect("") == "" and secretstore.unprotect("") == ""
    masked = secretstore.mask(ORG_PVP)
    assert masked.startswith("PVP_") and masked.endswith("ef01") and ORG_PVP not in masked


def test_token_rules():
    check_token("tarkovtracker.org", ORG_PVP, "regular")
    check_token("tarkovtracker.org", ORG_PVE, "pve")
    with pytest.raises(TrackerError, match="PvE token"):
        check_token("tarkovtracker.org", ORG_PVE, "regular")
    with pytest.raises(TrackerError, match="look like"):
        check_token("tarkovtracker.org", "not-a-token", "regular")
    check_token("tarkovtracker.io", "abc123def456", "pve")  # .io tokens have no mode prefix
    with pytest.raises(TrackerError):
        check_token("tarkovtracker.io", "has spaces in it", "pve")
    with pytest.raises(TrackerError):
        check_token("example.com", ORG_PVP, "regular")


# -- API client ---------------------------------------------------------------------------

class FakeHTTP:
    def __init__(self, monkeypatch, responses):
        self.responses = responses
        self.requests = []
        monkeypatch.setattr(urllib.request, "urlopen", self.urlopen)

    def urlopen(self, req, timeout):
        self.requests.append(req)
        status, body = self.responses[(req.get_method(), req.full_url)]
        if status != 200:
            raise urllib.error.HTTPError(req.full_url, status, "error", {}, io.BytesIO(body.encode()))

        class Resp:
            def read(self_inner):
                return body.encode()

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                pass

        return Resp()


PROGRESS = {"data": {
    "tasksProgress": [{"id": "t1", "complete": True}, {"id": "t2", "complete": True, "failed": True},
                      {"id": "t3", "complete": False}, {"id": "t4", "complete": True, "invalid": True},
                      {"id": "t5", "complete": True}],
    "hideoutModulesProgress": [{"id": "med-1", "complete": True}, {"id": "med-2", "complete": True},
                               {"id": "lav-1", "complete": False}],
    "displayName": "Tester", "userId": "u1", "playerLevel": 33, "gameEdition": 1, "pmcFaction": "BEAR",
}, "meta": {"self": "u1"}}


def test_client_requests(monkeypatch):
    base = "https://api.tarkovtracker.org"
    http = FakeHTTP(monkeypatch, {
        ("GET", base + "/token"): (200, json.dumps({"success": True, "permissions": ["GP", "WP"], "token": ORG_PVP, "gameMode": "pvp"})),
        ("GET", base + "/progress"): (200, json.dumps(PROGRESS)),
        ("POST", base + "/progress/tasks"): (200, "OK"),
    })
    c = TrackerClient("tarkovtracker.org", ORG_PVP)
    assert c.token_info() == {"permissions": ["GP", "WP"], "gameMode": "pvp"}
    assert c.progress()["playerLevel"] == 33
    c.set_tasks(["a", "b"])
    sent = http.requests[-1]
    assert sent.get_header("Authorization") == f"Bearer {ORG_PVP}"
    assert json.loads(sent.data) == [{"id": "a", "state": "completed"}, {"id": "b", "state": "completed"}]
    assert TrackerClient("tarkovtracker.io", "tok").base == "https://tarkovtracker.io/api/v2"


def test_client_errors(monkeypatch):
    base = "https://api.tarkovtracker.org"
    FakeHTTP(monkeypatch, {("GET", base + "/progress"): (401, "Unauthorized"),
                           ("GET", base + "/token"): (500, "boom")})
    c = TrackerClient("tarkovtracker.org", ORG_PVP)
    with pytest.raises(TrackerError, match="refused the request"):
        c.progress()
    with pytest.raises(TrackerError, match="HTTP 500: boom"):
        c.token_info()


STATIONS = [
    {"id": "medstation", "levels": [{"id": "med-1", "level": 1}, {"id": "med-2", "level": 2}, {"id": "med-3", "level": 3}]},
    {"id": "lavatory", "levels": [{"id": "lav-1", "level": 1}]},
    {"id": "stash", "levels": [{"id": "stash-1", "level": 1}]},
]


def test_merge_only_adds(tmp_path):
    p = Progress(tmp_path / "p.json")
    p.apply({"op": "tasks", "ids": ["mine"], "done": True})
    p.apply({"op": "hideout", "station": "stash", "level": 1})
    p.apply({"op": "profile", "player_level": 40})
    summary = merge_progress(p, PROGRESS["data"], STATIONS)
    snap = p.snapshot()
    assert snap["tasks"] == ["mine", "t1", "t5"]  # failed/invalid/incomplete skipped, nothing removed
    assert snap["hideout"] == {"medstation": 2, "stash": 1}
    assert snap["player_level"] == 40  # never lowered
    assert snap["faction"] == "BEAR"
    assert summary == {"tasks": 2, "trackerTasks": 2, "hideout": 1, "hideoutKnown": True, "level": None,
                       "faction": "BEAR", "name": "Tester"}
    assert merge_progress(p, PROGRESS["data"], None)["tasks"] == 0  # running again adds nothing


def test_prerequisite_ids():
    tasks = [
        {"id": "a", "taskRequirements": []},
        {"id": "b", "taskRequirements": [{"task": {"id": "a"}, "status": ["complete"]}]},
        {"id": "c", "taskRequirements": [{"task": {"id": "b"}, "status": ["complete"]}, {"task": {"id": "x"}, "status": ["active"]}]},
    ]
    assert prerequisite_ids("c", tasks) == ["b", "a"]
    assert prerequisite_ids("a", tasks) == [] and prerequisite_ids("zz", None) == []


# -- the app with demo data --------------------------------------------------------------------

@pytest.fixture()
def web(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    from tests import demo

    demo.install(monkeypatch)
    from tarkov_display.webapp import WebApp

    app = WebApp(open_on_start=False, port=0)
    app.app.prices.refresh()
    for name in ("tasks", "hideout", "maps"):
        app.store.refresh(name)
    published = []
    app.publish = lambda event, data: published.append((event, data))
    app.published = published
    yield app
    app.link.stop_logs()
    app.server.httpd.server_close()


def demo_task(name):
    from tests import demo

    return next(q for q in demo.QUESTS if q["name"] == name)


def test_finished_quest_marks_earlier_ones(web):
    painkiller = demo_task("Painkiller")
    new = web.link.finish_quests("regular", [painkiller["id"]])
    names = {q["id"]: q["name"] for q in __import__("tests.demo", fromlist=["QUESTS"]).QUESTS}
    assert [names[i] for i in new] == ["Painkiller", "Sanitary Standards - Part 1", "Shortage"]
    assert web.published[-1][0] == "progress"
    assert web.link.finish_quests("regular", [painkiller["id"]]) == []

    # A PvE quest goes to PvE progress, not the PvP progress on screen.
    web.link.finish_quests("pve", [demo_task("Debut")["id"]])
    assert demo_task("Debut")["id"] not in web.progress.snapshot()["tasks"]
    assert Progress(web.cfg_dir / "progress_pve.json").snapshot()["tasks"] == [demo_task("Debut")["id"]]


def test_log_events_flow_to_progress_and_window(web, tmp_path):
    logs = tmp_path / "Logs"
    app_log, notes = make_session(logs, "log_old", time.time() - 100)
    append(app_log, line("19:00:00", "application", "Session mode: Regular"))
    append(notes, quest("19:10:00", demo_task("Checking")["id"]))
    web.link.logs_change({"enabled": True, "path": str(logs)})
    follower = web.link.follower
    follower.stop()  # drive it by hand
    follower.check()
    # History: applied quietly.
    assert demo_task("Checking")["id"] in web.progress.snapshot()["tasks"]
    assert demo_task("Debut")["id"] in web.progress.snapshot()["tasks"]  # its prerequisite
    assert not [e for e, d in web.published if e == "gamelog"]
    assert web.link.history_quests == 2

    append(notes, quest("20:00:00", demo_task("Shortage")["id"]))
    append(app_log, RAID + line("20:30:00", "application", "Session mode: Pve"))
    follower.check()
    events = [d for e, d in web.published if e == "gamelog"]
    kinds = [d["kind"] for d in events]
    assert kinds == ["raid", "mode", "quest"]
    raid = events[0]
    assert raid["name"] == "Customs" and raid["normalizedName"] == "customs" and raid["autoMap"] is True
    assert events[1]["gameMode"] == "pve" and events[1]["appMode"] == "regular"
    assert events[2]["name"] == "Shortage" and events[2]["trader"] == "Therapist" and events[2]["added"] == 1
    state = web.link.logs_state()
    assert state["running"] and state["session"] == "log_old" and state["gameMode"] == "pve"
    assert [e["kind"] for e in state["events"]] == ["quest", "mode", "raid"]


def test_scan_and_apply_old_logs(web, tmp_path):
    logs = tmp_path / "Logs"
    app_log, notes = make_session(logs, "log_1", time.time() - 100)
    append(app_log, line("10:00:00", "application", "Session mode: Regular"))
    append(notes, quest("10:30:00", demo_task("Painkiller")["id"]))
    web.link.logs_change({"path": str(logs)})
    summary = web.link.scan()
    assert summary["sessions"] == 1
    assert summary["modes"]["regular"] == {"finished": 1, "new": 3}  # + 2 earlier quests
    assert web.progress.snapshot()["tasks"] == []  # nothing changes until you apply
    assert web.link.apply_scan() == {"added": {"regular": 3}}
    assert len(web.progress.snapshot()["tasks"]) == 3


def test_tracker_settings_import_and_push(web, monkeypatch):
    link = web.link
    with pytest.raises(ValueError, match="PvE token"):
        link.tracker_change({"token": {"mode": "regular", "value": ORG_PVE}})
    state = link.tracker_change({"token": {"mode": "regular", "value": ORG_PVP}, "push": True})
    assert state["tokens"]["regular"] == secretstore.mask(ORG_PVP) and state["tokens"]["pve"] is None
    stored = web.app.config.tracker.tokens["regular"]
    assert secretstore.unprotect(stored) == ORG_PVP
    assert stored.startswith("dpapi:" if sys.platform == "win32" else "plain:")
    shortage = demo_task("Shortage")["id"]
    medstation = next(s for s in web.store.snapshot("hideout")["data"] if s["name"] == "Medstation")

    calls = []

    class FakeClient:
        def __init__(self, domain, token):
            assert token == ORG_PVP

        def progress(self):
            return {"tasksProgress": [{"id": shortage, "complete": True}],
                    "hideoutModulesProgress": [{"id": medstation["levels"][0]["id"], "complete": True}],
                    "playerLevel": 12, "pmcFaction": "USEC"}

        def set_tasks(self, ids, state="completed"):
            calls.append((list(ids), state))

    monkeypatch.setattr("tarkov_display.linking.TrackerClient", FakeClient)
    summary = link.tracker_import("regular")
    assert summary["tasks"] == 1 and summary["hideout"] == 1 and summary["level"] == 12
    assert web.progress.snapshot()["hideout"] == {medstation["id"]: 1}
    assert web.app.config.tracker.last["regular"]["summary"]["tasks"] == 1

    link.push_completed("regular", ["q1"])
    for _ in range(100):
        if calls:
            break
        time.sleep(0.02)
    assert calls == [(["q1"], "completed")]

    # Switching site drops tokens for the old site.
    assert link.tracker_change({"domain": "tarkovtracker.io"})["tokens"] == {"regular": None, "pve": None}
    with pytest.raises(ValueError, match="token first"):
        link.tracker_import("regular")


def test_api_routes(web):
    from test_server import body, call

    web.server.start()
    try:
        assert body(call(web.server, "/api/gamelog"))["enabled"] is False
        assert body(call(web.server, "/api/tracker"))["domain"] == "tarkovtracker.org"
        status, raw, _ = call(web.server, "/api/gamelog", "POST", {"path": "/definitely/not/here"})
        assert status == 400 and b"doesn't exist" in raw
        status, raw, _ = call(web.server, "/api/tracker/import", "POST", {"mode": "regular"})
        assert status == 400 and b"token first" in raw
    finally:
        web.server.stop()


def test_token_mode_helper():
    assert tracker.token_mode("tarkovtracker.org", ORG_PVE) == "pve"
    assert tracker.token_mode("tarkovtracker.org", "SZN_0123456789abcdef01") == "seasonal"
    assert tracker.token_mode("tarkovtracker.io", ORG_PVE) is None


def test_events_load_missing_data(web, tmp_path):
    # Fresh store: maps and quests not downloaded yet when the raid starts.
    from tarkov_display.datasets import DataStore

    web.store = DataStore(web.cfg_dir / "fresh", "regular", on_update=lambda n: None)
    logs = tmp_path / "Logs"
    app_log, notes = make_session(logs, "log_new", time.time())
    web.link.logs_change({"enabled": True, "path": str(logs)})
    follower = web.link.follower
    follower.stop()
    follower.check()  # nothing yet
    append(app_log, RAID)
    append(notes, quest("20:30:00", demo_task("Painkiller")["id"]))
    follower.check()
    events = {d["kind"]: d for e, d in web.published if e == "gamelog"}
    assert events["raid"]["name"] == "Customs"
    assert events["quest"]["name"] == "Painkiller" and events["quest"]["added"] == 3


def test_mode_switch_is_one_step_for_log_quests(web):
    # While a quest from the logs is being saved, the switch waits, so the
    # quest can't land in the other mode's progress.
    switched = threading.Event()
    with web.link.lock:
        threading.Thread(target=lambda: (web.set_game_mode("pve"), switched.set()), daemon=True).start()
        assert not switched.wait(0.3)
        assert web.app.config.game_mode == "regular"
    assert switched.wait(10)
    web.app.prices.stop()
    assert web.app.config.game_mode == "pve" and web.store.game_mode == "pve"
    web.link.finish_quests("pve", [demo_task("Debut")["id"]])
    assert web.progress.snapshot()["tasks"] == [demo_task("Debut")["id"]]
    assert Progress(web.cfg_dir / "progress_regular.json").snapshot()["tasks"] == []
