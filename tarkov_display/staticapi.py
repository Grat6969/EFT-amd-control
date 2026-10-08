"""tarkov.dev's data files at json.tarkov.dev (the source its own website uses).

tarkov.dev's GraphQL API answers a query from a shared cache when someone
has asked exactly the same thing lately, and otherwise from one origin
server; when that server is slow it answers "GraphQL server unavailable".
Their website stopped using GraphQL and loads these plain JSON files from a
CDN instead, so they keep working when GraphQL doesn't.

The files hold ids where GraphQL gives objects, and translation keys where
it gives text (with a separate English file). This module turns them into
the same shapes the app's GraphQL queries return, so the rest of the app
doesn't care which source the data came from.

File layouts follow tarkov.dev's data manager (jobs/update-*.mjs), which
writes them, and their website (src/features/*/do-fetch-*.mjs), which reads
them.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from functools import cached_property
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .client import ApiError, TarkovClient

log = logging.getLogger(__name__)

STATIC_URL = "https://json.tarkov.dev/"
AMMO_CATEGORY = "5485a8684bdc2da71d8b4567"
NOT_AMMO = {"6241c316234b593b5676b637"}  # BB, left out by tarkov.dev's own ammo list
FLEA_VENDOR = {"name": "Flea Market", "normalizedName": "flea-market"}
CURRENCIES = {"RUB": "Roubles", "USD": "Dollars", "EUR": "Euros"}
HISTORY_DAYS = 7

ITEM_KEYS = (
    "id", "name", "shortName", "normalizedName", "description", "basePrice", "width", "height", "weight",
    "backgroundColor", "iconLink", "gridImageLink", "image512pxLink", "inspectImageLink", "wikiLink", "link",
    "types", "avg24hPrice", "lastLowPrice", "low24hPrice", "high24hPrice", "changeLast48h",
    "changeLast48hPercent", "lastOfferCount", "updated", "minLevelForFlea", "categories",
    "buyFromTrader", "sellToTrader",
)
AMMO_KEYS = (
    "caliber", "ammoType", "tracer", "tracerColor", "projectileCount", "damage", "armorDamage",
    "fragmentationChance", "ricochetChance", "penetrationChance", "penetrationPower", "initialSpeed",
    "accuracyModifier", "recoilModifier", "lightBleedModifier", "heavyBleedModifier",
)


# -- JSONPath, as far as the files' translation lists use it ----------------------------------

_STEP = re.compile(r"\.\.[A-Za-z_]\w*|\.\*|\[\*\]|\.[A-Za-z_]\w*|\[\s*'[^']*'(?:\s*,\s*'[^']*')*\s*\]")


def _children(value) -> Iterable[Tuple[Any, Any, Any]]:
    if isinstance(value, dict):
        return ((value, k, v) for k, v in value.items())
    if isinstance(value, list):
        return ((value, i, v) for i, v in enumerate(value))
    return ()


def _descend(value, name) -> Iterable[Tuple[Any, Any, Any]]:
    """``..name``: every ``name`` property in ``value`` and below it."""
    stack = [value]
    while stack:
        node = stack.pop()
        if isinstance(node, dict) and name in node:
            yield node, name, node[name]
        stack.extend(v for _, _, v in _children(node))


def jsonpath(root, path: str) -> List[Tuple[Any, Any]]:
    """(container, key) for each value ``path`` selects in ``root``."""
    if not path.startswith("$"):
        raise ValueError(f"unsupported JSONPath {path!r}")
    nodes = [(None, None, root)]
    pos = 1
    while pos < len(path):
        m = _STEP.match(path, pos)
        if not m:
            raise ValueError(f"unsupported JSONPath {path!r}")
        step, pos = m.group(0), m.end()
        found = []
        for _, _, value in nodes:
            if step.startswith(".."):
                found.extend(_descend(value, step[2:]))
            elif step in (".*", "[*]"):
                found.extend(_children(value))
            elif step.startswith("["):
                names = re.findall(r"'([^']*)'", step)
                if isinstance(value, dict):
                    found.extend((value, n, value[n]) for n in names if n in value)
            elif isinstance(value, dict) and step[1:] in value:
                found.append((value, step[1:], value[step[1:]]))
        nodes = found
    return [(parent, key) for parent, key, _ in nodes]


# Text fields the files leave as translation keys although the English file has them.
EXTRA_TRANSLATIONS = {
    "maps": ("$.data.maps.*.transits[*].conditions", "$.data.maps.*.bosses[*].spawnTrigger"),
}


def translate(doc: dict, locale: Dict[str, str], extra: Iterable[str] = ()) -> None:
    """Swap the translation keys at the file's own ``translations`` paths (and
    ``extra`` ones) for English text; keys without a translation stay as they are."""
    for path in list(doc.get("translations") or []) + list(extra):
        try:
            for parent, key in jsonpath(doc, path):
                value = parent[key]
                if isinstance(value, str):
                    parent[key] = locale.get(value, value)
        except ValueError as exc:
            log.debug("skipping translation path: %s", exc)


# -- downloading, shared by everything that needs a file ----------------------------------------

_cache: Dict[str, Tuple[float, Any]] = {}
_locks: Dict[str, threading.Lock] = {}
_guard = threading.Lock()


def load(client: TarkovClient, path: str, *, translated: bool = False, max_age: float = 1800,
         prepare: Optional[Callable[[Any], Any]] = None):
    """A file's ``data``, downloaded at most every ``max_age`` seconds however
    many datasets need it. ``prepare`` shrinks it to what's worth keeping."""
    with _guard:
        lock = _locks.setdefault(path, threading.Lock())
    with lock:
        hit = _cache.get(path)
        if hit and time.time() - hit[0] < max_age:
            return hit[1]
        doc = client.get_json(STATIC_URL + path)
        if not isinstance(doc, dict) or "data" not in doc:
            raise ApiError(f"tarkov.dev's {path} file isn't in the expected format")
        if translated:
            locale = client.get_json(f"{STATIC_URL}{path}_en")
            translate(doc, (locale or {}).get("data") or {}, EXTRA_TRANSLATIONS.get(path.rsplit("/", 1)[-1], ()))
        data = prepare(doc["data"]) if prepare else doc["data"]
        _cache[path] = (time.time(), data)
        return data


