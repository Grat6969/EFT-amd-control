"""Everything else tarkov.dev offers: quests, hideout, barters, crafts, ammo,
maps, traders, bosses, achievements, server status and goon sightings.

Each dataset comes from tarkov.dev's data files (json.tarkov.dev, what
their website uses; see staticapi), or from a small GraphQL request if a
file can't be read. Datasets are cached on disk and refreshed in the
background when they get old. Map images and wipe dates come from the
tarkov.dev website's own data files on GitHub.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional

from . import staticapi
from .client import ApiError, TarkovClient, drop_nulls

log = logging.getLogger(__name__)

ITEM = "id name shortName iconLink"

TASKS_QUERY = """
query Tasks {
  tasks(lang: en%(mode)s) {
    id name normalizedName experience wikiLink taskImageLink minPlayerLevel
    kappaRequired lightkeeperRequired factionName restartable
    trader { id name normalizedName imageLink }
    map { id name normalizedName }
    taskRequirements { task { id name } status }
    traderRequirements { trader { id name } requirementType compareMethod value }
    objectives {
      id type description optional
      maps { id name normalizedName }
      ... on TaskObjectiveItem { count foundInRaid items { ITEM } requiredKeys { ITEM } }
      ... on TaskObjectiveQuestItem { count questItem { ITEM } requiredKeys { ITEM } }
      ... on TaskObjectiveMark { markerItem { ITEM } requiredKeys { ITEM } }
      ... on TaskObjectiveBuildItem { item { ITEM } }
      ... on TaskObjectiveShoot { count targetNames }
      ... on TaskObjectiveExtract { count exitName requiredKeys { ITEM } }
      ... on TaskObjectiveBasic { requiredKeys { ITEM } }
      ... on TaskObjectiveUseItem { count useAny { ITEM } }
      ... on TaskObjectiveSkill { skillLevel { name level } }
      ... on TaskObjectiveTraderLevel { trader { id name } level }
      ... on TaskObjectivePlayerLevel { playerLevel }
    }
    finishRewards {
      items { count item { ITEM } }
      traderStanding { trader { id name } standing }
      offerUnlock { level trader { id name } item { ITEM } }
      skillLevelReward { name level }
      traderUnlock { id name }
      craftUnlock { id level station { id name } rewardItems { count item { ITEM } } }
    }
  }
}
""".replace("ITEM", ITEM)

HIDEOUT_QUERY = """
query Hideout {
  hideoutStations(lang: en%(mode)s) {
    id name normalizedName imageLink
    levels {
      id level constructionTime description
      itemRequirements { count attributes { type name value } item { ITEM } }
      stationLevelRequirements { level station { id name } }
      traderRequirements { trader { id name } requirementType compareMethod value }
      skillRequirements { name level }
      bonuses { type name value passive production skillName }
    }
  }
}
""".replace("ITEM", ITEM)

BARTERS_QUERY = """
query Barters {
  barters(lang: en%(mode)s) {
    id level buyLimit
    trader { id name normalizedName imageLink }
    taskUnlock { id name }
    requiredItems { count attributes { type name value } item { ITEM } }
    rewardItems { count item { ITEM } }
  }
}
""".replace("ITEM", ITEM)

CRAFTS_QUERY = """
query Crafts {
  crafts(lang: en%(mode)s) {
    id level duration
    station { id name normalizedName imageLink }
    taskUnlock { id name }
    requiredItems { count attributes { type name value } item { ITEM } }
    rewardItems { count item { ITEM } }
  }
}
""".replace("ITEM", ITEM)

AMMO_QUERY = """
query Ammo {
  ammo(lang: en%(mode)s) {
    caliber ammoType tracer tracerColor projectileCount damage armorDamage
    fragmentationChance ricochetChance penetrationChance penetrationPower
    initialSpeed accuracyModifier recoilModifier lightBleedModifier heavyBleedModifier
    item { ITEM }
  }
}
""".replace("ITEM", ITEM)

MAPS_QUERY = """
query Maps {
  maps(lang: en%(mode)s) {
    id name normalizedName nameId wiki description enemies raidDuration players
    minPlayerLevel maxPlayerLevel accessKeysMinPlayerLevel
    accessKeys { ITEM }
    bosses {
      spawnChance spawnTime spawnTimeRandom spawnTrigger
      boss { id name normalizedName imagePortraitLink }
      spawnLocations { name chance }
      escorts { boss { id name normalizedName } amount { count chance } }
    }
    extracts { id name faction }
    transits { id description conditions map { id name normalizedName } }
    locks { lockType needsPower key { ITEM } }
    hazards { hazardType name }
  }
}
""".replace("ITEM", ITEM)

TRADERS_QUERY = """
query Traders {
  traders(lang: en%(mode)s) {
    id name normalizedName description resetTime imageLink image4xLink
    currency { id name shortName }
    levels { id level requiredPlayerLevel requiredReputation requiredCommerce payRate insuranceRate repairCostMultiplier }
  }
}
"""

CASH_OFFERS_QUERY = """
query CashOffers {
  traders(lang: en%(mode)s) {
    id name normalizedName
    cashOffers { minTraderLevel price currency priceRUB buyLimit taskUnlock { id name } item { ITEM } }
  }
}
""".replace("ITEM", ITEM)

BOSSES_QUERY = """
query Bosses {
  bosses(lang: en%(mode)s) {
    id name normalizedName imagePortraitLink imagePosterLink
    health { bodyPart max }
    equipment { count item { ITEM } }
  }
}
""".replace("ITEM", ITEM)

ACHIEVEMENTS_QUERY = """
query Achievements {
  achievements(lang: en) {
    id name description hidden playersCompletedPercent adjustedPlayersCompletedPercent
    side normalizedSide rarity normalizedRarity imageLink
  }
}
"""

STATUS_QUERY = """
query Status {
  status {
    generalStatus { name message status statusCode }
    currentStatuses { name message status statusCode }
    messages { content time type solveTime statusCode }
  }
}
"""

GOONS_QUERY = """
query Goons {
  goonReports(lang: en%(mode)s, limit: 10) { timestamp map { id name normalizedName } }
}
"""

FLEA_QUERY = """
query Flea {
  fleaMarket(lang: en%(mode)s) {
    minPlayerLevel enabled sellOfferFeeRate sellRequirementFeeRate foundInRaidRequired
    reputationLevels { offers minRep maxRep }
  }
}
"""

ITEM_QUERY = """
query Item($id: ID!) {
  item(id: $id, lang: en%(mode)s) {
    id name shortName normalizedName description basePrice width height weight
    backgroundColor iconLink gridImageLink image512pxLink inspectImageLink wikiLink link types
    avg24hPrice lastLowPrice low24hPrice high24hPrice changeLast48h changeLast48hPercent
    lastOfferCount updated minLevelForFlea
    category { name }
    sellFor { price currency priceRUB vendor { name normalizedName ... on TraderOffer { minTraderLevel } } }
    buyFor {
      price currency priceRUB
      vendor { name normalizedName ... on TraderOffer { minTraderLevel buyLimit taskUnlock { id name } } }
    }
    usedInTasks { id name trader { name } }
    receivedFromTasks { id name trader { name } }
    bartersFor { ...BarterParts }
    bartersUsing { ...BarterParts }
    craftsFor { ...CraftParts }
    craftsUsing { ...CraftParts }
  }
  history: historicalItemPrices(id: $id, days: 7%(mode)s) { price priceMin offerCount timestamp }
}
fragment BarterParts on Barter {
  id level buyLimit trader { id name normalizedName } taskUnlock { id name }
  requiredItems { count attributes { type value } item { ITEM } }
  rewardItems { count item { ITEM } }
}
fragment CraftParts on Craft {
  id level duration station { id name normalizedName } taskUnlock { id name }
  requiredItems { count attributes { type value } item { ITEM } }
  rewardItems { count item { ITEM } }
}
""".replace("ITEM", ITEM)

# The tarkov.dev website's own data files: which 2D map images exist (and
# who made them), and wipe start dates.
TARKOV_DEV_DATA = "https://raw.githubusercontent.com/the-hideout/tarkov-dev/main/src/data/"
MAP_IMAGE_URL = "https://tarkov.dev/maps/{key}.jpg"
INTERACTIVE_MAP_URL = "https://tarkov.dev/map/{name}"

HOUR = 3600


@dataclass(frozen=True)
class Dataset:
    name: str
    ttl: float
    fetch: Callable[[TarkovClient], object]
    per_mode: bool = True  # PvE and PvP data differ


def _q(query: str, key: str) -> Callable[[TarkovClient], object]:
    return lambda client: client.query(query)[key]


def _files_or_query(from_files: Callable[[TarkovClient], object], query: str, key: str) -> Callable[[TarkovClient], object]:
    """tarkov.dev's data file first; their GraphQL API only if that fails.
    (GraphQL answers uncommon queries from one origin server, which is often
    overloaded: "GraphQL server unavailable".)"""
    def fetch(client: TarkovClient):
        try:
            return from_files(client)
        except Exception as exc:
            log.warning("tarkov.dev data file failed (%s); trying their GraphQL API", exc)
            try:
                return client.query(query)[key]
            except Exception as gql_exc:
                raise ApiError(f"Data file: {exc}. GraphQL: {gql_exc}") from None
    return fetch


def _map_images(client: TarkovClient):
    """2D/3D map images per map, from tarkov.dev's maps.json."""
    groups = client.get_json(TARKOV_DEV_DATA + "maps.json")
    out = {}
    for group in groups:
        images = []
        for variant in group.get("maps") or []:
            projection = variant.get("projection")
            if projection not in ("2D", "3D"):
                continue  # interactive maps are tiles, not one image
            images.append({
                "key": variant["key"],
                "projection": projection,
                "orientation": variant.get("orientation"),
                "url": MAP_IMAGE_URL.format(key=variant["key"]),
                "author": variant.get("author"),
                "authorLink": variant.get("authorLink"),
            })
        out[group["normalizedName"]] = {
            "images": images,
            "interactive": INTERACTIVE_MAP_URL.format(name=group["normalizedName"]),
        }
    return out


