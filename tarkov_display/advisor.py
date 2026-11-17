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

from . import gamelogs

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
EXPORT_NAME = re.compile(r"^raidready-\d{4}-\d{2}-\d{2}_\d{4}\.md$")

PROMPT = """\
> **Claude:** this is my current state in Escape from Tarkov, exported from RaidReady (my companion app).
> Before you answer, search current Reddit (r/EscapefromTarkov, r/Tarkov) and the Tarkov wiki for advice
> on this patch, then tell me, briefly:
> 1. The best map for my next 1-3 raids and why: stack as many of my open quests as you can, using the
>    keys I have, my level and my budget.
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


def quest_states(tasks: List[dict], progress: dict) -> Dict[str, str]:
    """"done" | "available" | "locked" | "other" for every quest, like the
    Quests page works it out."""
    by_id = {t["id"]: t for t in tasks if isinstance(t, dict) and t.get("id")}
    done, level, faction = set(progress.get("tasks") or []), progress.get("player_level") or 1, progress.get("faction")
    memo: Dict[str, str] = {}

    def state(task: dict, depth: int = 0) -> str:
        if task["id"] in memo:
            return memo[task["id"]]
        s = "available"
        if task["id"] in done:
            s = "done"
        elif not for_faction(task, faction):
            s = "other"
        elif (task.get("minPlayerLevel") or 0) > level:
            s = "locked"
        else:
            for r in _objs(task.get("taskRequirements")):
                req = by_id.get((r.get("task") or {}).get("id"))
                if not req:
                    continue
                if "complete" in _list(r.get("status")):
                    if req["id"] not in done:
                        s = "locked"
                        break
                elif depth < 50 and state(req, depth + 1) == "locked":
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


def open_quests(tasks: List[dict], progress: dict, maps: List[dict]) -> dict:
    """Available quests grouped by map, keys they need, and quests that
    unlock within a few levels."""
    states = quest_states(tasks, progress)
    map_names = {m.get("id"): m.get("name") for m in _objs(maps)}
    pinned = set(progress.get("pinned") or [])
    owned = progress.get("owned") or {}
    groups: Dict[str, List[dict]] = {}
    keys: Dict[str, dict] = {}
    soon = []
    level = progress.get("player_level") or 1
    for task in _objs(tasks):
        s = states.get(task.get("id"))
        if s == "locked" and (task.get("minPlayerLevel") or 0) <= level + 3:
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
        map_ids = list(dict.fromkeys(map_ids))
        if not left:
            where = ["Ready to turn in"]
        elif not raid_objs:
            where = ["No raid needed (hand-ins, trader or hideout)"]
        elif not map_ids:
            where = ["Any map"]
        else:
            where = [map_names.get(i) or i for i in map_ids]
        entry = {"task": task, "left": left, "pinned": task.get("id") in pinned}
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
        "done": sum(1 for s in states.values() if s == "done"),
    }


# -- the export ----------------------------------------------------------------------------

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
          app_version: str = "", now: Optional[datetime] = None) -> str:
    """The export as Markdown."""
    now = now or datetime.now()
    tasks, stations, maps = tasks or [], stations or [], maps or []
    names = dict(item_names or {})
    history = history or {}
    adv = progress.get("advisor") or {}
    q = open_quests(tasks, progress, maps)
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
    if adv.get("goal"):
        out.append(f"- Goal: {adv['goal']}")
    if adv.get("notes"):
        out += ["- Notes: " + adv["notes"].replace("\n", " ")]

    out += ["", "## Open quests by map", "",
            "_Unfinished objectives only. A quest with objectives on several maps is listed under each. "
            "📌 = in my raid plan._", ""]
    if not tasks:
        out.append("_Quest data hadn't downloaded from tarkov.dev yet._")
    for where, entries in q["groups"].items():
        out.append(f"### {where} ({len(entries)})")
        for e in sorted(entries, key=lambda e: (not e["pinned"], e["task"].get("name") or "")):
            t = e["task"]
            tags = [(t.get("trader") or {}).get("name")]
            if t.get("kappaRequired"):
                tags.append("Kappa")
            if t.get("lightkeeperRequired"):
                tags.append("Lightkeeper")
            pin = "📌 " if e["pinned"] else ""
            out.append(f"- {pin}**{t.get('name')}** ({', '.join(x for x in tags if x)})")
            for o in e["left"][:8]:
                out.append(f"  - {objective_text(o)}")
            if len(e["left"]) > 8:
                out.append(f"  - …and {len(e['left']) - 8} more")
        out.append("")

    out += ["## Keys my open quests use", ""]
    if q["keys"]:
        for k in q["keys"]:
            mark = "✅ have" if k["have"] else "❌ don't have"
            maps_ = f" ({', '.join(k['maps'])})" if k["maps"] else ""
            out.append(f"- {mark}: **{k['name']}**{maps_}, for {_join(k['quests'][:4], 'and')}")
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
                "| When | Map | Mode | Queue | Length | Ping | Server |", "|---|---|---|---|---|---|---|"]
        for r in raids:
            out.append("| {} | {} | {} | {} | {} | {} | {} |".format(
                r["time"][5:16], _map_name(r.get("map"), maps) + ("" if r.get("online", True) else " (offline)"),
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
                       + (f" for {_rub(s['roubles'])}" if s.get("roubles") else ""))

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