def clear_cache() -> None:
    with _guard:
        _cache.clear()


def _number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _values(collection) -> list:
    if isinstance(collection, dict):
        return list(collection.values())
    return list(collection or [])


def _index(collection) -> dict:
    """Records by id, whether the file keeps them in an object or a list."""
    if isinstance(collection, dict):
        return collection
    return {r["id"]: r for r in collection or [] if isinstance(r, dict) and r.get("id")}


def _prepare_items(data: dict) -> dict:
    """Keep what the app uses of the (large) item file."""
    items = {}
    for raw in _values(data.get("items")):
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        rec = {k: raw.get(k) for k in ITEM_KEYS}
        props = raw.get("properties") or {}
        cats = raw.get("categories") or []
        if (AMMO_CATEGORY in cats or props.get("propertiesType") == "ItemPropertiesAmmo") and raw["id"] not in NOT_AMMO:
            rec["ammo"] = {k: props.get(k) for k in AMMO_KEYS}
        items[raw["id"]] = rec
    categories = {}
    cats = data.get("itemCategories") or {}
    for cid, cat in (cats.items() if isinstance(cats, dict) else ((c.get("id"), c) for c in cats if isinstance(c, dict))):
        if isinstance(cat, dict):
            categories[cid] = cat.get("name")
    return {"items": items, "categories": categories, "fleaMarket": data.get("fleaMarket") or {}}


