"""Story chapters: the hand-kept step list, your ticks, and the export."""

import pytest

from tarkov_display import advisor, story
from tarkov_display.progress import ID, Progress, ProgressError


def test_chapter_data_is_sound():
    assert len(story.CHAPTERS) == 10 and len(story.BY_ID) == 10
    ids = [s["id"] for c in story.CHAPTERS for s in c["steps"]]
    assert len(ids) == len(set(ids)) == len(story.STEP_IDS)
    for c in story.CHAPTERS:
        assert ID.match(c["id"]) and c["kind"] in ("main", "investigation") and c["steps"]
        assert c["start"] and c["summary"] and c["reward"] and isinstance(c["choices"], list)
        for s in c["steps"]:
            assert ID.match(s["id"]) and s["text"] and isinstance(s["optional"], bool)
    assert [c["name"] for c in story.CHAPTERS if c["kind"] == "main"] == ["Tour", "Falling Skies", "The Ticket"]


def test_status_and_routes():
    ticket = story.BY_ID["the-ticket"]
    shared = {s["id"] for s in ticket["steps"] if not s["branch"] and not s["optional"]}
    # Kept the case: the Lightkeeper arc doesn't hold the chapter open.
    st = story.chapter_status(ticket, shared)
    assert st["state"] == "done" and st["next"] == []
    # Started that arc: now it counts.
    arc = next(s for s in ticket["steps"] if s["branch"] and not s["optional"])
    st = story.chapter_status(ticket, shared | {arc["id"]})
    assert st["state"] == "in progress" and st["requiredLeft"] > 0
    assert story.chapter_status(story.BY_ID["tour"], set())["state"] == "not started"


def test_story_progress():
    p = Progress(None)
    snap = p.apply({"op": "story", "ids": ["tour-01", "tour-02"], "done": True})
    assert snap["story"]["steps"] == ["tour-01", "tour-02"]
    assert p.apply({"op": "story", "ids": ["tour-01"], "done": False})["story"]["steps"] == ["tour-02"]
    assert p.apply({"op": "story_note", "chapter": "falling-skies", "text": "  kept the case  "})["story"]["notes"] == {
        "falling-skies": "kept the case"}
    assert p.apply({"op": "story_note", "chapter": "falling-skies", "text": ""})["story"]["notes"] == {}
    for bad in ({"op": "story", "ids": ["../x"]}, {"op": "story_note", "chapter": 5, "text": "x"}):
        with pytest.raises(ProgressError):
            p.apply(bad)
    p.apply({"op": "import", "data": {"story": {"steps": ["ok-1", "bad id!", 3], "notes": {"x": "y" * 900, "z": 1}}}})
    assert p.snapshot()["story"] == {"steps": ["ok-1"], "notes": {"x": "y" * 500}}
    assert p.apply({"op": "reset", "what": "story"})["story"] == {"steps": [], "notes": {}}


def test_story_in_export():
    fs = story.BY_ID["falling-skies"]
    progress = {"player_level": 30, "story": {"steps": [s["id"] for s in story.BY_ID["tour"]["steps"]] + ["fs-01"],
                                              "notes": {"falling-skies": "Stuck finding the G-Wagon"}}}
    text = advisor.build(progress=progress, tasks=None, stations=None, maps=None)
    assert "## Story chapters" in text and "**Tour** (main story): done, 17/17 steps" in text
    assert "**Falling Skies** (main story): in progress, 1/21 steps" in text
    assert "My notes: Stuck finding the G-Wagon" in text
    assert f"Next: {fs['steps'][1]['text']} [trader/hideout]" in text
    assert "Starts: " + story.BY_ID["batya"]["start"] in text


def test_story_api(webapp):
    from tests.test_server import body, call

    data = body(call(webapp.server, "/api/story"))
    assert [c["id"] for c in data["chapters"]] == [c["id"] for c in story.CHAPTERS] and data["sourceUrl"]
    snap = body(call(webapp.server, "/api/progress", "POST", {"op": "story", "ids": ["tour-01"], "done": True}))
    assert snap["story"]["steps"] == ["tour-01"]