def _wipes(client: TarkovClient):
    return client.get_json(TARKOV_DEV_DATA + "wipe-details.json")


DATASETS: Dict[str, Dataset] = {d.name: d for d in [
    Dataset("tasks", 6 * HOUR, _files_or_query(staticapi.tasks, TASKS_QUERY, "tasks")),
    Dataset("hideout", 6 * HOUR, _files_or_query(staticapi.hideout, HIDEOUT_QUERY, "hideoutStations")),
    Dataset("barters", 6 * HOUR, _files_or_query(staticapi.barters, BARTERS_QUERY, "barters")),
    Dataset("crafts", 6 * HOUR, _files_or_query(staticapi.crafts, CRAFTS_QUERY, "crafts")),
    Dataset("ammo", 12 * HOUR, _files_or_query(staticapi.ammo, AMMO_QUERY, "ammo")),
    Dataset("maps", 12 * HOUR, _files_or_query(staticapi.maps, MAPS_QUERY, "maps")),
    Dataset("traders", 10 * 60, _files_or_query(staticapi.traders, TRADERS_QUERY, "traders")),  # reset timers
    Dataset("cashoffers", 6 * HOUR, _files_or_query(staticapi.cashoffers, CASH_OFFERS_QUERY, "traders")),
    Dataset("bosses", 24 * HOUR, _files_or_query(staticapi.bosses, BOSSES_QUERY, "bosses")),
    Dataset("achievements", 24 * HOUR, _files_or_query(staticapi.achievements, ACHIEVEMENTS_QUERY, "achievements"),
            per_mode=False),
    Dataset("status", 5 * 60, _files_or_query(staticapi.status, STATUS_QUERY, "status"), per_mode=False),
    Dataset("goons", 5 * 60, _files_or_query(staticapi.goons, GOONS_QUERY, "goonReports")),
    Dataset("flea", 24 * HOUR, _files_or_query(staticapi.flea, FLEA_QUERY, "fleaMarket")),
    Dataset("mapimages", 24 * HOUR, _map_images, per_mode=False),
    Dataset("wipes", 24 * HOUR, _wipes, per_mode=False),
]}