class Source:
    """tarkov.dev's files for one game mode, with lookups that turn ids into
    the small objects GraphQL would return."""

    def __init__(self, client: TarkovClient) -> None:
        self.client = client
        self.mode = "pve" if client.game_mode == "pve" else "regular"

    def file(self, name: str, translated: bool = True, max_age: float = 1800, prepare=None):
        return load(self.client, f"{self.mode}/{name}", translated=translated, max_age=max_age, prepare=prepare)

    def item_file(self, max_age: float = 1800) -> dict:
        return self.file("items", max_age=max_age, prepare=_prepare_items)

    @cached_property
    def items(self) -> dict:
        return self.item_file()["items"]

    @cached_property
    def traders(self) -> dict:
        return _index(self.file("traders"))

    @cached_property
    def maps_file(self) -> dict:
        return self.file("maps")

    @cached_property
    def map_index(self) -> dict:
        return _index(self.maps_file.get("maps"))

    @cached_property
    def mobs(self) -> dict:
        return _index(self.maps_file.get("mobs"))

    @cached_property
    def tasks_file(self) -> dict:
        return self.file("tasks")

    @cached_property
    def task_index(self) -> dict:
        return _index(self.tasks_file.get("tasks"))

    @cached_property
    def quest_items(self) -> dict:
        return _index(self.tasks_file.get("questItems"))

    @cached_property
    def stations(self) -> dict:
        return _index(self.file("hideout"))

    # -- references --------------------------------------------------------

    def item(self, item_id) -> dict:
        it = self.items.get(item_id) or {}
        return {"id": item_id, "name": it.get("name"), "shortName": it.get("shortName"), "iconLink": it.get("iconLink")}

    def trader(self, trader_id) -> Optional[dict]:
        if not trader_id:
            return None
        t = self.traders.get(trader_id) or {}
        return {"id": trader_id, "name": t.get("name"), "normalizedName": t.get("normalizedName"),
                "imageLink": t.get("imageLink")}

    def map(self, map_id) -> Optional[dict]:
        if not map_id:
            return None
        m = self.map_index.get(map_id) or {}
        return {"id": map_id, "name": m.get("name"), "normalizedName": m.get("normalizedName")}

    def task(self, task_id) -> Optional[dict]:
        if not task_id:
            return None
        t = self.task_index.get(task_id) or {}
        return {"id": task_id, "name": t.get("name")}

    def station(self, station_id) -> Optional[dict]:
        if not station_id:
            return None
        s = self.stations.get(station_id) or {}
        return {"id": station_id, "name": s.get("name"), "normalizedName": s.get("normalizedName"),
                "imageLink": s.get("imageLink")}

    def quest_item(self, item_id) -> dict:
        q = self.quest_items.get(item_id) or {}
        return {"id": item_id, "name": q.get("name"), "shortName": q.get("shortName"), "iconLink": q.get("iconLink")}

    def contained(self, entry) -> dict:
        """{item: id, count, attributes: {type: value}} as GraphQL's ContainedItem."""
        entry = entry or {}
        attrs = entry.get("attributes") or {}
        if isinstance(attrs, dict):
            attrs = [{"type": k, "name": k, "value": str(v).lower() if isinstance(v, bool) else v} for k, v in attrs.items()]
        return {"count": entry.get("count") if entry.get("count") is not None else entry.get("quantity"),
                "attributes": attrs, "item": self.item(entry.get("item"))}


# -- datasets, in the shapes of the app's GraphQL queries ---------------------------------------

def _objective(o: dict, src: Source) -> dict:
    out = {"id": o.get("id"), "type": o.get("type"), "description": o.get("description"),
           "optional": bool(o.get("optional")), "maps": [src.map(m) for m in o.get("maps") or [] if m]}
    for key in ("count", "foundInRaid", "targetNames", "exitName", "playerLevel"):
        if key in o:
            out[key] = o[key]
    if o.get("items"):
        out["items"] = [src.item(i) for i in o["items"] if i]
    if o.get("requiredKeys"):
        out["requiredKeys"] = [[src.item(k) for k in group if k] for group in o["requiredKeys"] if group]
    if o.get("questItem"):
        out["questItem"] = src.quest_item(o["questItem"])
    if o.get("markerItem"):
        out["markerItem"] = src.item(o["markerItem"])
    if o.get("item"):
        out["item"] = src.item(o["item"])
    if o.get("useAny"):
        out["useAny"] = [src.item(i) for i in o["useAny"] if i]
    if o.get("skill"):
        out["skillLevel"] = {"name": o["skill"], "level": o.get("level")}
    if o.get("trader"):
        out["trader"] = src.trader(o["trader"])
        out["level"] = o.get("level")
    return out


