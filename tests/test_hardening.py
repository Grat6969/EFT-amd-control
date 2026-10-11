"""Hostile and malformed input: what a broken or future log format, a damaged
progress file, a hostile web page or a bad download must not be able to do.

The fuzz tests use a fixed seed, so a failure always reproduces.
"""

import http.client
import io
import math
import pathlib
import random
import string
import time
import zipfile

import pytest

from tarkov_display import progress as progress_mod
from tarkov_display import staticapi, updater
from tarkov_display.gamelogs import LogFollower, parse_text, scan_history
from tarkov_display.progress import Progress, ProgressError
from tarkov_display.server import MAX_BODY, Server

from test_gamelogs import FLEA, RAID, append, line, make_session, notification, quest
from test_server import FakeCtx

SEED = 20261011


def random_value(rng: random.Random, depth: int = 0):
    """Any value a JSON document (or json.loads, which accepts NaN and
    Infinity) can hold."""
    choices = ["none", "bool", "int", "big", "float", "special", "str", "unicode"]
    if depth < 3:
        choices += ["list", "dict"]
    kind = rng.choice(choices)
    if kind == "none":
        return None
    if kind == "bool":
        return rng.random() < 0.5
    if kind == "int":
        return rng.randint(-5, 20)
    if kind == "big":
        return rng.choice([10 ** 30, -(10 ** 30), 2 ** 63])
    if kind == "float":
        return rng.uniform(-1e6, 1e6)
    if kind == "special":
        return rng.choice([math.inf, -math.inf, math.nan, 1e308])
    if kind == "str":
        return "".join(rng.choice(string.ascii_letters + string.digits + " _-") for _ in range(rng.randint(0, 30)))
    if kind == "unicode":
        return rng.choice(["Ёжик", "\u202e", "\x00", "🙂" * 3, "a" * 5000, "", " "])
    if kind == "list":
        return [random_value(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    return {rng.choice(["type", "id", "data", "message", "x", "templateId"]): random_value(rng, depth + 1)
            for _ in range(rng.randint(0, 4))}


# -- the local web server ------------------------------------------------------------------

@pytest.fixture()
def server():
    s = Server(FakeCtx(), 0)
    s.start()
    yield s
    s.stop()


def request(server, method, path, headers=None, body=None, timeout=5):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=timeout)
    try:
        conn.putrequest(method, path)
        for k, v in (headers or {}).items():
            conn.putheader(k, v)
        conn.endheaders()
        if body:
            conn.send(body)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


HOSTILE_STATIC = [
    "/static/%5C%5Cevil.example%5Cshare%5Cx.js",    # \\evil.example\share\x.js
    "/static/..%5C..%5Cserver.py",                   # ..\..\server.py
    "/static/C:/Windows/win.ini",
    "/static/C%3A%5CWindows%5Cwin.ini",
    "/static/js/%2E%2E/%2E%2E/server.py",
    "/static//etc/passwd",
    "/static/.hidden",
    "/static/js/./lib.js",
    "/static/js/lib.js/",
    "/static/js/lib.js%00.png",
    "/static/%E2%80%AEjs/lib.js",
    "/static/",
]


def test_static_names_are_checked_before_the_disk_is_touched(server, monkeypatch):
    touched = []
    real_resolve, real_is_file = pathlib.Path.resolve, pathlib.Path.is_file

    def resolve(self, *a, **k):
        touched.append(str(self))
        return real_resolve(self, *a, **k)

    def is_file(self, *a, **k):
        touched.append(str(self))
        return real_is_file(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "resolve", resolve)
    monkeypatch.setattr(pathlib.Path, "is_file", is_file)
    for path in HOSTILE_STATIC:
        status, _ = request(server, "GET", path)
        assert status == 404, path
    assert touched == [], f"looked at the disk for a hostile name: {touched}"
    status, body = request(server, "GET", "/static/js/lib.js")
    assert status == 200 and body


def test_bad_content_length_is_refused_not_waited_on(server):
    auth = {"X-Token": server.token, "Content-Type": "application/json"}
    for value, expected in (("-1", 400), ("abc", 400), (str(MAX_BODY + 1), 413)):
        start = time.time()
        status, _ = request(server, "POST", "/api/progress", {**auth, "Content-Length": value})
        assert status == expected, value
        assert time.time() - start < 3, f"Content-Length {value} made the server wait"


def test_head_and_wrong_methods(server):
    assert request(server, "HEAD", "/static/js/lib.js")[0] == 200
    assert request(server, "POST", "/static/js/lib.js", {"Content-Length": "0"})[0] == 405
    assert request(server, "GET", "/api/progress", {"X-Token": "x" * 10_000})[0] == 403


# -- game logs: a future or damaged log format ----------------------------------------------

def test_odd_notification_shapes_do_not_crash_the_parser():
    odd = [
        notification("20:00:00", "just a string"),
        notification("20:00:01", ["a", "list"]),
        notification("20:00:02", {"type": [12], "templateId": "q1 successMessageText"}),
        notification("20:00:03", {"type": 12, "templateId": {"not": "a string"}}),
        notification("20:00:04", {"type": 4, "templateId": "5bdabfb886f7743e152e867e 0",
                                  "systemData": "nope", "items": ["nope"]}),
        notification("20:00:05", {"type": 4, "templateId": "5bdabfb886f7743e152e867e 0",
                                  "items": {"data": [{"_tpl": "5449016a4bdc2d6f028b456f", "upd": {"StackObjectsCount": "9"}}]}}),
        line("20:00:06", "notifications", "Got notification | UserMatchOver") + "[1, 2]\n",
    ]
    for text in odd:
        parse_text(text)  # must not raise


def test_one_bad_entry_does_not_hide_the_good_ones():
    text = (quest("20:00:00", "first-quest") + notification("20:00:01", "broken")
            + quest("20:00:02", "second-quest"))
    assert [e.data["questId"] for e in parse_text(text) if e.kind == "quest"] == ["first-quest", "second-quest"]


def test_log_follower_and_history_survive_a_bad_entry(tmp_path):
    logs = tmp_path / "Logs"
    app, notes = make_session(logs, "log_2025.11.20_19-45-12_1.0.0.1", time.time() - 100)
    append(app, line("19:45:12", "application", "Session mode: Regular"))
    append(notes, quest("19:50:00", "before") + notification("19:51:00", "broken") + quest("19:52:00", "after"))
    seen = []
    follower = LogFollower(logs, lambda ev, history: seen.append(ev))
    follower.check()
    assert [e.data["questId"] for e in seen if e.kind == "quest"] == ["before", "after"]
    result = scan_history(logs)
    assert result["modes"]["regular"]["finished"] == ["before", "after"]


def test_parser_fuzz():
    rng = random.Random(SEED)
    valid = [RAID, FLEA, quest("20:20:00", "5936d90786f7742b1420ba5b"),
             line("19:45:12", "application", "Session mode: Pve"),
             line("20:40:00", "notifications", "Got notification | UserMatchOver") + '{"location": "bigmap"}\n']
    for _ in range(1500):
        parts = []
        for _ in range(rng.randint(1, 5)):
            roll = rng.random()
            if roll < 0.35:
                parts.append(rng.choice(valid))
            elif roll < 0.7:
                message = random_value(rng) if rng.random() < 0.3 else {
                    k: random_value(rng) for k in rng.sample(["type", "templateId", "systemData", "items", "_id"], 3)}
                parts.append(notification("20:30:00", message))
            else:
                text = rng.choice(valid)
                cut = rng.randint(0, len(text))
                junk = "".join(rng.choice("{}[]\":,|\n x9\u0451\ufeff") for _ in range(rng.randint(0, 20)))
                parts.append(text[:cut] + junk + text[cut:])
        for ev in parse_text("".join(parts)):
            assert isinstance(ev.data, dict)
            if ev.kind == "quest":
                assert isinstance(ev.data["questId"], str) and ev.data["status"] in ("finished", "started", "failed")
            if ev.kind == "flea":
                assert isinstance(ev.data["count"], int) and isinstance(ev.data["roubles"], int)


# -- progress: hand-edited files and odd requests -------------------------------------------

def test_progress_file_with_huge_or_odd_numbers_still_loads(tmp_path):
    path = tmp_path / "progress.json"
    for doc in ('{"player_level": 1e999}', '{"player_level": Infinity, "hideout": {"5d388e97081959000a123acf": Infinity}}',
                '{"objectives": {"abc": NaN, "def": 1e400}, "owned": {"x": -Infinity}}', "null", "[1,2,3]", '"text"', "{"):
        path.write_text(doc, encoding="utf-8")
        snap = Progress(path).snapshot()  # must not raise
        assert snap == progress_mod._clean(snap)


def test_progress_fuzz(tmp_path):
    rng = random.Random(SEED)
    path = tmp_path / "progress.json"
    p = Progress(path)
    kinds = ["tasks", "achievements", "pin", "objective", "hideout", "owned", "profile", "reset", "nope", None, 7]
    fields = ["ids", "done", "pinned", "id", "count", "station", "level", "item", "player_level",
              "intel_center", "hideout_management", "faction", "what"]
    good_ids = ["5936d90786f7742b1420ba5b", "59674cd986f7744ab26e32f2"]
    for _ in range(3000):
        op = {"op": rng.choice(kinds)}
        for name in rng.sample(fields, rng.randint(0, 5)):
            op[name] = rng.choice([random_value(rng), good_ids, good_ids[0], rng.randint(0, 80), "USEC", "all"])
        if rng.random() < 0.05:
            op = random_value(rng)
        try:
            p.apply(op)
        except ProgressError:
            continue
        snap = p.snapshot()
        assert snap == progress_mod._clean(snap), op
        assert Progress(path).snapshot() == snap, op


# -- tarkov.dev file helpers ---------------------------------------------------------------

def test_jsonpath_and_translate_fuzz():
    rng = random.Random(SEED)
    steps = [".name", "..description", "[*]", ".*", "['a','b']", ".data", "..", "[", "']", ".0", "[*][*]"]
    for _ in range(2000):
        root = random_value(rng)
        path = "$" + "".join(rng.choice(steps) for _ in range(rng.randint(0, 5)))
        try:
            staticapi.jsonpath(root, path)
        except ValueError:
            pass  # a path tarkov.dev's files can't contain may be refused, but not crash otherwise
        doc = {"data": random_value(rng), "translations": [path, random_value(rng)]}
        locale = {"k": "v"} if rng.random() < 0.5 else random_value(rng)
        try:
            staticapi.translate(doc, locale if isinstance(locale, dict) else {}, [path])
        except ValueError:
            pass


# -- updates: a damaged or hostile download -------------------------------------------------

def app_zip(extra: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("top/tarkov_display/__init__.py", '__version__ = "9.0.0"\n')
        for name, text in extra.items():
            zf.writestr(name, text)
    return buf.getvalue()


@pytest.mark.parametrize("name", ["../evil.txt", "/abs/evil.txt", "top/../../evil.txt",
                                  "top\\..\\..\\evil.txt", "C:/evil.txt", "top/C:evil.txt"])
def test_update_refuses_paths_outside_the_folder(tmp_path, name):
    root = tmp_path / "app"
    (root / "tarkov_display").mkdir(parents=True)
    (root / "tarkov_display" / "__init__.py").write_text('__version__ = "1.0.0"\n')
    with pytest.raises(RuntimeError):
        updater.Updater(root=root).apply(data=app_zip({name: "pwned"}))
    assert (root / "tarkov_display" / "__init__.py").read_text() == '__version__ = "1.0.0"\n'
    assert not any(p.name.endswith("evil.txt") for p in tmp_path.rglob("*"))


def test_update_keeps_the_bundled_python(tmp_path):
    root = tmp_path / "app"
    (root / "tarkov_display").mkdir(parents=True)
    (root / "tarkov_display" / "__init__.py").write_text('__version__ = "1.0.0"\n')
    (root / "tarkov_display" / "__pycache__").mkdir()
    (root / "python" / "Lib" / "__pycache__").mkdir(parents=True)
    (root / "python" / "pythonw.exe").write_text("exe")
    (root / "python" / "Lib" / "__pycache__" / "os.cpython-312.pyc").write_text("cache")
    updater.Updater(root=root).apply(data=app_zip({"top/run.bat": "new"}))
    assert (root / "tarkov_display" / "__init__.py").read_text() == '__version__ = "9.0.0"\n'
    assert (root / "python" / "pythonw.exe").read_text() == "exe"
    assert (root / "python" / "Lib" / "__pycache__" / "os.cpython-312.pyc").exists()
    assert not (root / "tarkov_display" / "__pycache__").exists()
