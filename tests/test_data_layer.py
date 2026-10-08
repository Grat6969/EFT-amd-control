import io
import json
import os
import re
import time
import zipfile
from pathlib import Path

import pytest

from tarkov_display import datasets, progress, updater
from tarkov_display.datasets import DATASETS, DataStore
from tarkov_display.progress import Progress, ProgressError


# -- datasets -------------------------------------------------------------------

class FakeClient:
    def __init__(self, fail=False):
        self.fail = fail
        self.queries = []
        self.urls = []
        self.game_mode = "regular"

    def query(self, template, variables=None, **params):
        self.queries.append((template, variables))
        if self.fail:
            raise RuntimeError("HTTP 422: GraphQL server unavailable. Try again later.")
        if "query Item(" in template:
            return {"item": {"id": variables["id"], "name": "LEDX"}, "history": [{"price": 1, "timestamp": "0"}]}
        key = re.search(r"query \w+\s*\{\s*(\w+)", template).group(1)
        return {key: [{"id": "x", "query": key}]}

    def get_json(self, url):
        self.urls.append(url)
        if self.fail:
            raise RuntimeError("offline")
        if url.endswith("maps.json"):
            return [{"normalizedName": "customs", "maps": [
                {"key": "customs", "projection": "interactive"},
                {"key": "customs-2d", "projection": "2D", "author": "monki", "authorLink": "https://x"},
                {"key": "customs-3d", "projection": "3D", "author": "re3mr"},
            ]}]
        return [{"name": "1.0.0.0", "start": "2025-11-15T09:00:00.000Z"}]


def test_get_fetches_and_caches(tmp_path):
    client = FakeClient()
    updates = []
    store = DataStore(tmp_path, "regular", client, on_update=updates.append)
    entry = store.get("tasks", wait=5)
    assert entry["data"] == [{"id": "x", "query": "tasks"}] and entry["error"] is None
    assert updates == ["tasks"]
    assert (tmp_path / "data_regular_tasks.json").exists()

    # Fresh data is served without asking tarkov.dev again.
    store.get("tasks", wait=5)
    assert len(client.queries) == 1

    # A new store (next app start) reads the disk cache.
    again = DataStore(tmp_path, "regular", FakeClient(fail=True))
    assert again.snapshot("tasks")["data"] == [{"id": "x", "query": "tasks"}]


def test_failure_keeps_old_data_and_reports_error(tmp_path):
    store = DataStore(tmp_path, "regular", FakeClient())
    store.refresh("barters")
    store.client = FakeClient(fail=True)
    entry = store.refresh("barters")
    assert entry["data"] == [{"id": "x", "query": "barters"}]
    assert "GraphQL server unavailable" in entry["error"]


def test_stale_data_refreshes_in_background(tmp_path):
    client = FakeClient()
    store = DataStore(tmp_path, "regular", client)
    store.refresh("status")
    store._entries["status"]["updated"] = time.time() - DATASETS["status"].ttl - 1
    store.get("status")  # returns old data right away, refreshes behind
    for _ in range(50):
        if len(client.queries) == 2:
            break
        time.sleep(0.02)
    assert len(client.queries) == 2


def test_cache_files_per_game_mode(tmp_path):
    pve = DataStore(tmp_path, "pve", FakeClient())
    pve.refresh("tasks")
    pve.refresh("achievements")
    assert (tmp_path / "data_pve_tasks.json").exists()
    assert (tmp_path / "data_all_achievements.json").exists()  # same in both modes
    assert DataStore(tmp_path, "regular", FakeClient(fail=True)).snapshot("tasks")["data"] is None


def test_map_images_from_tarkov_dev_data():
    images = DATASETS["mapimages"].fetch(FakeClient())
    customs = images["customs"]
    assert [i["key"] for i in customs["images"]] == ["customs-2d", "customs-3d"]
    assert customs["images"][0]["url"] == "https://tarkov.dev/maps/customs-2d.jpg"
    assert customs["images"][0]["author"] == "monki"
    assert customs["interactive"] == "https://tarkov.dev/map/customs"