def _rewards(r: Optional[dict], src: Source) -> dict:
    r = r or {}
    return {
        "items": [{"count": x.get("count"), "item": src.item(x["item"])} for x in r.get("items") or [] if x.get("item")],
        "traderStanding": [{"trader": src.trader(x.get("trader")), "standing": x.get("standing")}
                           for x in r.get("traderStanding") or []],
        "offerUnlock": [{"level": x.get("level"), "trader": src.trader(x.get("trader")), "item": src.item(x.get("item"))}
                        for x in r.get("offerUnlock") or []],
        "skillLevelReward": [{"name": x.get("skill") or x.get("name"), "level": x.get("level")}
                             for x in r.get("skillLevelReward") or []],
        "traderUnlock": [src.trader(t) for t in r.get("traderUnlock") or [] if t],
        "craftUnlock": [{"id": x.get("id"), "level": x.get("level"), "station": src.station(x.get("station")),
                         "rewardItems": [{"count": x.get("count") or 1, "item": src.item(x.get("item"))}]}
                        for x in r.get("craftUnlock") or []],
    }


TASK_FIELDS = ("id", "name", "normalizedName", "experience", "wikiLink", "taskImageLink", "minPlayerLevel",
               "kappaRequired", "lightkeeperRequired", "factionName", "restartable")


def tasks(client: TarkovClient) -> List[dict]:
    src = Source(client)
    out = []
    for t in src.task_index.values():
        task = {k: t.get(k) for k in TASK_FIELDS}
        task.update(
            trader=src.trader(t.get("trader")),
            map=src.map(t.get("map")),
            taskRequirements=[{"task": src.task(r["task"]), "status": r.get("status") or []}
                              for r in t.get("taskRequirements") or [] if r.get("task")],
            traderRequirements=[{"trader": src.trader(r.get("trader")), "requirementType": r.get("requirementType"),
                                 "compareMethod": r.get("compareMethod"), "value": r.get("value")}
                                for r in t.get("traderRequirements") or []],
            objectives=[_objective(o, src) for o in t.get("objectives") or [] if isinstance(o, dict)],
            finishRewards=_rewards(t.get("finishRewards"), src),
        )
        out.append(task)
    if not out:
        raise ApiError("tarkov.dev's task file has no tasks")
    return out


def achievements(client: TarkovClient) -> List[dict]:
    keys = ("id", "name", "description", "hidden", "playersCompletedPercent", "adjustedPlayersCompletedPercent",
            "side", "normalizedSide", "rarity", "normalizedRarity", "imageLink")
    if client.game_mode != "regular":  # the same in both modes
        client = type(client)("regular")
    data = Source(client).tasks_file
    return [{k: a.get(k) for k in keys} for a in _values(data.get("achievements")) if isinstance(a, dict)]


def hideout(client: TarkovClient) -> List[dict]:
    src = Source(client)
    out = []
    for s in _values(src.stations):
        levels = []
        for lvl in s.get("levels") or []:
            levels.append({
                "id": lvl.get("id"), "level": lvl.get("level"), "constructionTime": lvl.get("constructionTime"),
                "description": lvl.get("description"),
                "itemRequirements": [src.contained(r) for r in lvl.get("itemRequirements") or [] if r.get("item")],
                "stationLevelRequirements": [{"level": r.get("level"), "station": src.station(r.get("station"))}
                                             for r in lvl.get("stationLevelRequirements") or []],
                "traderRequirements": [{"trader": src.trader(r.get("trader")), "requirementType": r.get("requirementType"),
                                        "compareMethod": r.get("compareMethod"), "value": r.get("value")}
                                       for r in lvl.get("traderRequirements") or []],
                "skillRequirements": [{"name": r.get("skill") or r.get("name"), "level": r.get("level")}
                                      for r in lvl.get("skillRequirements") or []],
                "bonuses": [{"type": b.get("type"), "name": b.get("name"), "value": b.get("value"),
                             "passive": b.get("passive"), "production": b.get("production"),
                             "skillName": b.get("skill") or b.get("skillName")}
                            for b in lvl.get("bonuses") or []],
            })
        out.append({"id": s.get("id"), "name": s.get("name"), "normalizedName": s.get("normalizedName"),
                    "imageLink": s.get("imageLink"), "levels": levels})
    if not out:
        raise ApiError("tarkov.dev's hideout file has no stations")
    return out


