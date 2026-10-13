"""Your own map markers: validation, saving, and the API."""

import json

import pytest

from tarkov_display.markers import MAX_NOTE, MAX_PER_IMAGE, MarkerError, Markers


def test_add_update_delete_and_save(tmp_path):
    path = tmp_path / "markers.json"
    m = Markers(path)
    snap = m.apply({"op": "add", "image": "customs-2d", "x": 0.25, "y": 0.75, "note": "  Dorms key  ", "color": "red"})
    (mk,) = snap["customs-2d"]
    assert (mk["x"], mk["y"], mk["note"], mk["color"]) == (0.25, 0.75, "Dorms key", "red")
    m.apply({"op": "update", "image": "customs-2d", "id": mk["id"], "x": 2, "y": -1, "note": "moved"})
    again = Markers(path).snapshot()["customs-2d"][0]
    assert (again["x"], again["y"], again["note"], again["color"]) == (1.0, 0.0, "moved", "red")
    assert m.apply({"op": "delete", "image": "customs-2d", "id": mk["id"]}) == {}
    assert json.loads(path.read_text()) == {}


def test_clear_only_touches_one_image(tmp_path):
    m = Markers(tmp_path / "m.json")
    for image in ("customs-2d", "woods-2d"):
        m.apply({"op": "add", "image": image, "x": 0.1, "y": 0.1})
    assert list(m.apply({"op": "clear", "image": "customs-2d"})) == ["woods-2d"]


@pytest.mark.parametrize("op", [
    None, [], {"op": "add"}, {"op": "add", "image": "../x", "x": 0, "y": 0},
    {"op": "add", "image": "a", "x": "0", "y": 0}, {"op": "add", "image": "a", "x": float("nan"), "y": 0},
    {"op": "add", "image": "a", "x": True, "y": 0}, {"op": "add", "image": "a", "x": 0, "y": 0, "note": 5},
    {"op": "add", "image": "a", "x": 0, "y": 0, "color": "pink"},
    {"op": "update", "image": "a", "id": "nope"}, {"op": "delete", "image": "a", "id": None}, {"op": "boom", "image": "a"},
])
def test_bad_changes_are_refused(tmp_path, op):
    m = Markers(tmp_path / "m.json")
    with pytest.raises(MarkerError):
        m.apply(op)
    assert m.snapshot() == {}


def test_limits(tmp_path):
    m = Markers(None)
    snap = m.apply({"op": "add", "image": "a", "x": 0, "y": 0, "note": "x" * (MAX_NOTE + 50)})
    assert len(snap["a"][0]["note"]) == MAX_NOTE
    for _ in range(MAX_PER_IMAGE - 1):
        m.apply({"op": "add", "image": "a", "x": 0, "y": 0})
    with pytest.raises(MarkerError):
        m.apply({"op": "add", "image": "a", "x": 0, "y": 0})


def test_damaged_or_hand_edited_file(tmp_path):
    path = tmp_path / "markers.json"
    path.write_text("{not json")
    assert Markers(path).snapshot() == {}
    assert (tmp_path / "markers.unreadable.json").exists()
    path.write_text(json.dumps({
        "ok": [{"id": "abc", "x": 0.5, "y": 0.5, "note": "keep", "color": "blue"},
               {"id": "abd", "x": "bad", "y": 0}, {"id": "../", "x": 0, "y": 0}, "junk",
               {"id": "abe", "x": 0.1, "y": 9, "color": "pink", "note": 7}],
        "bad key!": [{"id": "abc", "x": 0, "y": 0}], "empty": [], "notalist": {}}))
    snap = Markers(path).snapshot()
    assert list(snap) == ["ok"]
    assert [(mk["id"], mk["color"], mk["y"]) for mk in snap["ok"]] == [("abc", "blue", 0.5)]