def test_item_details_use_variables_and_cache():
    client = FakeClient()
    store = DataStore(None, "regular", client)
    result = store.item("5c0530ee86f774697952d952")
    assert result["item"]["name"] == "LEDX" and result["history"]
    assert client.queries[0][1] == {"id": "5c0530ee86f774697952d952"}
    store.item("5c0530ee86f774697952d952")
    assert len(client.queries) == 1
    with pytest.raises(ValueError):
        store.item('x") { injected }')


def test_unknown_dataset():
    with pytest.raises(KeyError):
        DataStore(None).get("nope")


@pytest.mark.skipif(not os.environ.get("TARKOV_SCHEMA"), reason="set TARKOV_SCHEMA to tarkov-api's schema-static.mjs")
def test_queries_match_tarkov_dev_schema():
    from graphql import build_schema, parse, validate

    from tarkov_display import prices

    sdl = re.search(r"`(.*)`", Path(os.environ["TARKOV_SCHEMA"]).read_text(), re.S).group(1)
    schema = build_schema(sdl)
    queries = [v for k, v in vars(datasets).items() if k.endswith("_QUERY")]
    queries += [v for k, v in vars(prices).items() if k.endswith("_QUERY")]
    for query in queries:
        for mode in ("", ", gameMode: pve"):
            errors = validate(schema, parse(query % {"mode": mode, "limit": 10, "offset": 0}))
            assert not errors, (query[:40], errors)


# -- progress -------------------------------------------------------------------

def test_progress_changes_and_persists(tmp_path):
    path = tmp_path / "progress_regular.json"
    p = Progress(path)
    p.apply({"op": "tasks", "ids": ["a", "b"], "done": True})
    p.apply({"op": "tasks", "ids": ["a"], "done": False})
    p.apply({"op": "hideout", "station": "medstation", "level": 2})
    p.apply({"op": "owned", "item": "ledx", "count": 3})
    p.apply({"op": "profile", "player_level": 200, "faction": "BEAR", "intel_center": 3})
    snap = Progress(path).snapshot()
    assert snap["tasks"] == ["b"]
    assert snap["hideout"] == {"medstation": 2} and snap["owned"] == {"ledx": 3}
    assert snap["player_level"] == 79 and snap["faction"] == "BEAR" and snap["intel_center"] == 3

    p.apply({"op": "owned", "item": "ledx", "count": 0})
    p.apply({"op": "hideout", "station": "medstation", "level": 0})
    assert p.snapshot()["owned"] == {} and p.snapshot()["hideout"] == {}


def test_progress_rejects_bad_input(tmp_path):
    p = Progress(tmp_path / "p.json")
    for op in (
        {"op": "tasks", "ids": ["../evil"], "done": True},
        {"op": "tasks", "ids": "abc", "done": True},
        {"op": "owned", "item": None, "count": 1},
        {"op": "profile", "faction": "SCAV"},
        {"op": "profile", "player_level": "lots"},
        {"op": "reset", "what": "everything"},
        {"op": "launch_rockets"},
        "not a dict",
    ):
        with pytest.raises(ProgressError):
            p.apply(op)


def test_progress_import_and_reset(tmp_path):
    p = Progress(tmp_path / "p.json")
    p.apply({"op": "import", "data": {
        "player_level": "42", "faction": "BEAR", "tasks": ["t1", "t1", "bad id!"],
        "hideout": {"stash": 4, "bad id!": 2, "lavatory": -1}, "owned": {"gpu": 2.0}, "junk": True,
    }})
    snap = p.snapshot()
    assert snap["player_level"] == 42 and snap["tasks"] == ["t1"]
    assert snap["hideout"] == {"stash": 4} and snap["owned"] == {"gpu": 2}
    assert "junk" not in snap
    p.apply({"op": "reset", "what": "tasks"})
    assert p.snapshot()["tasks"] == [] and p.snapshot()["hideout"] == {"stash": 4}
    p.apply({"op": "reset", "what": "all"})
    assert p.snapshot() == progress.DEFAULT


def test_corrupt_progress_file_starts_fresh(tmp_path):
    path = tmp_path / "p.json"
    path.write_text("{not json")
    assert Progress(path).snapshot() == progress.DEFAULT


# -- updater --------------------------------------------------------------------