def barters(client: TarkovClient) -> List[dict]:
    src = Source(client)
    out = []
    for b in _values(src.file("barters", translated=False)):
        offered = b.get("offeredItem") or ((b.get("rewardItems") or [None])[0])
        out.append({
            "id": b.get("id"), "level": b.get("minTraderLevel", b.get("level")), "buyLimit": b.get("buyLimit"),
            "trader": src.trader(b.get("trader")), "taskUnlock": src.task(b.get("taskUnlock")),
            "requiredItems": [src.contained(r) for r in b.get("requiredItems") or [] if r.get("item")],
            "rewardItems": [src.contained(offered)] if offered else [],
        })
    return out


def crafts(client: TarkovClient) -> List[dict]:
    src = Source(client)
    out = []
    for c in _values(src.file("crafts", translated=False)):
        product = c.get("productItem") or ((c.get("rewardItems") or [None])[0])
        out.append({
            "id": c.get("id"), "level": c.get("level"), "duration": c.get("duration"),
            "station": src.station(c.get("station")), "taskUnlock": src.task(c.get("taskUnlock")),
            "requiredItems": [src.contained(r) for r in c.get("requiredItems") or [] if r.get("item")],
            "rewardItems": [src.contained(product)] if product else [],
        })
    return out


def ammo(client: TarkovClient) -> List[dict]:
    src = Source(client)
    out = []
    for rec in src.items.values():
        if rec.get("ammo"):
            out.append({**rec["ammo"], "item": src.item(rec["id"])})
    if not out:
        raise ApiError("tarkov.dev's item file has no ammo")
    return out


def maps(client: TarkovClient) -> List[dict]:
    src = Source(client)
    mobs = src.mobs

    def boss(mob_id, portrait=True):
        m = mobs.get(mob_id) or {}
        out = {"id": mob_id, "name": m.get("name"), "normalizedName": m.get("normalizedName")}
        if portrait:
            out["imagePortraitLink"] = m.get("imagePortraitLink")
        return out

    out = []
    for m in src.map_index.values():
        out.append({
            **{k: m.get(k) for k in ("id", "name", "normalizedName", "nameId", "wiki", "description", "enemies",
                                     "raidDuration", "players", "minPlayerLevel", "maxPlayerLevel",
                                     "accessKeysMinPlayerLevel")},
            "accessKeys": [src.item(k) for k in m.get("accessKeys") or [] if k],
            "bosses": [{
                "spawnChance": b.get("spawnChance"), "spawnTime": b.get("spawnTime"),
                "spawnTimeRandom": b.get("spawnTimeRandom"), "spawnTrigger": b.get("spawnTrigger"),
                "boss": boss(b.get("mob") or b.get("id")),
                "spawnLocations": [{"name": loc.get("name"), "chance": loc.get("chance")} for loc in b.get("spawnLocations") or []],
                "escorts": [{"boss": boss(e.get("mob") or e.get("id"), portrait=False), "amount": e.get("amount") or []}
                            for e in b.get("escorts") or []],
            } for b in m.get("bosses") or []],
            "extracts": [{"id": x.get("id"), "name": x.get("name"), "faction": x.get("faction")} for x in m.get("extracts") or []],
            "transits": [{"id": x.get("id"), "description": x.get("description"), "conditions": x.get("conditions"),
                          "map": src.map(x.get("map"))} for x in m.get("transits") or []],
            "locks": [{"lockType": x.get("lockType"), "needsPower": x.get("needsPower"), "key": src.item(x.get("key"))}
                      for x in m.get("locks") or [] if x.get("key")],
            "hazards": [{"hazardType": x.get("hazardType"), "name": x.get("name")} for x in m.get("hazards") or []],
        })
    if not out:
        raise ApiError("tarkov.dev's map file has no maps")
    return out


