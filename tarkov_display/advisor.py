"""The "Ask Claude" export: everything RaidReady knows about where you are in
the game, written as one Markdown file you can drop into a Claude chat.

Claude then looks up current advice (Reddit, the wiki) and suggests what to
do next: which map, which quests to stack, what to bring. No API key or
credits involved; the file is plain text and stays on your PC until you
share it.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from . import gamelogs, playerprofile, story

KIT_NAMES = {
    "budget": "Budget (cheap gear, scav-level kits, don't mind losing it)",
    "mid": "Mid (class 3-4 armor, decent ammo)",
    "geared": "Geared (class 4-5 armor, good ammo, can afford losses)",
    "meta": "Meta (best gear and ammo, money isn't a problem)",
}
MODE_NAMES = {"regular": "PvP", "pve": "PvE", "seasonal": "Seasonal"}
# Objectives done out in a raid (the rest happen at traders, in the hideout or over time).
IN_RAID = {"shoot", "extract", "findItem", "findQuestItem", "mark", "plantItem", "plantQuestItem", "visit",
           "useItem", "experience"}
HAND_IN = {"giveItem", "giveQuestItem"}
KEEP_EXPORTS = 20
SKIP_MAP_WORDS = ("Tutorial", "Infected")
PER_MAP = 12  # quests listed per map in the export (accepted and pinned first)
EXPORT_NAME = re.compile(r"^raidready-\d{4}-\d{2}-\d{2}_\d{4}\.md$")

PROMPT = """\
> **Claude:** this is my current state in Escape from Tarkov, exported from RaidReady (my companion app).
> Before you answer, search current Reddit (r/EscapefromTarkov, r/Tarkov) and the Tarkov wiki for advice
> on this patch, then tell me, briefly:
> 1. The best map for my next 1-3 raids and why: stack as many of my open quests and story steps as
>    you can, using the keys I have, my level and my budget.
> 2. The order to do the objectives on that map, with any spawn/extract tips that matter.
> 3. What to bring: gear that fits my budget, and which of my keys to take.
> 4. Quests to turn in or pick up first, and items worth keeping vs selling.
> 5. One hideout upgrade to work towards.
> If something important is missing (like what's in my stash), ask me. I may attach stash screenshots."""


def _list(x) -> list:
    return x if isinstance(x, list) else []


def _objs(x) -> List[dict]:
    return [v for v in _list(x) if isinstance(v, dict)]


def _name(ref) -> str:
    return (ref or {}).get("name") or (ref or {}).get("shortName") or "?" if isinstance(ref, dict) else "?"


def _join(words: Iterable[str], joiner: str = "or") -> str:
    words = [w for w in words if w]
    if len(words) <= 1:
        return words[0] if words else ""
    return f"{', '.join(words[:-1])} {joiner} {words[-1]}"


def _rub(n) -> str:
    return f"{int(n):,} ₽" if isinstance(n, (int, float)) else "?"


# -- quests --------------------------------------------------------------------------------

def for_faction(task: dict, faction: str) -> bool:
    return task.get("factionName") in (None, "", "Any", faction)


# Traders you have to unlock through quests: until you say otherwise, assume
# they're not unlocked yet (the others start at loyalty level 1).
LOCKED_TRADERS = {"lightkeeper"}
CMP = {">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b,
       "<": lambda a, b: a < b, "=": lambda a, b: a == b, "==": lambda a, b: a == b}


def _trader_key(trader: Optional[dict]) -> str:
    trader = trader or {}
    return (trader.get("normalizedName") or trader.get("name") or "").lower().replace(" ", "-")


def trader_level(trader: Optional[dict], progress: dict) -> int:
    entry = (progress.get("traders") or {}).get((trader or {}).get("id") or "")
    if entry and "level" in entry:
        return entry["level"]
    return 0 if _trader_key(trader) in LOCKED_TRADERS else 1


def ll_player_level(trader_id: Optional[str], ll, traders: Optional[List[dict]]) -> int:
    """The player level a trader's loyalty level needs (0 = unknown)."""
    for t in _objs(traders):
        if t.get("id") == trader_id:
            for lvl in _objs(t.get("levels")):
                if lvl.get("level") == ll and isinstance(lvl.get("requiredPlayerLevel"), (int, float)):
                    return int(lvl["requiredPlayerLevel"])
    return 0


def trader_blocks(task: dict, progress: dict, traders: Optional[List[dict]] = None) -> List[str]:
    """Why your trader standing keeps a quest locked ([] = it doesn't). With
    your trader levels entered, those count. Without them, only what is sure
    from your player level: a loyalty level needs a player level (Prapor LL2
    needs level 15, say), so a quest asking for it is out of reach below
    that. ``traders``: tarkov.dev's trader list, for those player levels."""
    entered = bool(progress.get("traders"))
    level = progress.get("player_level") or 1
    out = []
    giver = task.get("trader")
    if entered and giver and trader_level(giver, progress) < 1:
        out.append(f"{giver.get('name')} not unlocked")
    for r in _objs(task.get("traderRequirements")):
        trader, kind, value = r.get("trader"), r.get("requirementType") or "level", r.get("value")
        test = CMP.get(r.get("compareMethod") or ">=", CMP[">="])
        if not isinstance(value, (int, float)) or not trader:
            continue
        if kind == "level":
            if entered:
                if not test(trader_level(trader, progress), value):
                    out.append(f"{trader.get('name')} LL{value}")
            elif (r.get("compareMethod") or ">=") == ">=":
                need = ll_player_level(trader.get("id"), value, traders)
                if need > level:
                    out.append(f"{trader.get('name')} LL{value} (level {need}+)")
        elif kind == "reputation" and entered:
            rep = ((progress.get("traders") or {}).get(trader.get("id") or "") or {}).get("rep")
            if rep is not None and not test(rep, value):
                out.append(f"{trader.get('name')} rep {value}")
    return out


def quest_blocks(task: dict, progress: dict, traders: Optional[List[dict]] = None) -> List[str]:
    """What, besides your level and earlier quests, keeps a quest from being
    taken ([] = nothing): failed in game (and it can't be restarted), the
    other side of a choice you already made (finishing one quest fails
    another: its fail conditions), or trader standing. Like the Quests page."""
    done, failed = set(progress.get("tasks") or []), set(progress.get("failed") or [])
    out = []
    if task.get("id") in failed and not task.get("restartable"):
        out.append("Failed in game")
    for f in _objs(task.get("failConditions")):
        other = (f.get("task") or {}) if isinstance(f.get("task"), dict) else {}
        if f.get("type") != "taskStatus" or not other.get("id") or other.get("id") == task.get("id"):
            continue
        status = _list(f.get("status"))
        if "complete" in status and other["id"] in done:
            out.append(f"Gone: you finished {other.get('name') or 'another quest'}")
        elif "failed" in status and other["id"] in failed:
            out.append(f"Gone: you failed {other.get('name') or 'another quest'}")
    return out + trader_blocks(task, progress, traders)


def needs_finished(requirement: dict) -> bool:
    """A requirement on an earlier quest being finished: the quests marked
    done along with a later one. Not when failing it would do too."""
    status = _list((requirement or {}).get("status"))
    return "complete" in status and "failed" not in status


# Lightkeeper access after patch 1.1.5 (Sept 2026), per community guides.
LK_MAIN_TRADERS = ("prapor", "therapist", "skier", "peacekeeper", "mechanic", "ragman", "jaeger")
LK_FENCE_REP = 2.0


def lightkeeper_checklist(tasks: Optional[List[dict]], traders: Optional[List[dict]], progress: dict) -> List[dict]:
    """What's still between you and Lightkeeper: [{label, ok (True/False/None = unknown), detail}]."""
    out = []
    by_key = {_trader_key(t): t for t in _objs(traders)}
    entered = progress.get("traders") or {}
    for key in LK_MAIN_TRADERS:
        t = by_key.get(key) or {"name": key.title(), "id": ""}
        known = t.get("id") in entered and "level" in entered.get(t.get("id"), {})
        lvl = trader_level(t, progress)
        out.append({"label": f"{t.get('name')} loyalty level 3", "ok": (lvl >= 3) if known else None,
                    "detail": f"LL{lvl}" if known else "not set"})
    fence = by_key.get("fence") or {}
    rep = (entered.get(fence.get("id") or "") or {}).get("rep")
    out.append({"label": f"Fence reputation {LK_FENCE_REP:g} or more", "ok": None if rep is None else rep >= LK_FENCE_REP,
                "detail": "not set" if rep is None else f"{rep:g}"})
    steps = set((progress.get("story") or {}).get("steps") or [])
    out.append({"label": "Lighthouse unlocked (Tour: pay Mechanic)", "ok": "tour-13" in steps or None,
                "detail": "ticked on the Story page" if "tour-13" in steps else "tick it on the Story page"})
    done = set(progress.get("tasks") or [])
    chain = [t for t in _objs(tasks) if (t.get("name") or "").lower().startswith("to the light")]
    for t in chain:
        out.append({"label": f"Quest: {t.get('name')}", "ok": t.get("id") in done, "detail": (t.get("trader") or {}).get("name") or ""})
    if not chain:
        out.append({"label": "Mechanic's \"To the Light\" quest chain", "ok": None,
                    "detail": "not in tarkov.dev's quest list; check in game"})
    out.append({"label": "Encoded DSP radio transmitter to get past Zryachiy", "ok": None,
                "detail": "wear it and don't harm Zryachiy, his followers or Lightkeeper-friendly PMCs"})
    return out


def quest_states(tasks: List[dict], progress: dict, traders: Optional[List[dict]] = None) -> Dict[str, str]:
    """"done" | "available" | "locked" | "other" for every quest, like the
    Quests page works it out."""
    by_id = {t["id"]: t for t in tasks if isinstance(t, dict) and t.get("id")}
    done, level, faction = set(progress.get("tasks") or []), progress.get("player_level") or 1, progress.get("faction")
    accepted, failed = set(progress.get("accepted") or []), set(progress.get("failed") or [])
    memo: Dict[str, str] = {}

    def met(status: list, rid: str) -> bool:
        # tarkov.dev lists the states that count: "complete", "failed" (some
        # quests open when you fail another) and "active" (taken).
        return (("complete" in status and rid in done) or ("failed" in status and rid in failed)
                or ("active" in status and (rid in accepted or rid in done)))

    def state(task: dict, depth: int = 0) -> str:
        if task["id"] in memo:
            return memo[task["id"]]
        s = "available"
        if task["id"] in done:
            s = "done"
        elif not for_faction(task, faction):
            s = "other"
        elif (task.get("minPlayerLevel") or 0) > level or quest_blocks(task, progress, traders):
            s = "locked"
        else:
            for r in _objs(task.get("taskRequirements")):
                req = by_id.get((r.get("task") or {}).get("id"))
                status = _list(r.get("status"))
                if not req or met(status, req["id"]):
                    continue
                if "complete" in status or "failed" in status:  # has to be finished (or failed): it isn't yet
                    s = "locked"
                    break
                if depth < 50 and state(req, depth + 1) == "locked":  # only has to be taken: and can't be yet
                    s = "locked"
                    break
        memo[task["id"]] = s
        return s

    return {tid: state(t) for tid, t in by_id.items()}


def objective_done(o: dict, progress: dict) -> bool:
    target = max(1, o.get("count") or 1) if isinstance(o.get("count"), int) else 1
    return (progress.get("objectives") or {}).get(o.get("id"), 0) >= target


def objective_map_ids(o: dict) -> List[str]:
    ids = [m.get("id") for m in _objs(o.get("maps")) if m.get("id")]
    ids += [(z.get("map") or {}).get("id") for z in _objs(o.get("zones")) if (z.get("map") or {}).get("id")]
    ids += [(p.get("map") or {}).get("id") for p in _objs(o.get("possibleLocations")) if (p.get("map") or {}).get("id")]
    return list(dict.fromkeys(ids))


def key_groups(o: dict) -> List[List[dict]]:
    """requiredKeys: groups of keys, any one of a group opens it."""
    return [_objs(g) for g in _list(o.get("requiredKeys")) if _objs(g)]


def objective_text(o: dict) -> str:
    text = (o.get("description") or o.get("type") or "").strip()
    extra = []
    count = o.get("count")
    items = _objs(o.get("items")) or _objs([o.get("questItem") or o.get("markerItem") or o.get("item")])
    if o.get("type") in ("giveItem", "findItem", "plantItem", "mark") and items and items[0].get("name"):
        names = [i.get("name") for i in items[:4] if i.get("name")]
        if names and not any(n.lower() in text.lower() for n in names):
            extra.append(_join(names) + (f" (+{len(items) - 4} more)" if len(items) > 4 else ""))
    if isinstance(count, int) and count > 1 and str(count) not in text:
        extra.append(f"×{count}")
    if o.get("foundInRaid"):
        extra.append("FiR")
    if o.get("zoneNames"):
        extra.append("at " + _join([str(z) for z in o["zoneNames"][:3]]))
    if o.get("optional"):
        extra.append("optional")
    return text + (f" ({', '.join(extra)})" if extra else "")


def open_quests(tasks: List[dict], progress: dict, maps: List[dict], traders: Optional[List[dict]] = None) -> dict:
    """Available quests grouped by map, keys they need, and quests that
    unlock within a few levels."""
    states = quest_states(tasks, progress, traders)
    level = progress.get("player_level") or 1
    # Event, tutorial and high-level variants of maps only clutter the list.
    skip = {m.get("id") for m in _objs(maps)
            if any(w in (m.get("name") or "") for w in SKIP_MAP_WORDS) or (m.get("minPlayerLevel") or 0) > level}
    map_names = {m.get("id"): m.get("name") for m in _objs(maps)}
    pinned = set(progress.get("pinned") or [])
    accepted, failed = set(progress.get("accepted") or []), set(progress.get("failed") or [])
    owned = progress.get("owned") or {}
    groups: Dict[str, List[dict]] = {}
    keys: Dict[str, dict] = {}
    soon = []
    for task in _objs(tasks):
        s = states.get(task.get("id"))
        # Unlocking soon: held back only by your level, a few levels away.
        if (s == "locked" and level < (task.get("minPlayerLevel") or 0) <= level + 3
                and not quest_blocks(task, progress, traders)):
            reqs_done = all("complete" not in _list(r.get("status")) or states.get((r.get("task") or {}).get("id")) == "done"
                            for r in _objs(task.get("taskRequirements")))
            if reqs_done:
                soon.append(task)
        if s != "available":
            continue
        left = [o for o in _objs(task.get("objectives")) if not objective_done(o, progress)]
        raid_objs = [o for o in left if o.get("type") in IN_RAID or objective_map_ids(o)]
        map_ids = []
        for o in raid_objs:
            map_ids += objective_map_ids(o)
        if raid_objs and not map_ids and (task.get("map") or {}).get("id"):
            map_ids = [task["map"]["id"]]
        map_ids = [i for i in dict.fromkeys(map_ids) if i not in skip] or ([] if not map_ids else ["*skipped*"])
        if map_ids == ["*skipped*"]:
            continue  # only on event/tutorial maps
        if not left:
            where = ["Ready to turn in"]
        elif not raid_objs:
            where = ["No raid needed (hand-ins, trader or hideout)"]
        elif not map_ids:
            where = ["Any map"]
        else:
            where = [map_names.get(i) or i for i in map_ids]
        entry = {"task": task, "left": left, "pinned": task.get("id") in pinned,
                 "accepted": task.get("id") in accepted, "failed": task.get("id") in failed}
        for w in where:
            groups.setdefault(w, []).append(entry)
        # Keys: the quest's own list, and keys its unfinished objectives name.
        found = []
        for nk in _objs(task.get("neededKeys")):
            for k in _objs(nk.get("keys")):
                found.append((k, (nk.get("map") or {}).get("name")))
        for o in raid_objs:
            for group in key_groups(o):
                mname = _join([map_names.get(i) or "" for i in objective_map_ids(o)], "/")
                for k in group:
                    found.append((k, mname))
        for k, mname in found:
            if not k.get("id"):
                continue
            e = keys.setdefault(k["id"], {"id": k["id"], "name": k.get("name") or k.get("shortName") or k["id"],
                                          "short": k.get("shortName"), "icon": k.get("iconLink"),
                                          "maps": [], "quests": [], "have": bool(owned.get(k["id"]))})
            if mname and mname not in e["maps"]:
                e["maps"].append(mname)
            if task.get("name") not in e["quests"]:
                e["quests"].append(task.get("name"))
    order = lambda name: (name in ("Ready to turn in", "No raid needed (hand-ins, trader or hideout)", "Any map"),
                          -len(groups[name]), name)
    return {
        "groups": {name: groups[name] for name in sorted(groups, key=order)},
        "keys": sorted(keys.values(), key=lambda k: (not k["have"], k["maps"][:1], k["name"])),
        "soon": sorted(soon, key=lambda t: (t.get("minPlayerLevel") or 0, t.get("name") or "")),
        "available": sum(1 for s in states.values() if s == "available"),
        "failed": [t for t in _objs(tasks) if t.get("id") in failed and states.get(t.get("id")) != "done"],
        "acceptedCount": len([t for t in _objs(tasks) if t.get("id") in accepted and states.get(t.get("id")) != "done"]),
        "done": sum(1 for s in states.values() if s == "done"),
    }


# -- pre-raid pack check --------------------------------------------------------------------

def raid_kit(tasks: List[dict], progress: dict, map_id: str, traders: Optional[List[dict]] = None) -> dict:
    """What to take into a raid on ``map_id`` for your raid plan (pinned
    quests; accepted ones if nothing is pinned): keys, markers, items to place
    or use, weapons. Like the Raid plan page's kit list."""
    states = quest_states(tasks, progress, traders)
    pinned = [t for t in _objs(tasks) if t.get("id") in set(progress.get("pinned") or []) and states.get(t.get("id")) != "done"]
    source = "pinned"
    if not pinned:
        pinned = [t for t in _objs(tasks) if t.get("id") in set(progress.get("accepted") or []) and states.get(t.get("id")) == "available"]
        source = "accepted"
    owned = progress.get("owned") or {}
    bring: Dict[str, dict] = {}
    quests = []

    def add(key: str, kind: str, items: List[dict], count: int, quest: str) -> None:
        e = bring.setdefault(key, {"kind": kind, "items": [i.get("name") or i.get("shortName") or "?" for i in items],
                                   "ids": [i.get("id") for i in items], "count": 0, "quests": []})
        e["count"] += count
        if quest not in e["quests"]:
            e["quests"].append(quest)

    for task in pinned:
        here = False
        for o in _objs(task.get("objectives")):
            if objective_done(o, progress):
                continue
            ids = objective_map_ids(o)
            if ids and map_id not in ids:
                continue
            if not ids and (task.get("map") or {}).get("id") not in (None, map_id):
                continue
            here = here or bool(ids) or (task.get("map") or {}).get("id") == map_id
            name, n = task.get("name") or "?", max(1, o.get("count") or 1) if isinstance(o.get("count"), int) else 1
            for group in key_groups(o):
                add("key:" + "|".join(sorted(k.get("id") or "" for k in group)), "Key", group, 1, name)
            marker = (o.get("markerItem") or {}) if isinstance(o.get("markerItem"), dict) else {}
            if o.get("type") == "mark" and marker:
                add("mark:" + (marker.get("id") or ""), "Marker", [marker], 1, name)
            if o.get("type") == "plantItem" and _objs(o.get("items")):
                items = _objs(o.get("items"))
                add("plant:" + "|".join(sorted(i.get("id") or "" for i in items)), "To place", items, n, name)
            if o.get("type") == "useItem" and _objs(o.get("useAny")):
                items = _objs(o.get("useAny"))
                add("use:" + "|".join(sorted(i.get("id") or "" for i in items)), "To use", items, n, name)
            if o.get("type") == "shoot" and _objs(o.get("usingWeapon")):
                items = _objs(o.get("usingWeapon"))
                add("weapon:" + "|".join(sorted(i.get("id") or "" for i in items)), "Weapon", items, 1, name)
        if here:
            quests.append(task.get("name"))
    for e in bring.values():
        e["have"] = any(owned.get(i) for i in e["ids"] if i)
    order = {"Key": 0, "Marker": 1, "To place": 2, "To use": 3, "Weapon": 4}
    return {"source": source, "quests": quests,
            "bring": sorted(bring.values(), key=lambda e: (order.get(e["kind"], 9), e["items"][0] if e["items"] else ""))}


def kit_lines(kit: dict, limit: int = 8) -> List[str]:
    """Short lines for a popup: "Key: Dorm room 314 marked key (missing)"."""
    out = []
    for e in kit["bring"][:limit]:
        names = _join(e["items"][:2]) + (f" (+{len(e['items']) - 2} more)" if len(e["items"]) > 2 else "")
        count = f" ×{e['count']}" if e["count"] > 1 else ""
        flag = "" if e["kind"] != "Key" else (" ✓" if e["have"] else " (not ticked as owned)")
        out.append(f"{e['kind']}: {names}{count}{flag}")
    if len(kit["bring"]) > limit:
        out.append(f"+{len(kit['bring']) - limit} more on the Raid plan page")
    return out


# -- the export ----------------------------------------------------------------------------

def _story_lines(progress: dict) -> List[str]:
    """Story chapters: where I am in each, and the next steps."""
    data = progress.get("story") or {}
    done = set(data.get("steps") or [])
    notes = data.get("notes") or {}
    out = ["## Story chapters", "",
           "_Ticked off by hand in RaidReady; the step list comes from community guides and may lag a patch._", ""]
    for ch in story.CHAPTERS:
        st = story.chapter_status(ch, done)
        kind = "main story" if ch["kind"] == "main" else "investigation"
        out.append(f"- **{ch['name']}** ({kind}): {st['state']}, {st['done']}/{st['total']} steps")
        if ch["id"] in notes:
            out.append(f"  - My notes: {notes[ch['id']]}")
        if st["state"] == "not started":
            out.append(f"  - Starts: {ch['start']}")
        for s in st["next"]:
            where = s["map"] or "trader/hideout"
            extra = [f"needs {s['need']}" if s["need"] else "", f"only if {s['branch'].lower()}" if s.get("branch") else ""]
            extra = ", ".join(e for e in extra if e)
            if st["state"] == "in progress":
                out.append(f"  - Next: {s['text']} [{where}]" + (f" ({extra})" if extra else ""))
    return out + [""]


def _hideout(stations: List[dict], progress: dict, item_names: Dict[str, str]) -> List[str]:
    built = progress.get("hideout") or {}
    owned = progress.get("owned") or {}
    lines = []
    for st in sorted(_objs(stations), key=lambda s: s.get("name") or ""):
        level = built.get(st.get("id"), 0)
        levels = sorted(_objs(st.get("levels")), key=lambda l: l.get("level") or 0)
        nxt = next((l for l in levels if (l.get("level") or 0) > level), None)
        if not nxt:
            continue
        need = []
        for req in _objs(nxt.get("itemRequirements")):
            item = req.get("item") or {}
            name = item.get("name") or item_names.get(item.get("id"), "?")
            count = req.get("count") or req.get("quantity") or 1
            have = owned.get(item.get("id"), 0)
            need.append(f"{name} ×{count}" + (f" (have {min(have, count)})" if have else ""))
        other = [f"{(r.get('station') or {}).get('name')} {r.get('level')}" for r in _objs(nxt.get("stationLevelRequirements"))]
        other += [f"{(r.get('trader') or {}).get('name')} LL{r.get('value')}" for r in _objs(nxt.get("traderRequirements"))
                  if r.get("requirementType") in (None, "level")]
        other += [f"{r.get('name')} skill {r.get('level')}" for r in _objs(nxt.get("skillRequirements"))]
        line = f"- **{st.get('name')} {level} → {nxt.get('level')}**: {', '.join(need) or 'no items'}"
        if other:
            line += f". Needs {', '.join(other)}"
        lines.append(line)
    return lines


def _map_name(name_id: Optional[str], maps: List[dict]) -> str:
    for m in _objs(maps):
        if (m.get("nameId") or "").lower() == (name_id or "").lower():
            return m.get("name") or name_id
    return name_id or "?"


def build(*, progress: dict, tasks: Optional[List[dict]], stations: Optional[List[dict]], maps: Optional[List[dict]],
          history: Optional[dict] = None, item_names: Optional[Dict[str, str]] = None, game_mode: str = "regular",
          app_version: str = "", now: Optional[datetime] = None, traders: Optional[List[dict]] = None,
          prices: Optional[Dict[str, dict]] = None, profile: Optional[dict] = None) -> str:
    """The export as Markdown."""
    now = now or datetime.now()
    tasks, stations, maps = tasks or [], stations or [], maps or []
    names = dict(item_names or {})
    history = history or {}
    adv = progress.get("advisor") or {}
    q = open_quests(tasks, progress, maps, traders)
    out: List[str] = ["# RaidReady export for Claude", "", PROMPT, ""]
    stamp = now.strftime("%Y-%m-%d %H:%M")
    version = f", game {history['gameVersion']}" if history.get("gameVersion") else ""
    out.append(f"_Exported {stamp} from RaidReady {app_version}{version}._")
    out += ["", "## Me", ""]
    out.append(f"- Mode: {MODE_NAMES.get(game_mode, game_mode)}")
    out.append(f"- Level {progress.get('player_level', 1)}, {progress.get('faction', 'USEC')}")
    out.append(f"- Quests done: {q['done']} · available now: {q['available']}")
    out.append(f"- Usual kit: {KIT_NAMES.get(adv.get('kit'), 'not set')}")
    out.append(f"- Roubles: {_rub(adv['roubles']) if adv.get('roubles') else 'not set'}")
    if progress.get("intel_center"):
        out.append(f"- Intelligence Center {progress['intel_center']}")
    if progress.get("hideout_management"):
        out.append(f"- Hideout Management skill {progress['hideout_management']}")
    if q.get("acceptedCount"):
        out.append(f"- Accepted in game (from the logs): {q['acceptedCount']} quests")
    if adv.get("goal"):
        out.append(f"- Goal: {adv['goal']}")
    if adv.get("notes"):
        out += ["- Notes: " + adv["notes"].replace("\n", " ")]

    standing = progress.get("traders") or {}
    if standing:
        names = {t.get("id"): t.get("name") for t in _objs(traders)}
        bits = []
        for tid, e in sorted(standing.items(), key=lambda x: names.get(x[0]) or x[0]):
            lvl = e.get("level")
            text = f"{names.get(tid, tid)} " + ("locked" if lvl == 0 else f"LL{lvl}" if lvl is not None else "LL?")
            if e.get("rep") is not None:
                text += f" ({e['rep']:g})"
            bits.append(text)
        out.append(f"- Traders: {', '.join(bits)}")
    else:
        out.append("- Trader levels: not entered (quest availability only checks the player level each loyalty level needs)")
    if profile and profile.get("profile"):
        out += [""] + playerprofile.export_lines(profile)[:-1]
    if "lightkeeper" in (adv.get("goal") or "").lower() or standing:
        checklist = lightkeeper_checklist(tasks, traders, progress)
        out += ["", "## Road to Lightkeeper", "", "_Requirements after the 1.1.5 Lighthouse rework, per community guides._", ""]
        for row in checklist:
            mark = "✅" if row["ok"] is True else "❌" if row["ok"] is False else "❔"
            out.append(f"- {mark} {row['label']}" + (f" ({row['detail']})" if row["detail"] else ""))
    if q.get("failed"):
        out += ["", "## Failed quests (restart at the trader)", ""]
        out += [f"- {t.get('name')} ({(t.get('trader') or {}).get('name')})" for t in q["failed"]]
    out += ["", "## Open quests by map", "",
            "_Unfinished objectives only. Quests I've accepted in game come first, then pinned ones (📌). "
            f"A quest on several maps is written out once and named again under the others; at most {PER_MAP} per map._", ""]
    if not tasks:
        out.append("_Quest data hadn't downloaded from tarkov.dev yet._")
    shown: Dict[str, str] = {}  # quest id -> map it was written out under
    for where, entries in q["groups"].items():
        out.append(f"### {where} ({len(entries)})")
        entries = sorted(entries, key=lambda e: (not e["failed"], not e["accepted"], not e["pinned"], e["task"].get("name") or ""))
        for e in entries[:PER_MAP]:
            t = e["task"]
            tags = [(t.get("trader") or {}).get("name")]
            if t.get("kappaRequired"):
                tags.append("Kappa")
            if t.get("lightkeeperRequired"):
                tags.append("Lightkeeper")
            if e["failed"]:
                tags.append("FAILED in game, restart it")
            elif e["accepted"]:
                tags.append("accepted in game")
            pin = "📌 " if e["pinned"] else ""
            if t.get("id") in shown:
                out.append(f"- {pin}**{t.get('name')}** (see {shown[t['id']]})")
                continue
            shown[t["id"]] = where
            out.append(f"- {pin}**{t.get('name')}** ({', '.join(x for x in tags if x)})")
            limit = 12 if e["pinned"] or e["accepted"] else 6
            for o in e["left"][:limit]:
                out.append(f"  - {objective_text(o)}")
            if len(e["left"]) > limit:
                out.append(f"  - …and {len(e['left']) - limit} more")
        if len(entries) > PER_MAP:
            rest = [e["task"].get("name") for e in entries[PER_MAP:]]
            out.append(f"- Also here: {', '.join(rest)}")
        out.append("")

    out += _story_lines(progress)
    out += ["## Keys my open quests use", ""]
    if q["keys"]:
        for k in q["keys"]:
            mark = "✅ have" if k["have"] else "❌ don't have"
            maps_ = f" ({', '.join(k['maps'])})" if k["maps"] else ""
            price = (prices or {}).get(k["id"]) or {}
            cost = ""
            if not k["have"]:
                if price.get("banned"):
                    cost = " — not on the flea"
                elif price.get("flea"):
                    cost = f" — flea about {_rub(price['flea'])}"
            out.append(f"- {mark}: **{k['name']}**{maps_}, for {_join(k['quests'][:4], 'and')}{cost}")
    else:
        out.append("- None of my available quests need keys.")
    other_keys = [names.get(i, i) for i, n in (progress.get("owned") or {}).items()
                  if n and i not in {k["id"] for k in q["keys"]} and "key" in names.get(i, "").lower()]
    if other_keys:
        out.append(f"- Other keys I have: {', '.join(sorted(other_keys))}")

    owned = [(names.get(i), n) for i, n in (progress.get("owned") or {}).items() if n and names.get(i)
             and "key" not in names.get(i, "").lower()]
    if owned:
        out += ["", "## Items I've set aside for quests and hideout", ""]
        out += [f"- {name} ×{n}" for name, n in sorted(owned)]

    hideout = _hideout(stations, progress, names)
    if hideout:
        out += ["", "## Hideout: next level of each station", ""] + hideout

    if q["soon"]:
        out += ["", "## Quests unlocking in the next few levels", ""]
        out += [f"- Level {t.get('minPlayerLevel')}: {t.get('name')} ({(t.get('trader') or {}).get('name')})"
                for t in q["soon"][:15]]

    raids = history.get("raids") or []
    if raids:
        out += ["", "## My recent raids (from the game's log files)", "",
                "_The logs don't say whether I survived or what I looted._", "",
                "| When | Map | As | Mode | Queue | Length | Ping | Server |", "|---|---|---|---|---|---|---|---|"]
        for r in raids:
            out.append("| {} | {} | {} | {} | {} | {} | {} | {} |".format(
                r["time"][5:16], _map_name(r.get("map"), maps) + ("" if r.get("online", True) else " (offline)"),
                r.get("side") or "?",
                MODE_NAMES.get(r.get("mode"), r.get("mode") or "?"),
                f"{r['queue']} s" if r.get("queue") is not None else "?",
                f"{r['minutes']} min" if r.get("minutes") is not None else "?",
                f"{r['ping']} ms" + (f", {r['loss']} lost" if r.get("loss") else "") if r.get("ping") is not None else "?",
                r.get("server") or "?"))
        counts: Dict[str, int] = {}
        for r in raids:
            counts[_map_name(r.get("map"), maps)] = counts.get(_map_name(r.get("map"), maps), 0) + 1
        out += ["", "Maps played lately: " + ", ".join(f"{m} ×{n}" for m, n in sorted(counts.items(), key=lambda x: -x[1]))]

    sales = history.get("sales") or []
    if sales:
        total = sum(s.get("roubles") or 0 for s in sales)
        out += ["", "## Recent flea market sales", "", f"{len(sales)} sales, {_rub(total)} in total. Latest:", ""]
        for s in sales[:10]:
            name = names.get(s.get("itemId"), s.get("itemId") or "?")
            out.append(f"- {s['time'][5:16]}: {name}" + (f" ×{s['count']}" if (s.get("count") or 1) > 1 else "")
                       + (f" for {_rub(s['roubles'])}" if s.get("roubles") else "")
                       + (f" ⚠️ still needed: {'; '.join(s['needed'])}" if s.get("needed") else ""))

    if maps:
        out += ["", "## Maps (tarkov.dev)", ""]
        for m in sorted(_objs(maps), key=lambda m: m.get("name") or ""):
            bosses = [f"{_name(b.get('boss'))} {round((b.get('spawnChance') or 0) * 100)}%"
                      for b in _objs(m.get("bosses")) if (b.get("spawnChance") or 0) > 0]
            bits = [f"{m['players']} players" if m.get("players") else "",
                    f"{m['raidDuration']} min" if m.get("raidDuration") else "",
                    f"bosses: {', '.join(dict.fromkeys(bosses))}" if bosses else ""]
            if m.get("minPlayerLevel"):
                bits.append(f"level {m['minPlayerLevel']}+")
            out.append(f"- **{m.get('name')}**: " + ", ".join(b for b in bits if b))

    out += ["", "---", "_End of export. Claude: please answer using the steps at the top._", ""]
    return "\n".join(out)


# -- files ---------------------------------------------------------------------------------

def export_folder() -> Path:
    """Documents\\RaidReady exports (Documents may be moved, e.g. to OneDrive)."""
    docs = None
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:  # CSIDL_PERSONAL
                docs = Path(buf.value)
        except Exception:
            docs = None
    if not docs or not docs.is_dir():
        docs = Path.home() / "Documents"
        if not docs.is_dir():
            docs = Path.home()
    return docs / "RaidReady exports"


def save(text: str, folder: Optional[Path] = None, now: Optional[datetime] = None) -> Path:
    folder = folder or export_folder()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"raidready-{(now or datetime.now()).strftime('%Y-%m-%d_%H%M')}.md"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    # Keep the newest few; old exports are out of date anyway.
    old = sorted((p for p in folder.iterdir() if p.is_file() and EXPORT_NAME.match(p.name)),
                 key=lambda p: p.name, reverse=True)[KEEP_EXPORTS:]
    for p in old:
        try:
            p.unlink()
        except OSError:
            pass
    return path


def history_for(logs_folder: Optional[Path]) -> dict:
    if not logs_folder:
        return {}
    try:
        return gamelogs.recent_history(logs_folder)
    except Exception:
        return {}

