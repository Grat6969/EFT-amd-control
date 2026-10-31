"""Checks RaidReady against tarkov.dev's live data (needs the internet).

Downloads the files the app uses, for PvP and PvE, runs every converter, the
price list and item panels through the app's own code, and checks what comes
out. Not part of the normal test run (it isn't named test_*); run it with

    python -m tests.live_check [--save DIR] [--graphql]

--save keeps every downloaded file under DIR, laid out by URL, so the app can
be replayed on real data. --graphql also tries tarkov.dev's GraphQL API, which
is often overloaded: its failures are reported but don't fail the check.
Exits 1 if anything crashes or breaks a hard rule; warnings don't fail it.
"""

from __future__ import annotations

import argparse
import collections
import json
import random
import sys
import time
import traceback
from pathlib import Path
from typing import Optional

from tarkov_display import datasets, pricewatch, questmap, staticapi
from tarkov_display.client import TarkovClient
from tarkov_display.prices import PriceDB

# Objective types the app spells out (web/js/questinfo.js, objectiveHow).
EXPLAINED = {
    "shoot", "extract", "giveItem", "findItem", "haveItem", "sellItem", "plantItem", "mark",
    "findQuestItem", "giveQuestItem", "plantQuestItem", "useItem", "visit", "buildWeapon",
    "experience", "skill", "traderLevel", "traderStanding", "taskStatus", "playerLevel",
    "hideoutStation",
}
ITEM_LISTS = ("items", "useAny", "usingWeapon", "notWearing", "containsAll")
ITEM_GROUPS = ("requiredKeys", "wearing", "usingWeaponMods")
ITEM_REFS = ("questItem", "markerItem", "item")


DUMP: list = []  # --dump-quest-maps lines


class Report:
    def __init__(self) -> None:
        self.errors: list = []
        self.warnings: collections.Counter = collections.Counter()
        self.examples: dict = {}

    def error(self, message: str) -> None:
        print("  ERROR", message)
        self.errors.append(message)

    def warn(self, message: str, example=None) -> None:
        self.warnings[message] += 1
        if example is not None:
            self.examples.setdefault(message, example)