def bosses(client: TarkovClient) -> List[dict]:
    src = Source(client)
    out = []
    for m in src.mobs.values():
        out.append({
            **{k: m.get(k) for k in ("id", "name", "normalizedName", "imagePortraitLink", "imagePosterLink")},
            "health": [{"bodyPart": h.get("bodyPart"), "max": h.get("max")} for h in m.get("health") or []],
            "equipment": [{"count": e.get("count"), "item": src.item(e.get("item"))} for e in m.get("equipment") or [] if e.get("item")],
        })
    return out


def goons(client: TarkovClient) -> List[dict]:
    src = Source(client)
    reports = [r for r in src.maps_file.get("goonReports") or [] if isinstance(r, dict)]
    reports.sort(key=lambda r: _number(r.get("timestamp")), reverse=True)
    return [{"timestamp": str(r.get("timestamp")), "map": src.map(r.get("map"))} for r in reports[:10]]


def traders(client: TarkovClient) -> List[dict]:
    src = Source(client)
    src.__dict__["traders"] = _index(src.file("traders", max_age=60))  # reset times change often
    level_keys = ("id", "level", "requiredPlayerLevel", "requiredReputation", "requiredCommerce", "payRate",
                  "insuranceRate", "repairCostMultiplier")
    out = []
    for t in _values(src.traders):
        code = t.get("currency")
        currency = {"id": code, "name": CURRENCIES.get(code, code), "shortName": code} if isinstance(code, str) else code
        out.append({
            **{k: t.get(k) for k in ("id", "name", "normalizedName", "description", "resetTime", "imageLink", "image4xLink")},
            "currency": currency,
            "levels": [{k: lvl.get(k) for k in level_keys} for lvl in t.get("levels") or []],
        })
    if not out:
        raise ApiError("tarkov.dev's trader file has no traders")
    return out


def cashoffers(client: TarkovClient) -> List[dict]:
    src = Source(client)
    by_trader: Dict[str, list] = {}
    for rec in src.items.values():
        for offer in rec.get("buyFromTrader") or []:
            by_trader.setdefault(offer.get("trader"), []).append({
                "minTraderLevel": offer.get("minTraderLevel"), "price": offer.get("price"),
                "currency": offer.get("currency"), "priceRUB": offer.get("priceRUB"),
                "buyLimit": offer.get("buyLimit"), "taskUnlock": src.task(offer.get("taskUnlock")),
                "item": src.item(rec["id"]),
            })
    out = []
    for trader_id, offers in by_trader.items():
        ref = src.trader(trader_id) or {}
        out.append({"id": trader_id, "name": ref.get("name"), "normalizedName": ref.get("normalizedName"),
                    "cashOffers": offers})
    return out


def flea(client: TarkovClient) -> dict:
    data = Source(client).item_file()["fleaMarket"]
    keys = ("minPlayerLevel", "enabled", "sellOfferFeeRate", "sellRequirementFeeRate", "foundInRaidRequired",
            "reputationLevels")
    if not data:
        raise ApiError("tarkov.dev's item file has no flea market settings")
    return {k: data.get(k) for k in keys}


def status(client: TarkovClient) -> dict:
    data = load(client, "status", max_age=60)
    if not isinstance(data, dict) or "currentStatuses" not in data:
        raise ApiError("tarkov.dev's status file isn't in the expected format")
    return data


# -- prices and item details ------------------------------------------------------------------

def price_list(client: TarkovClient, max_age: float = 300) -> List[dict]:
    """Every item in the shape of the price list's GraphQL query."""
    src = Source(client)
    items = src.item_file(max_age=max_age)["items"]
    out = []
    for rec in items.values():
        out.append({
            **{k: rec.get(k) for k in ("id", "name", "shortName", "types", "width", "height", "basePrice", "iconLink",
                                       "wikiLink", "avg24hPrice", "lastLowPrice", "low24hPrice",
                                       "changeLast48hPercent", "updated", "link")},
            "sellFor": [{"priceRUB": o.get("priceRUB"), "vendor": {"name": (src.trader(o.get("trader")) or {}).get("name")}}
                        for o in rec.get("sellToTrader") or []],
        })
    if not out:
        raise ApiError("tarkov.dev's item file has no items")
    return out


