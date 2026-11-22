"""Public profile from tarkov.dev: parsing BSG's format, caching, applying it."""

import json

import pytest

from tarkov_display import advisor, playerprofile as pp

LEVELS = [{"level": 1, "exp": 0}, {"level": 2, "exp": 1000}, {"level": 35, "exp": 2_000_000}, {"level": 36, "exp": 2_200_000}]


def raw_profile(**over):
    data = {
        "aid": 14545243,
        "info": {"nickname": "Garrett", "side": "Usec", "experience": 2_100_000, "prestigeLevel": 0},
        "skills": {"Common": [{"Id": "Strength", "Progress": 512.3}, {"Id": "HideoutManagement", "Progress": 830},
                              {"Id": "Endurance", "Progress": 1520}], "Mastering": []},
        "pmcStats": {"eft": {"overAllCounters": {"Items": [
            {"Key": ["Sessions", "Pmc"], "Value": 410}, {"Key": ["ExitStatus", "Survived", "Pmc"], "Value": 160},
            {"Key": ["ExitStatus", "Killed", "Pmc"], "Value": 200}, {"Key": ["ExitStatus", "Runner", "Pmc"], "Value": 30},
            {"Key": ["Kills"], "Value": 950}, {"Key": ["KilledPmc"], "Value": 140}]}}},
        "scavStats": {"Eft": {"OverAllCounters": {"Items": [
            {"Key": ["Sessions", "Scav"], "Value": 50}, {"Key": ["ExitStatus", "Survived", "Scav"], "Value": 40}]}}},
        "equipment": {"Id": "eq", "Items": [
            {"_id": "eq", "_tpl": "root"}, {"_id": "a", "_tpl": "t-armor", "parentId": "eq", "slotId": "ArmorVest"},
            {"_id": "b", "_tpl": "t-gun", "parentId": "eq", "slotId": "FirstPrimaryWeapon"},
            {"_id": "c", "_tpl": "t-pocket", "parentId": "eq", "slotId": "Pockets"},
            {"_id": "d", "_tpl": "t-mag", "parentId": "b", "slotId": "mod_magazine"}]},
        "achievements": {"ach-1": 1794000000, "ach-2": 1794100000},
    }
    data.update(over)
    return data


def test_summarize_reads_bsg_format_in_any_case():
    p = pp.summarize(raw_profile(), LEVELS, {"t-armor": "6B13 armor", "t-gun": "AK-74N"})
    assert (p["nickname"], p["side"], p["level"]) == ("Garrett", "Usec", 35)
    assert p["pmc"] == {"raids": 410, "survived": 160, "killed": 200, "runThrough": 30, "mia": 0, "kills": 950,
                        "pmcKills": 140, "deaths": 0, "survivalRate": 0.39}
    assert p["scav"]["raids"] == 50 and p["scav"]["survivalRate"] == 0.8
    assert [(s["name"], s["level"]) for s in p["skills"]] == [("Endurance", 15), ("Hideout Management", 8), ("Strength", 5)]
    assert [g["name"] for g in p["gear"]] == ["6B13 armor", "AK-74N"]  # not pockets, not the magazine
    assert p["achievements"] == ["ach-1", "ach-2"]
    assert pp.summarize({"info": {"experience": 5}}, None)["level"] is None


def test_account_id_from_logs(tmp_path):
    session = tmp_path / "log_2026.11.17_12-52-07_1.3.0.2.48779"
    session.mkdir()
    (session / "2026.11.17 application_000.log").write_text(
        "2026-11-17 12:52:38.448|1.3.0.2.48779|Info|application|PrepareSelectedProfileLocally ProfileId:69ed29e508831aaa8005643a AccountId:14545243\n")
    assert pp.account_id(tmp_path) == "14545243"
    assert pp.account_id(None) is None


class FakeClient:
    def __init__(self, answers):
        self.answers, self.urls = answers, []

    def get_json(self, url):
        self.urls.append(url)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def query(self, q):
        return {"playerLevels": LEVELS}


def test_fetch_tries_both_sources_and_caches(tmp_path):
    client = FakeClient([RuntimeError("HTTP 403"), raw_profile()])
    store = pp.ProfileStore(tmp_path, client_for=lambda mode: client)
    result = store.fetch("14545243", "regular", {})
    assert "player.tarkov.dev/account/14545243?gameMode=regular" in client.urls[0]
    assert client.urls[1].endswith("/profile/14545243.json")
    assert result["profile"]["level"] == 35 and store.cached("regular")["accountId"] == "14545243"
    assert store.fetch("14545243", "regular") == result and len(client.urls) == 2  # fresh copy reused
    with pytest.raises(ValueError):
        pp.ProfileStore(tmp_path, client_for=lambda m: FakeClient([{"x": 1}, RuntimeError("down")])).fetch("1234", "pve", force=True)
    with pytest.raises(ValueError):
        store.fetch("not-an-id", "regular")


def test_profile_in_export_and_applied(webapp, monkeypatch, tmp_path):
    cached = {"accountId": "14545243", "fetched": 1794000000, "profile": pp.summarize(raw_profile(), LEVELS, {"t-gun": "AK-74N"})}
    text = advisor.build(progress={"player_level": 30}, tasks=None, stations=None, maps=None, profile=cached)
    assert "## My profile (public, from tarkov.dev)" in text
    assert "PMC: 410 raids, 160 survived, 200 killed, 30 run-throughs (39% survived); 950 kills, 140 PMCs" in text
    assert "Hideout Management 8" in text and "AK-74N" in text

    monkeypatch.setattr(pp, "account_id", lambda folder: "14545243")
    monkeypatch.setattr(webapp.profiles, "fetch", lambda aid, mode, names, force=False: cached)
    webapp.progress.apply({"op": "profile", "player_level": 20, "faction": "BEAR"})
    state = webapp.profile_refresh(force=True)
    snap = webapp.progress.snapshot()
    assert state["error"] is None and snap["player_level"] == 35 and snap["faction"] == "USEC" and snap["hideout_management"] == 8
    webapp.progress.apply({"op": "profile", "player_level": 40})
    webapp.profile_refresh(force=True)
    assert webapp.progress.snapshot()["player_level"] == 40  # never lowered
    monkeypatch.setattr(pp, "account_id", lambda folder: None)
    assert "account id" in webapp.profile_refresh(quiet=True)["error"]


def test_a_missing_profile_is_explained_in_words(tmp_path):
    from tarkov_display.client import ApiError

    html = "HTTP 404 Not Found: <html><head><title>404 Not Found</title></head><body><h1>404</h1></body></html>"
    client = FakeClient([ApiError("HTTP 401 Unauthorized: {}"), ApiError(html)])
    with pytest.raises(ValueError) as err:
        pp.ProfileStore(tmp_path, client_for=lambda m: client).fetch("14545243", "regular", force=True)
    text = str(err.value)
    assert "<" not in text and "browser check" in text and "tarkov.dev/players/regular/14545243" in text
    other = pp.not_found_message("1234", "pve", ["player.tarkov.dev: HTTP 500 boom", "players.tarkov.dev: <b>down</b>"])
    assert "<" not in other and "HTTP 500 boom" in other
