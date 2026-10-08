import json
import threading
import urllib.error
import urllib.request

import pytest

from tarkov_display.server import Server, find_running

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(server, path, method="GET", body=None, token=True, headers=None, raw=None):
    hdrs = dict(headers or {})
    if token:
        hdrs["X-Token"] = server.token
    data = raw
    if body is not None:
        data = json.dumps(body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(f"http://127.0.0.1:{server.port}{path}", data=data, method=method, headers=hdrs)
    try:
        with OPENER.open(req, timeout=10) as resp:
            return resp.status, resp.read(), resp.headers
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers


class FakeCtx:
    def __init__(self):
        self.clients = []
        self.changes = []

    def on_clients(self, n):
        self.clients.append(n)

    def state(self):
        return {"watcher": "waiting for game"}

    def bootstrap(self):
        return {"version": "test"}

    def progress_change(self, body):
        if body.get("op") == "bad":
            raise ValueError("unknown change 'bad'")
        self.changes.append(body)
        return {"ok": True}

    def dataset(self, name, wait):
        raise KeyError(f"unknown dataset {name}")


@pytest.fixture()
def server():
    s = Server(FakeCtx(), 0)
    s.start()
    yield s
    s.stop()


def test_token_and_host_are_required(server):
    assert call(server, "/api/bootstrap")[0] == 200
    assert call(server, "/api/bootstrap", token=False)[0] == 403
    status, body, _ = call(server, "/api/bootstrap", headers={"Host": "evil.example"})
    assert status == 403 and b"bad host" in body
    # Hello is open (used to find a running copy) but still checks the host.
    assert call(server, "/api/hello", token=False)[0] == 200
    assert find_running(server.port)["app"] == "tarkov-companion"
    assert find_running(1) is None


def test_index_carries_token_and_strict_csp(server):
    status, body, headers = call(server, "/", token=False)
    assert status == 200 and server.token.encode() in body
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert headers["Cache-Control"] == "no-store"


def test_static_files_and_traversal(server, monkeypatch):
    import mimetypes

    # Windows registries sometimes map .css/.js to text/plain; we must not care.
    monkeypatch.setattr(mimetypes, "guess_type", lambda *a, **k: ("text/plain", None))
    status, body, headers = call(server, "/static/js/lib.js", token=False)
    assert status == 200 and headers["Content-Type"].startswith("text/javascript")
    assert call(server, "/static/css/app.css", token=False)[2]["Content-Type"].startswith("text/css")
    for path in ("/static/../server.py", "/static/%2e%2e/server.py", "/static/../../tarkov_display/server.py", "/server.py"):
        req = urllib.request.Request(f"http://127.0.0.1:{server.port}{path}")
        try:
            OPENER.open(req, timeout=5)
            raise AssertionError(f"{path} was served")
        except urllib.error.HTTPError as exc:
            assert exc.code in (403, 404)


def test_post_rules(server):
    assert call(server, "/api/progress", "POST", {"op": "tasks"})[0] == 200
    status, body, _ = call(server, "/api/progress", "POST", {"op": "bad"})
    assert status == 400 and b"unknown change" in body
    status, _, _ = call(server, "/api/progress", "POST", raw=b'{"op":"tasks"}', headers={"Content-Type": "text/plain"})
    assert status == 415  # plain form posts can't drive the app
    status, _, _ = call(server, "/api/progress", "POST", raw=b"{not json", headers={"Content-Type": "application/json"})
    assert status == 400
    assert call(server, "/api/nothing")[0] == 404
    assert call(server, "/api/data/nope")[0] == 400


def test_events_stream(server):
    got = []

    def listen():
        req = urllib.request.Request(f"http://127.0.0.1:{server.port}/api/events?token={server.token}")
        with OPENER.open(req, timeout=10) as resp:
            for raw in resp:
                line = raw.decode().strip()
                if line.startswith("event:"):
                    got.append(line.split(":", 1)[1].strip())
                if len(got) >= 2:
                    return

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    for _ in range(100):
        if server.events.count:
            break
        threading.Event().wait(0.02)
    server.events.publish("scan", {"item": None})
    t.join(5)
    assert got == ["state", "scan"]
    assert server.ctx.clients[0] == 1


# -- the real app with demo data -----------------------------------------------------

@pytest.fixture()
def webapp(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from tests import demo

    demo.install(monkeypatch)
    from tarkov_display.webapp import WebApp

    app = WebApp(open_on_start=False, port=0)
    app.app.prices.refresh()
    app.server.start()
    yield app
    app.server.stop()


def body(resp):
    return json.loads(resp[1])


def test_app_api_end_to_end(webapp):
    s = webapp.server
    boot = body(call(s, "/api/bootstrap"))
    assert boot["settings"]["gameMode"] == "regular" and boot["progress"]["player_level"] == 1

    items = body(call(s, "/api/items"))["items"]
    ledx = next(i for i in items if i["short"] == "LEDX")
    assert ledx["avg"] == 1020000 and ledx["trader"] == "Therapist"

    tasks = body(call(s, "/api/data/tasks?wait=10"))["data"]
    assert any(t["name"] == "Private Clinic" for t in tasks)

    detail = body(call(s, f"/api/item/{ledx['id']}"))
    assert detail["item"]["name"].startswith("LEDX") and detail["history"]

    prog = body(call(s, "/api/progress", "POST", {"op": "tasks", "ids": [tasks[0]["id"]], "done": True}))
    assert prog["tasks"] == [tasks[0]["id"]]

    d = body(call(s, "/api/display", "POST", {"op": "select", "name": "night"}))
    assert d["active"] == "night"
    d = body(call(s, "/api/display", "POST", {"op": "save_profile", "name": "night", "profile": {
        "brightness": 999, "contrast": 120, "saturation": 150, "gamma": 9, "temperature": None}}))
    assert d["profiles"]["night"]["brightness"] == 100 and d["profiles"]["night"]["gamma"] == 3.0
    assert call(s, "/api/display", "POST", {"op": "delete_profile", "name": "nope"})[0] == 400


def test_needs_follow_progress(webapp):
    ledx = next(i for i in webapp.app.prices.items if i.short_name == "LEDX")
    webapp.store.refresh("tasks")
    webapp.store.refresh("hideout")
    needs = webapp.item_needs(ledx.id)
    assert any("Private Clinic x2 FiR" in text for _, text in needs)
    clinic = next(t for t in webapp.store.snapshot("tasks")["data"] if t["name"] == "Private Clinic")
    webapp.progress.apply({"op": "tasks", "ids": [clinic["id"]], "done": True})
    assert not any("Private Clinic" in text for _, text in webapp.item_needs(ledx.id))


def test_game_mode_switch_swaps_data(webapp):
    s = webapp.server
    call(s, "/api/progress", "POST", {"op": "profile", "player_level": 30})
    old_store = webapp.store
    boot = body(call(s, "/api/settings", "POST", {"gameMode": "pve"}))
    assert boot["settings"]["gameMode"] == "pve"
    assert webapp.store is not old_store and webapp.store.game_mode == "pve"
    assert boot["progress"]["player_level"] == 1  # PvE progress is separate
    assert call(s, "/api/settings", "POST", {"gameMode": "arena"})[0] == 400
    body(call(s, "/api/settings", "POST", {"gameMode": "regular"}))
    assert body(call(s, "/api/progress"))["player_level"] == 30