def _mentions(lists: Iterable[Iterable[dict]], item_id: str) -> bool:
    return any((entry.get("item") or {}).get("id") == item_id for entries in lists for entry in entries or [])


def item_detail(client: TarkovClient, item_id: str, *, tasks_data=None, barters_data=None, crafts_data=None) -> dict:
    """One item in the shape of the item panel's GraphQL query."""
    src = Source(client)
    rec = src.items.get(item_id)
    if not rec:
        raise ApiError("tarkov.dev has no item with that id")
    item = {k: rec.get(k) for k in ITEM_KEYS if k not in ("buyFromTrader", "sellToTrader", "categories")}
    cats = [src.item_file()["categories"].get(c) for c in rec.get("categories") or []]
    item["category"] = {"name": next((c for c in cats if c), None)}
    banned = "noFlea" in (rec.get("types") or [])

    sell = []
    if rec.get("lastLowPrice") and not banned:
        sell.append({"price": rec["lastLowPrice"], "currency": "RUB", "priceRUB": rec["lastLowPrice"], "vendor": dict(FLEA_VENDOR)})
    for o in rec.get("sellToTrader") or []:
        t = src.trader(o.get("trader")) or {}
        sell.append({"price": o.get("price"), "currency": o.get("currency"), "priceRUB": o.get("priceRUB"),
                     "vendor": {"name": t.get("name"), "normalizedName": t.get("normalizedName")}})
    buy = []
    flea_buy = rec.get("avg24hPrice") or rec.get("lastLowPrice")
    if flea_buy and not banned:
        buy.append({"price": flea_buy, "currency": "RUB", "priceRUB": flea_buy, "vendor": dict(FLEA_VENDOR)})
    for o in rec.get("buyFromTrader") or []:
        t = src.trader(o.get("trader")) or {}
        buy.append({"price": o.get("price"), "currency": o.get("currency"), "priceRUB": o.get("priceRUB"),
                    "vendor": {"name": t.get("name"), "normalizedName": t.get("normalizedName"),
                               "minTraderLevel": o.get("minTraderLevel"), "buyLimit": o.get("buyLimit"),
                               "taskUnlock": src.task(o.get("taskUnlock"))}})
    item.update(sellFor=sell, buyFor=buy)

    def task_ref(t):
        return {"id": t.get("id"), "name": t.get("name"), "trader": {"name": (t.get("trader") or {}).get("name")}}

    def needs(task):
        for o in task.get("objectives") or []:
            refs = list(o.get("items") or []) + list(o.get("useAny") or [])
            refs += [o[k] for k in ("markerItem", "item") if o.get(k)]
            if any((r or {}).get("id") == item_id for r in refs):
                return True
        return False

    item["usedInTasks"] = [task_ref(t) for t in tasks_data or [] if needs(t)]
    item["receivedFromTasks"] = [task_ref(t) for t in tasks_data or []
                                 if _mentions([(t.get("finishRewards") or {}).get("items")], item_id)]
    item["bartersFor"] = [b for b in barters_data or [] if _mentions([b.get("rewardItems")], item_id)]
    item["bartersUsing"] = [b for b in barters_data or [] if _mentions([b.get("requiredItems")], item_id)]
    item["craftsFor"] = [c for c in crafts_data or [] if _mentions([c.get("rewardItems")], item_id)]
    item["craftsUsing"] = [c for c in crafts_data or [] if _mentions([c.get("requiredItems")], item_id)]

    history = []
    try:
        doc = client.get_json(f"{STATIC_URL}{src.mode}/prices/{item_id}")
        since = (time.time() - HISTORY_DAYS * 86400) * 1000
        history = [p for p in (doc or {}).get("data") or []
                   if isinstance(p, dict) and _number(p.get("timestamp")) >= since]
        history.sort(key=lambda p: _number(p.get("timestamp")))
    except Exception as exc:  # the chart is optional
        log.debug("no price history for %s: %s", item_id, exc)
    return {"item": item, "history": history}