ITEM_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class DataStore:
    """Cached tarkov.dev datasets for one game mode."""

    def __init__(self, cache_dir: Optional[Path], game_mode: str = "regular",
                 client: Optional[TarkovClient] = None, on_update: Optional[Callable[[str], None]] = None) -> None:
        self.cache_dir = cache_dir
        self.game_mode = game_mode
        self.client = client or TarkovClient(game_mode)
        self.on_update = on_update or (lambda name: None)
        self._entries: Dict[str, dict] = {}
        self._loading: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._items: Dict[str, tuple] = {}  # item detail cache: id -> (time, data)

    # -- disk cache -------------------------------------------------------

    def _path(self, name: str) -> Optional[Path]:
        if not self.cache_dir:
            return None
        mode = self.game_mode if DATASETS[name].per_mode else "all"
        return self.cache_dir / f"data_{mode}_{name}.json"

    def _load(self, name: str) -> dict:
        entry = {"name": name, "data": None, "updated": 0.0, "error": None}
        path = self._path(name)
        if path and path.exists():
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    cached = json.load(fh)
                entry.update(data=drop_nulls(cached["data"]), updated=cached["updated"])
            except (OSError, ValueError, KeyError) as exc:
                log.warning("Ignoring cached %s: %s", name, exc)
        return entry

    def _save(self, name: str, entry: dict) -> None:
        path = self._path(name)
        if not path:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"updated": entry["updated"], "data": entry["data"]}, fh)
            os.replace(tmp, path)
        except OSError as exc:
            log.debug("Could not cache %s: %s", name, exc)

    # -- access -----------------------------------------------------------

    def _entry(self, name: str) -> dict:
        with self._lock:
            if name not in self._entries:
                self._entries[name] = self._load(name)
            return self._entries[name]

    def is_stale(self, name: str) -> bool:
        entry = self._entry(name)
        return entry["data"] is None or time.time() - entry["updated"] > DATASETS[name].ttl

    def snapshot(self, name: str) -> dict:
        entry = self._entry(name)
        return {
            "name": name,
            "data": entry["data"],
            "updated": entry["updated"],
            "error": entry["error"],
            "loading": name in self._loading,
        }

    def get(self, name: str, wait: float = 0.0) -> dict:
        """Current data for a dataset; refreshes it in the background if old.

        With ``wait``, blocks up to that many seconds when there is no data
        yet, so a first page load can show something.
        """
        if name not in DATASETS:
            raise KeyError(name)
        if self.is_stale(name):
            had_data = self._entry(name)["data"] is not None
            done = self.refresh_async(name)
            if wait and not had_data:
                done.wait(wait)
        return self.snapshot(name)

    def refresh_async(self, name: str) -> threading.Event:
        with self._lock:
            if name in self._loading:
                return self._loading[name]
            done = self._loading[name] = threading.Event()
        threading.Thread(target=self._refresh, args=(name, done), name=f"data-{name}", daemon=True).start()
        return done

    def refresh(self, name: str) -> dict:
        self.refresh_async(name).wait()
        return self.snapshot(name)

    def _refresh(self, name: str, done: threading.Event) -> None:
        entry = self._entry(name)
        try:
            data = DATASETS[name].fetch(self.client)
            with self._lock:
                entry.update(data=data, updated=time.time(), error=None)
            self._save(name, entry)
            log.info("Updated %s from tarkov.dev", name)
        except Exception as exc:
            with self._lock:
                entry["error"] = str(exc)
            log.warning("Could not update %s: %s", name, exc)
        finally:
            with self._lock:
                self._loading.pop(name, None)
            try:
                self.on_update(name)
            except Exception:
                log.exception("on_update failed")
            done.set()

    def status(self) -> list:
        return [
            {k: v for k, v in self.snapshot(name).items() if k != "data"} | {"ttl": DATASETS[name].ttl}
            for name in DATASETS
        ]

    def item(self, item_id: str, max_age: float = 600) -> dict:
        """Full details for one item (fetched on demand, cached briefly)."""
        if not ITEM_ID.match(item_id or ""):
            raise ValueError("bad item id")
        cached = self._items.get(item_id)
        if cached and time.time() - cached[0] < max_age:
            return cached[1]
        try:
            # Quests, barters and crafts that mention it come from the loaded
            # datasets (asking for them also starts loading any that aren't).
            result = staticapi.item_detail(self.client, item_id, tasks_data=self.get("tasks")["data"],
                                           barters_data=self.get("barters")["data"],
                                           crafts_data=self.get("crafts")["data"])
        except Exception as exc:
            log.info("Item details from tarkov.dev's data files failed (%s); trying GraphQL", exc)
            data = self.client.query(ITEM_QUERY, variables={"id": item_id})
            result = {"item": data.get("item"), "history": data.get("history") or []}
        with self._lock:  # requests come in on several threads
            self._items[item_id] = (time.time(), result)
            if len(self._items) > 200:
                oldest = min(self._items, key=lambda k: self._items[k][0])
                self._items.pop(oldest, None)
        return result