def record_downloads(save: Optional[Path]) -> dict:
    """Wrap every download: time it and, with --save, keep the file."""
    real = TarkovClient.get_json
    real_bytes = TarkovClient.get_bytes
    timings: dict = {}

    def get_bytes(self, url):
        raw = real_bytes(self, url)
        if save is not None:  # map drawings, as they are
            path = save / url.split("://", 1)[-1]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        return raw

    TarkovClient.get_bytes = get_bytes

    def get_json(self, url):
        start = time.time()
        doc = real(self, url)
        timings[url] = time.time() - start
        if save is not None:
            path = save / (url.split("://", 1)[-1] + ".json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
        return doc

    TarkovClient.get_json = get_json
    return timings


def named(ref) -> bool:
    return isinstance(ref, dict) and bool(ref.get("id")) and bool(ref.get("name"))


def check_items(rep: Report, where: str, refs) -> None:
    for ref in refs or []:
        if not named(ref):
            rep.warn(f"{where}: item without id or name", ref)


def check_tasks(rep: Report, mode: str, tasks: list, map_ids: set) -> collections.Counter:
    types: collections.Counter = collections.Counter()
    if len(tasks) < 100:
        rep.error(f"[{mode}] only {len(tasks)} tasks")
    task_ids = collections.Counter(t.get("id") for t in tasks)
    for tid, n in task_ids.items():
        if n > 1 or not tid:
            rep.error(f"[{mode}] task id {tid!r} appears {n} times")
    seen_objectives: dict = {}
    for t in tasks:
        label = f"[{mode}] task {t.get('name')!r}"
        if not t.get("name"):
            rep.error(f"[{mode}] task {t.get('id')} has no name")
        if not (t.get("trader") or {}).get("name"):
            rep.warn("task without a trader name", t.get("name"))
        if t.get("map") and t["map"].get("id") not in map_ids:
            rep.warn("task map not in the maps list", (t.get("name"), t["map"]))
        for req in t.get("taskRequirements") or []:
            if (req.get("task") or {}).get("id") not in task_ids:
                rep.warn("task requirement points at an unknown task", (t.get("name"), req))
        for entry in (t.get("finishRewards") or {}).get("items") or []:
            check_items(rep, "reward", [entry.get("item")])
        for group in t.get("neededKeys") or []:
            check_items(rep, "needed key", group.get("keys"))
            if group.get("map") and group["map"].get("id") not in map_ids:
                rep.warn("needed-keys map not in the maps list", group.get("map"))
        for kind in ("objectives", "failConditions"):
            for o in t.get(kind) or []:
                check_objective(rep, label, kind, o, map_ids, types if kind == "objectives" else None)
                if kind == "objectives" and o.get("id"):
                    other = seen_objectives.setdefault(o["id"], t.get("name"))
                    if other != t.get("name"):
                        rep.error(f"[{mode}] objective id {o['id']} is used by {other!r} and {t.get('name')!r}"
                                  " (ticking one would tick both)")
    return types


def check_objective(rep: Report, label: str, kind: str, o: dict, map_ids: set, types) -> None:
    if not isinstance(o, dict):
        rep.error(f"{label}: {kind} entry is not an object: {o!r}")
        return
    if not o.get("type"):
        rep.error(f"{label}: objective {o.get('id')} has no type")
    if types is not None:
        types[o.get("type")] += 1
        if not o.get("id"):
            rep.warn("objective without an id (can't be ticked off)", (label, o.get("description")))
        if o.get("type") not in EXPLAINED:
            rep.warn(f"objective type {o.get('type')!r} has no how-to lines", (label, o.get("description")))
    if not o.get("description"):
        rep.warn("objective without a description", (label, o.get("type")))
    for m in o.get("maps") or []:
        if not (isinstance(m, dict) and m.get("id") and m.get("name")):
            rep.warn("objective map without id or name", (label, m))
        elif m["id"] not in map_ids:
            rep.warn("objective map not in the maps list", (label, m))
    for z in o.get("zones") or []:
        if (z.get("map") or {}).get("id") not in map_ids:
            rep.warn("zone on a map not in the maps list", (label, z))
    for loc in o.get("possibleLocations") or []:
        if (loc.get("map") or {}).get("id") not in map_ids:
            rep.warn("possible location on a map not in the maps list", (label, loc))
    for key in ITEM_LISTS:
        value = o.get(key)
        if value is not None and not isinstance(value, list):
            rep.error(f"{label}: objective {key} is not a list: {value!r}")
            continue
        check_items(rep, f"objective {key}", value)
    for key in ITEM_GROUPS:
        for group in o.get(key) or []:
            if not isinstance(group, list):
                rep.error(f"{label}: objective {key} entry is not a list: {group!r}")
                continue
            check_items(rep, f"objective {key}", group)
    for key in ITEM_REFS:
        if o.get(key) is not None:
            check_items(rep, f"objective {key}", [o[key]])


def check_mode(rep: Report, mode: str, args) -> None:
    print(f"\n== {mode} ==")
    client = TarkovClient(game_mode=mode, timeout=120)
    staticapi.clear_cache()
    out: dict = {}
    for name in ("maps", "tasks", "hideout", "barters", "crafts", "ammo", "bosses", "goons", "traders",
                 "cashoffers", "flea", "achievements"):
        try:
            start = time.time()
            out[name] = getattr(staticapi, name)(client)
            size = len(out[name]) if hasattr(out[name], "__len__") else "-"
            print(f"  {name:13} ok  {size:>5}  {time.time() - start:5.1f}s")
        except Exception:
            rep.error(f"[{mode}] {name} crashed:\n{traceback.format_exc()}")

    maps = out.get("maps") or []
    map_ids = {m.get("id") for m in maps}
    for m in maps:
        if not m.get("normalizedName"):
            rep.warn("map without normalizedName (hidden in the app)", m.get("name"))
    types = check_tasks(rep, mode, out.get("tasks") or [], map_ids)
    print("  objective types:", dict(types.most_common()))
    check_quest_maps(rep, mode, out, args.map_images, dump=args.dump_quest_maps and mode == "regular")

    for station in out.get("hideout") or []:
        for level in station.get("levels") or []:
            for req in level.get("itemRequirements") or []:
                check_items(rep, "hideout requirement", [req.get("item")])
    for kind in ("barters", "crafts"):
        for entry in out.get(kind) or []:
            for side in ("requiredItems", "rewardItems"):
                for req in entry.get(side) or []:
                    check_items(rep, f"{kind} {side}", [req.get("item")])
    for a in out.get("ammo") or []:
        if not isinstance(a.get("damage"), (int, float)) or not isinstance(a.get("penetrationPower"), (int, float)):
            rep.warn("ammo without damage or penetration numbers", (a.get("item") or {}).get("name"))
    for t in out.get("traders") or []:
        if not t.get("name"):
            rep.warn("trader without a name", t.get("id"))

    db = PriceDB(cache_path=None, game_mode=mode)
    price_lists = {}
    for label, fetch in [("price list (data file)", db.fetch_items_files)] + (
            [("price list (item list)", db.fetch_items_lite)] if mode == "regular" else []):
        try:
            items = price_lists[label] = fetch()
            print(f"  {label:24} ok  {len(items):>5} items")
            if len(items) < 1000:
                rep.error(f"[{mode}] {label}: only {len(items)} items")
            for it in items[:5000]:
                if not getattr(it, "name", None):
                    rep.warn(f"{label}: item without a name", getattr(it, "uid", None))
        except Exception:
            rep.error(f"[{mode}] {label} crashed:\n{traceback.format_exc()}")
    # The app's own price list: PvP from the item list, PvE from the data file.
    app_items = price_lists.get("price list (item list)") or price_lists.get("price list (data file)") or []
    check_price_watch(rep, mode, client, app_items)

    try:
        hideout_needs, quest_needs = db.fetch_needs()
        print(f"  needed items             ok  hideout {len(hideout_needs or {})}, quests {len(quest_needs or {})}")
        if hideout_needs is None or quest_needs is None:
            rep.error(f"[{mode}] needed items: a source failed")
    except Exception:
        rep.error(f"[{mode}] needed items crashed:\n{traceback.format_exc()}")

    # Item panels: a fixed random sample plus items quests ask for.
    try:
        all_ids = sorted(staticapi.Source(client).items)
    except Exception:
        rep.error(f"[{mode}] item file crashed:\n{traceback.format_exc()}")
        all_ids = []
    quest_ids = sorted({ref["id"] for t in out.get("tasks") or [] for o in t.get("objectives") or []
                        for ref in (o.get("items") or []) if named(ref)})
    sample = random.Random(1).sample(all_ids, min(args.items, len(all_ids))) + quest_ids[: args.items // 2]
    ok = 0
    for item_id in sample:
        try:
            detail = staticapi.item_detail(client, item_id, tasks_data=out.get("tasks"),
                                           barters_data=out.get("barters"), crafts_data=out.get("crafts"))
            if not (detail.get("item") or {}).get("name"):
                rep.warn("item panel without a name", item_id)
            ok += 1
        except Exception:
            rep.error(f"[{mode}] item panel for {item_id} crashed:\n{traceback.format_exc()}")
    print(f"  item panels              ok  {ok}/{len(sample)}")

    if args.graphql:
        try:
            gql = datasets._q(datasets.TASKS_QUERY, "tasks")(client)
            print(f"  GraphQL tasks            ok  {len(gql)} (data files: {len(out.get('tasks') or [])})")
        except Exception as exc:
            print(f"  GraphQL tasks            failed (not counted): {str(exc)[:200]}")


def check_labels(rep: Report) -> None:
    """tarkov.dev's own place labels (maps.json) land on the drawings."""
    groups = TarkovClient().get_json(datasets.TARKOV_DEV_DATA + "maps.json")
    drawings = questmap.Drawings(None, TarkovClient().get_bytes)
    for g in groups:
        for variant in g.get("maps") or []:
            entry = questmap.quest_entry(variant) if variant.get("projection") == "interactive" else None
            if not entry or not entry.get("svg") or not variant.get("labels"):
                continue
            try:
                _svg, view = drawings.get(entry["svg"], entry.get("svgLayer"))
            except Exception as exc:
                rep.warn("tarkov.dev map drawing failed", f"{entry['key']}: {exc}")
                continue
            pic = questmap.svg_picture(entry, *view)
            off = [lab.get("text") for lab in variant["labels"]
                   if not all(-0.02 <= v <= 1.02 for v in pic.fraction(entry, lab["position"][0], lab["position"][1]))]
            minx, miny, maxx, maxy = questmap.box(entry, entry.get("svgBounds") or entry["bounds"])
            shape = (view[0] / view[1]) / ((maxx - minx) / (maxy - miny))
            print(f"  drawing {entry['key']:20} {view[0]:.0f}x{view[1]:.0f}, shape vs bounds {shape:.3f}, "
                  f"{len(variant['labels']) - len(off)}/{len(variant['labels'])} labels on it")
            if off:
                rep.warn("tarkov.dev place labels off their map drawing", f"{entry['key']}: {off[:5]}")
            if not 0.9 < shape < 1.1:
                rep.warn("map drawing a different shape from its bounds", f"{entry['key']}: {shape:.3f}")


def _inside(point, polygon) -> bool:
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def check_quest_maps(rep: Report, mode: str, out: dict, images: Optional[dict], dump: bool) -> None:
    """Quest markers on tarkov.dev's map drawings, placed by the app's own code:
    every map with quest positions gets a picture, markers land on it, a
    zone's marker is inside its own outline, and tarkov.dev's place labels
    land on the picture too. With ``dump``, prints the markers (compressed)
    so they can be drawn on the real drawings and looked at elsewhere."""
    if not images:
        rep.error(f"[{mode}] quest maps: no map images")
        return
    drawings = questmap.Drawings(None, TarkovClient().get_bytes)
    maps = [m for m in out.get("maps") or [] if m.get("normalizedName")]
    tasks = out.get("tasks") or []
    dumped = []
    totals = collections.Counter()
    for m in sorted(maps, key=lambda m: m["normalizedName"]):
        norm = m["normalizedName"]
        positions = sum(1 for t in tasks for o in t.get("objectives") or []
                        for p in [z.get("position") for z in o.get("zones") or [] if (z.get("map") or {}).get("id") == m.get("id")]
                        + [p for loc in o.get("possibleLocations") or [] if (loc.get("map") or {}).get("id") == m.get("id")
                           for p in loc.get("positions") or []] if p)
        try:
            result = questmap.build(maps, tasks, images, norm, drawings)
        except Exception:
            rep.error(f"[{mode}] quest map for {norm} crashed:\n{traceback.format_exc()}")
            continue
        pic = result["picture"]
        markers = [mk for q in result["quests"] for mk in q["markers"]]
        off_picture = [mk for mk in markers if not (-0.01 <= mk["x"] <= 1.01 and -0.01 <= mk["y"] <= 1.01)]
        outside_own_outline = [mk for mk in markers if mk.get("outline") and not _inside((mk["x"], mk["y"]), mk["outline"])]
        floors = collections.Counter(mk["floor"] for mk in markers if mk.get("floor"))
        totals.update(positions=positions, markers=len(markers), outside=result["outside"], quests=len(result["quests"]))
        kind = pic["kind"] if pic else "-"
        extra = f" tiles z{pic['tiles']['zoom']} {pic['tiles']['columns']}x{pic['tiles']['rows']}" if pic and pic["kind"] == "tiles" else ""
        print(f"  quest map {norm:22} {kind:5}{extra:14} {len(result['quests']):3} quests {len(markers):4} spots "
              f"({positions} positions, {result['outside']} off tarkov.dev's map) floors {dict(floors.most_common(4))}")
        if positions and not pic:
            rep.warn("quest positions on a map the app can't draw them on", f"{norm}: {result.get('error') or 'no interactive map'}")
        if result.get("error"):
            rep.warn("tarkov.dev map drawing failed (tiles used instead)", f"{norm}: {result['error']}")
        if off_picture:
            rep.warn("quest markers off the map picture", f"{norm}: {len(off_picture)}, e.g. {off_picture[0]['text'][:60]}")
        if outside_own_outline:
            rep.warn("zone markers outside their own outline", f"{norm}: {len(outside_own_outline)}, e.g. {outside_own_outline[0]['text'][:60]}")
        if positions and result["outside"] > positions / 2:
            rep.error(f"[{mode}] {norm}: {result['outside']} of {positions} quest positions are off the map: the map's bounds look wrong")
        if pic and dump:
            n = lambda v: round(v * 10000)  # noqa: E731
            dumped.append({"map": norm, "p": [pic["key"], pic["kind"], pic["width"], pic["height"]],
                           "q": [[q["name"], [[n(mk["x"]), n(mk["y"]), mk["kind"][0], mk.get("floor"),
                                               [n(c) for pt in mk.get("outline") or [] for c in pt]] for mk in q["markers"]]]
                                 for q in result["quests"]]})
    print(f"  quest maps               ok  {totals['quests']} quest/map pairs, {totals['markers']} spots from "
          f"{totals['positions']} positions, {totals['outside']} off tarkov.dev's maps")
    if not totals["markers"]:
        rep.error(f"[{mode}] no quest markers on any map")
    # Tiles: the ones the app would show exist.
    for g in images.values():
        entry = (g or {}).get("quest") or {}
        if entry.get("tiles") and not entry.get("svg"):
            layout = questmap.tile_layout(entry)
            corners = [(layout["x0"] + c, layout["y0"] + r) for c, r in ((0, 0), (layout["columns"] - 1, layout["rows"] - 1),
                                                                           (layout["columns"] // 2, layout["rows"] // 2))]
            ok = 0
            for x, y in corners:
                url = layout["url"].replace("{z}", str(layout["zoom"])).replace("{x}", str(x)).replace("{y}", str(y))
                try:
                    ok += len(TarkovClient().get_bytes(url)) > 100
                except Exception as exc:
                    rep.warn("map tile missing", f"{url}: {exc}")
            print(f"  tiles {entry['key']:20} z{layout['zoom']} {layout['columns']}x{layout['rows']}: {ok}/{len(corners)} sample tiles there")
    if dump and dumped:  # printed last (see main), so the end of the log has it
        import base64
        import gzip
        blob = base64.b64encode(gzip.compress(json.dumps(dumped, separators=(",", ":")).encode(), 9)).decode()
        DUMP.extend("QMDUMP " + blob[i:i + 4000] for i in range(0, len(blob), 4000))


def check_price_watch(rep: Report, mode: str, client: TarkovClient, items) -> None:
    """Price histories (the item chart and the price watch) and one price
    watch check, as the app does it after a price update. With --save, the
    histories it looked up are kept, so the replayed app's price watch finds them."""
    eligible = sorted((i for i in items if pricewatch.eligible(i) and i.avg24h), key=lambda i: -(i.avg24h or 0))
    spacing, spans, empty = [], [], []
    for it in eligible[:3] + eligible[len(eligible) // 2:len(eligible) // 2 + 3]:
        try:
            points = staticapi.price_history(client, it.id)
        except Exception:
            rep.error(f"[{mode}] price history for {it.name} crashed:\n{traceback.format_exc()}")
            continue
        stamps = sorted(float(p["timestamp"]) for p in points if p.get("timestamp") is not None)
        if not points:
            empty.append(it.name)
            continue
        if any(not isinstance(p.get("price"), (int, float)) for p in points):
            rep.warn("price history point without a numeric price", points[0])
        gaps = [(b - a) / 60000 for a, b in zip(stamps, stamps[1:])]
        spacing.append(sorted(gaps)[len(gaps) // 2] if gaps else 0)
        spans.append((stamps[-1] - stamps[0]) / 86400e3 if len(stamps) > 1 else 0)
        avg = pricewatch.weekly_average(points)
        print(f"    {it.name[:40]:40} {len(points):>4} prices over {spans[-1]:.1f} days, 7-day avg lowest "
              f"{avg.low and round(avg.low)} (now {it.last_low}), average {avg.price and round(avg.price)}, "
              f"offers {avg.offers}")
    if spacing:
        print(f"  price histories          ok  every ~{sorted(spacing)[len(spacing) // 2]:.0f} min, "
              f"{min(spans):.1f}-{max(spans):.1f} days")
    if empty and not spacing:
        rep.error(f"[{mode}] every price history checked was empty: {empty}")
    elif empty:
        rep.warn("price history empty", empty[0])
    try:
        counts = staticapi.offer_counts(client)
        print(f"  offer counts             ok  {len(counts)} items, "
              f"{sum(1 for n in counts.values() if n >= pricewatch.MIN_OFFERS_NOW)} with {pricewatch.MIN_OFFERS_NOW}+ offers")
        if len(counts) < 1000:
            rep.error(f"[{mode}] offer counts for only {len(counts)} items: the price watch can't skip thin markets")
    except Exception:
        rep.error(f"[{mode}] offer counts crashed:\n{traceback.format_exc()}")
    try:
        start = time.time()
        watch = pricewatch.PriceWatch(lambda: items, lambda item_id: staticapi.price_history(client, item_id),
                                      offers=lambda: staticapi.offer_counts(client))
        result = watch.check()
        print(f"  price watch              ok  {len(result['cheap'])} cheap now, {len(result['high'])} selling high, "
              f"{result['compared']} compared, {result['waiting']} waiting ({time.time() - start:.1f}s)")
        for e in result["cheap"][:6] + result["high"][:6]:
            print(f"    {e['list']:5} {e['name'][:40]:40} lowest {e['low']:>9} vs 7-day {e['avg7']:>9} ({e['diff']:+.0%}), "
                  f"24h avg {e['avg24']} vs {e['avg7All']}, {e['offers']} offers")
        if result["error"]:
            rep.warn("price watch download errors", result["error"])
    except Exception:
        rep.error(f"[{mode}] price watch crashed:\n{traceback.format_exc()}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--save", type=Path, help="keep downloaded files here")
    parser.add_argument("--graphql", action="store_true", help="also try the GraphQL API (not counted)")
    parser.add_argument("--items", type=int, default=40, help="random item panels to build per mode")
    parser.add_argument("--dump-quest-maps", action="store_true", help="print PvP quest markers, compressed, to draw elsewhere")
    parser.add_argument("--only-quest-maps", action="store_true", help="only the quest map check, PvP")
    args = parser.parse_args(argv)
    args.map_images = None
    record_downloads(args.save)
    rep = Report()
    if args.only_quest_maps:
        args.map_images = datasets._map_images(TarkovClient())
        check_labels(rep)
        client = TarkovClient(game_mode="regular", timeout=120)
        out = {"maps": staticapi.maps(client), "tasks": staticapi.tasks(client)}
        check_quest_maps(rep, "regular", out, args.map_images, dump=args.dump_quest_maps)
        return finish(rep)
    try:
        status = staticapi.status(TarkovClient())
        print("status ok:", [s.get("name") for s in status.get("currentStatuses") or []][:8])
    except Exception:
        rep.error(f"status crashed:\n{traceback.format_exc()}")
    # Map images and wipe dates come from tarkov.dev's website data on GitHub.
    for label, fetch in (("map images", datasets._map_images), ("wipe dates", datasets._wipes)):
        try:
            result = fetch(TarkovClient())
            print(f"{label} ok: {len(result)}")
            if label == "map images":
                args.map_images = result
                interactive = sorted(k for k, g in result.items() if g.get("quest"))
                print(f"  interactive maps: {interactive}")
                if len(interactive) < 8:
                    rep.error(f"only {len(interactive)} maps have tarkov.dev's interactive map data")
                check_labels(rep)
        except Exception:
            rep.error(f"{label} crashed:\n{traceback.format_exc()}")
    for mode in ("regular", "pve"):
        check_mode(rep, mode, args)
    return finish(rep)


def finish(rep: Report) -> int:
    print("\n== warnings ==")
    for message, count in rep.warnings.most_common():
        example = rep.examples.get(message)
        print(f"  {count:5}x {message}" + (f"   e.g. {str(example)[:160]}" if example is not None else ""))
    print(f"\n{len(rep.errors)} error(s), {sum(rep.warnings.values())} warning(s)")
    for line in DUMP:
        print(line)
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