def make_install(root: Path):
    (root / "tarkov_display").mkdir(parents=True)
    (root / "tarkov_display" / "__init__.py").write_text('__version__ = "1.0.0"\n')
    (root / "tarkov_display" / "removed_module.py").write_text("old\n")
    (root / "README.md").write_text("old readme\n")
    (root / "my_notes.txt").write_text("mine\n")


def make_zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()


NEW_RELEASE = {
    "EFT-amd-control-branch/tarkov_display/__init__.py": '__version__ = "1.1.0"\n',
    "EFT-amd-control-branch/tarkov_display/web/index.html": "<html></html>\n",
    "EFT-amd-control-branch/README.md": "new readme\n",
}


def test_parse_version():
    assert updater.parse_version("1.10.0") > updater.parse_version("1.9.9")
    assert updater.parse_version("1.0") < updater.parse_version("1.0.1")
    assert updater.parse_version("garbage") == (0,)


def test_update_replaces_code_and_keeps_user_files(tmp_path):
    make_install(tmp_path)
    messages = []
    updater.Updater(root=tmp_path).apply(messages.append, data=make_zip(NEW_RELEASE))
    assert '1.1.0' in (tmp_path / "tarkov_display" / "__init__.py").read_text()
    assert (tmp_path / "tarkov_display" / "web" / "index.html").exists()
    assert not (tmp_path / "tarkov_display" / "removed_module.py").exists()
    assert (tmp_path / "README.md").read_text() == "new readme\n"
    assert (tmp_path / "my_notes.txt").read_text() == "mine\n"
    assert not (tmp_path / "tarkov_display.old").exists()
    assert messages[-1] == "Installed."


def test_failed_update_rolls_back(tmp_path, monkeypatch):
    make_install(tmp_path)

    def broken_copy(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(updater.shutil, "copy2", broken_copy)
    monkeypatch.setattr(updater.shutil, "copytree", broken_copy)
    with pytest.raises(OSError):
        updater.Updater(root=tmp_path).apply(data=make_zip(NEW_RELEASE))
    assert '1.0.0' in (tmp_path / "tarkov_display" / "__init__.py").read_text()
    assert (tmp_path / "tarkov_display" / "removed_module.py").exists()


def test_update_rejects_bad_downloads(tmp_path):
    make_install(tmp_path)
    u = updater.Updater(root=tmp_path)
    with pytest.raises(RuntimeError, match="Unsafe path"):
        u.apply(data=make_zip({"x/../../evil.txt": "boom"}))
    with pytest.raises(RuntimeError, match="doesn't look like"):
        u.apply(data=make_zip({"something-else/readme.txt": "hi"}))
    assert '1.0.0' in (tmp_path / "tarkov_display" / "__init__.py").read_text()


def test_check_reports_new_version(tmp_path, monkeypatch):
    make_install(tmp_path)

    import base64

    def fake_download(url, timeout=60):
        if "api.github.com" in url and "/contents/" in url:
            return json.dumps({"content": base64.b64encode(b'__version__ = "9.0.0"\n').decode()}).encode()
        if url.endswith("__init__.py"):
            return b'__version__ = "8.0.0"\n'  # raw CDN copy can lag behind
        return json.dumps([{"commit": {"message": "Add things\n\nDetails", "author": {"date": "2026-10-08T00:00:00Z"}}}]).encode()

    monkeypatch.setattr(updater, "_download", fake_download)
    result = updater.Updater(root=tmp_path).check()
    assert result["latest"] == "9.0.0" and result["available"] is True and result["error"] is None
    assert result["notes"][0]["title"] == "Add things"
    assert result["can_update"] is True


def test_check_falls_back_to_raw_file(tmp_path, monkeypatch):
    make_install(tmp_path)

    def fake_download(url, timeout=60):
        if "api.github.com" in url:
            raise OSError("API rate limit exceeded")
        return b'__version__ = "1.2.0"\n'

    monkeypatch.setattr(updater, "_download", fake_download)
    result = updater.Updater(root=tmp_path).check()
    assert result["latest"] == "1.2.0" and result["error"] is None


def test_check_offline(tmp_path, monkeypatch):
    make_install(tmp_path)

    def offline(url, timeout=60):
        raise OSError("no internet")

    monkeypatch.setattr(updater, "_download", offline)
    result = updater.Updater(root=tmp_path).check()
    assert result["available"] is False and "no internet" in result["error"]
