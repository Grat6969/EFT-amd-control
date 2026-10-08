"""Flea market and trader prices from the free tarkov.dev API."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from . import staticapi
from .client import ApiError, TarkovClient, error_message  # noqa: F401  (re-exported)

log = logging.getLogger(__name__)
# tarkov.dev's plain item list. Everyone gets the same response, so it is
# usually served from their cache, and it keeps working when their GraphQL
# back end is down.
LITE_ITEMS_URL = "https://api.tarkov.dev/api/v1/items"
FLEA = "Flea Market"
USD_ID = "5696686a4bdc2da3298b456a"
EUR_ID = "569668774bdc2da2298b4568"
CURRENCY_SYMBOLS = {"\u20bd": "RUB", "$": "USD", "\u20ac": "EUR"}
PAGE_SIZE = 500
MAX_PAGES = 40
NEEDS_MAX_AGE = 6 * 3600  # quest/hideout requirements only change with game patches

# Used for PvE, and for PvP if the item list fails. Paged so no single
# request comes near tarkov.dev's 20 second limit.
ITEMS_QUERY = """
query Items {
  items(lang: en%(mode)s, limit: %(limit)d, offset: %(offset)d) {
    id name shortName types width height basePrice iconLink wikiLink
    avg24hPrice lastLowPrice low24hPrice changeLast48hPercent updated link
    sellFor { priceRUB vendor { name } }
  }
}
"""

HIDEOUT_QUERY = """
query Hideout {
  hideoutStations(lang: en%(mode)s) {
    name
    levels { level itemRequirements { count item { id } } }
  }
}
"""

TASKS_QUERY = """
query Tasks {
  tasks(lang: en%(mode)s) {
    name
    objectives {
      ... on TaskObjectiveItem { count foundInRaid items { id } }
    }
  }
}
"""


@dataclass
class Item:
    id: str
    name: str
    short_name: str
    avg24h: Optional[int] = None
    last_low: Optional[int] = None
    low24h: Optional[int] = None
    change48h: Optional[float] = None
    base_price: int = 0
    slots: int = 1
    size: str = ""  # e.g. "2x1", when known
    flea_banned: bool = False
    is_preset: bool = False
    best_trader: Optional[str] = None
    best_trader_price: int = 0  # roubles
    quests: List[str] = field(default_factory=list)
    hideout: List[str] = field(default_factory=list)
    link: str = ""
    icon: str = ""
    wiki: str = ""
    tags: List[str] = field(default_factory=list)

    @property
    def flea_price(self) -> Optional[int]:
        """Typical flea price: 24h average, else the lowest current listing."""
        if self.flea_banned:
            return None
        return self.avg24h or self.last_low

    @property
    def best_value(self) -> int:
        return max(self.flea_price or 0, self.best_trader_price)

    @property
    def best_place(self) -> str:
        if self.flea_price and self.flea_price > self.best_trader_price:
            return FLEA
        return self.best_trader or "-"

    @property
    def per_slot(self) -> int:
        return self.best_value // max(1, self.slots)

    @property
    def needed_for(self) -> str:
        parts = []
        if self.hideout:
            parts.append("Hideout: " + ", ".join(self.hideout))
        if self.quests:
            parts.append("Quests: " + ", ".join(self.quests))
        return " | ".join(parts)


def parse_graphql_items(raw_items: List[dict]) -> List[Item]:
    """Items from the GraphQL ``items`` query."""
    items = []
    for raw in raw_items:
        types = raw.get("types") or []
        best_name, best_price = None, 0
        for offer in raw.get("sellFor") or []:
            vendor = (offer.get("vendor") or {}).get("name")
            price = offer.get("priceRUB") or 0
            if vendor and vendor != FLEA and price > best_price:
                best_name, best_price = vendor, price
        width, height = raw.get("width") or 1, raw.get("height") or 1
        items.append(
            Item(
                id=raw["id"],
                name=raw.get("name") or "",
                short_name=raw.get("shortName") or "",
                avg24h=raw.get("avg24hPrice") or None,
                last_low=raw.get("lastLowPrice") or None,
                low24h=raw.get("low24hPrice") or None,
                change48h=raw.get("changeLast48hPercent"),
                base_price=raw.get("basePrice") or 0,
                slots=width * height,
                size=f"{width}x{height}",
                flea_banned="noFlea" in types,
                is_preset="preset" in types,
                best_trader=best_name,
                best_trader_price=best_price,
                link=raw.get("link") or "",
                icon=raw.get("iconLink") or "",
                wiki=raw.get("wikiLink") or "",
                tags=list(types),
            )
        )
    return items


def parse_lite_items(raw_items: List[dict]) -> List[Item]:
    """Items from the plain ``/api/v1/items`` list.

    It gives the best trader's price in that trader's own currency, so
    dollar and euro prices are converted with the Dollars and Euros items'
    handbook value, the same rate tarkov.dev uses for its rouble prices.
    """
    rates = {"RUB": 1}
    for raw in raw_items:
        if raw.get("uid") == USD_ID and raw.get("basePrice"):
            rates["USD"] = raw["basePrice"]
        elif raw.get("uid") == EUR_ID and raw.get("basePrice"):
            rates["EUR"] = raw["basePrice"]

    items = []
    for raw in raw_items:
        if not raw.get("uid"):
            continue
        tags = raw.get("tags") or []
        currency = CURRENCY_SYMBOLS.get(raw.get("traderPriceCur") or "")
        rate = rates.get(currency) if currency else None
        trader_rub = int(round((raw.get("traderPrice") or 0) * rate)) if rate else 0
        # diff24h is the change over 48h in roubles; turn it into percent.
        avg, diff = raw.get("avg24hPrice"), raw.get("diff24h")
        change = None
        if isinstance(diff, (int, float)) and avg and avg - diff > 0:
            change = round(diff / (avg - diff) * 100, 2)
        items.append(
            Item(
                id=raw["uid"],
                name=raw.get("name") or "",
                short_name=raw.get("shortName") or "",
                avg24h=raw.get("avg24hPrice") or None,
                last_low=raw.get("price") or None,
                change48h=change,
                base_price=raw.get("basePrice") or 0,
                slots=raw.get("slots") or 1,
                flea_banned="noFlea" in tags,
                is_preset="preset" in tags,
                best_trader=raw.get("traderName") if trader_rub else None,
                best_trader_price=trader_rub,
                link=raw.get("link") or "",
                icon=raw.get("icon") or "",
                wiki=raw.get("wikiLink") or "",
                tags=list(tags),
            )
        )
    return items


def parse_hideout(stations: List[dict]) -> Dict[str, List[str]]:
    needs: Dict[str, List[str]] = {}
    for station in stations:
        for level in station.get("levels") or []:
            for req in level.get("itemRequirements") or []:
                item = (req or {}).get("item") or {}
                if item.get("id"):
                    needs.setdefault(item["id"], []).append(
                        f"{station['name']} {level['level']} x{req.get('count', 1)}"
                    )
    return needs


def parse_tasks(tasks: List[dict]) -> Dict[str, List[str]]:
    """Quests that need each item: "Quest name x2 FiR"."""
    per_item: Dict[str, Dict[str, list]] = {}
    for task in tasks:
        for objective in task.get("objectives") or []:
            for item in (objective or {}).get("items") or []:
                if not item or not item.get("id"):
                    continue
                entry = per_item.setdefault(item["id"], {}).setdefault(task["name"], [0, False])
                entry[0] = max(entry[0], objective.get("count") or 1)
                entry[1] = entry[1] or bool(objective.get("foundInRaid"))
    return {
        item_id: [f"{name} x{count}" + (" FiR" if fir else "") for name, (count, fir) in sorted(quests.items())]
        for item_id, quests in per_item.items()
    }


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


class PriceDB:
    """Holds the item list, cached on disk and refreshed in the background."""

    def __init__(self, cache_path: Optional[Path] = None, game_mode: str = "regular", max_age: float = 900):
        self.cache_path = cache_path
        self.game_mode = game_mode
        self.client = TarkovClient(game_mode)
        self.max_age = max_age
        self.items: List[Item] = []
        self.updated: float = 0.0
        self.needs_updated: float = 0.0
        self.error: Optional[str] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.load_cache()

    def set_items(self, items: List[Item], updated: Optional[float] = None) -> None:
        self.items = items  # swapped in one go so readers never see a half list
        self.updated = updated or time.time()

    @property
    def age(self) -> float:
        return time.time() - self.updated if self.updated else float("inf")

    def load_cache(self) -> None:
        if not self.cache_path or not self.cache_path.exists():
            return
        try:
            with open(self.cache_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("game_mode", "regular") != self.game_mode:
                return
            self.set_items([Item(**i) for i in data["items"]], data["updated"])
            self.needs_updated = data.get("needs_updated", 0.0)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.warning("Ignoring price cache: %s", exc)

    def save_cache(self) -> None:
        if not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "updated": self.updated,
                    "needs_updated": self.needs_updated,
                    "game_mode": self.game_mode,
                    "items": [asdict(i) for i in self.items],
                },
                fh,
            )
        os.replace(tmp, self.cache_path)

    def get_json(self, url: str):
        return self.client.get_json(url)

    def query(self, template: str, **params) -> dict:
        return self.client.query(template, **params)

    def fetch_items_graphql(self) -> List[Item]:
        raw: List[dict] = []
        for page in range(MAX_PAGES):
            batch = self.query(ITEMS_QUERY, limit=PAGE_SIZE, offset=page * PAGE_SIZE).get("items") or []
            raw += batch
            if len(batch) < PAGE_SIZE:
                break
        return parse_graphql_items(raw)

    def fetch_items_files(self) -> List[Item]:
        """From tarkov.dev's item data file (what their website uses)."""
        return parse_graphql_items(staticapi.price_list(self.client, max_age=self.max_age / 3))

    def fetch_items(self) -> List[Item]:
        # PvP: the small plain item list first. (It ignores PvE and returns PvP
        # prices, so PvE starts with the data file.) GraphQL comes last: it
        # often fails with "GraphQL server unavailable".
        sources = [("data file", self.fetch_items_files), ("GraphQL", self.fetch_items_graphql)]
        if self.game_mode != "pve":
            sources.insert(0, ("item list", self.fetch_items_lite))
        errors = []
        for name, fetch in sources:
            try:
                items = fetch()
                if items:
                    return items
                raise ApiError("no items")
            except Exception as exc:
                log.warning("tarkov.dev %s failed: %s", name, exc)
                errors.append(f"{name}: {exc}" if errors else str(exc))
        raise ApiError(errors[0] + (f" ({'; '.join(errors[1:])})" if len(errors) > 1 else ""))

    def fetch_items_lite(self) -> List[Item]:
        data = self.get_json(LITE_ITEMS_URL)
        if not isinstance(data, list):
            raise ApiError(error_message(json.dumps(data).encode(), 200, "OK"))
        return parse_lite_items(data)

    def fetch_needs(self):
        """(hideout, quests) by item id; None where the request failed."""
        def first(*fetchers):
            errors = []
            for fetch in fetchers:
                try:
                    return fetch()
                except Exception as exc:
                    errors.append(str(exc))
            raise ApiError("; ".join(errors))

        hideout = quests = None
        try:
            hideout = parse_hideout(first(lambda: staticapi.hideout(self.client),
                                          lambda: self.query(HIDEOUT_QUERY).get("hideoutStations") or []))
        except Exception as exc:
            log.warning("Hideout requirements unavailable: %s", exc)
        try:
            quests = parse_tasks(first(lambda: staticapi.tasks(self.client),
                                       lambda: self.query(TASKS_QUERY).get("tasks") or []))
        except Exception as exc:
            log.warning("Quest requirements unavailable: %s", exc)
        return hideout, quests

    def refresh(self) -> bool:
        with self._lock:
            try:
                items = self.fetch_items()
            except Exception as exc:
                self.error = str(exc)
                log.warning("Could not update prices from tarkov.dev: %s", exc)
                return False

            previous = {i.id: i for i in self.items}
            hideout = quests = None
            if time.time() - self.needs_updated > NEEDS_MAX_AGE:
                hideout, quests = self.fetch_needs()
                if hideout is not None and quests is not None:
                    self.needs_updated = time.time()
            for item in items:
                old = previous.get(item.id)
                item.hideout = hideout.get(item.id, []) if hideout is not None else (old.hideout if old else [])
                item.quests = quests.get(item.id, []) if quests is not None else (old.quests if old else [])

            self.set_items(items)
            self.error = None
            log.info("Prices updated: %d items", len(items))
            try:
                self.save_cache()
            except OSError as exc:
                log.debug("Could not save price cache: %s", exc)
            return True

    def start(self) -> None:
        def loop():
            while not self._stop.is_set():
                if self.age >= self.max_age:
                    self.refresh()
                self._stop.wait(60)

        self._thread = threading.Thread(target=loop, name="Prices", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def search(self, query: str, limit: int = 50) -> List[Item]:
        q = normalize(query)
        if not q:
            return []
        tokens = q.split()
        scored = []
        for item in self.items:
            name, short = normalize(item.name), normalize(item.short_name)
            if short == q or name == q:
                rank = 0
            elif name.startswith(q) or short.startswith(q):
                rank = 1
            elif all(t in name or t in short for t in tokens):
                rank = 2
            else:
                continue
            scored.append((rank, item.is_preset, -item.best_value, item.name, item))
        scored.sort(key=lambda s: s[:4])
        return [s[-1] for s in scored[:limit]]


def rub(value: Optional[int]) -> str:
    return f"{value:,} ₽".replace(",", " ") if value else "-"


def age_text(seconds: float) -> str:
    if seconds == float("inf"):
        return "never"
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return f"{int(seconds // 60)} min ago"
    return f"{int(seconds // 3600)} h ago"


def describe(item: Item) -> List[str]:
    lines = [item.name]
    if item.flea_banned:
        lines.append("Flea: can't be sold on flea")
    else:
        change = f"  ({item.change48h:+.0f}% 48h)" if item.change48h else ""
        lines.append(f"Flea: {rub(item.flea_price)} avg   lowest {rub(item.last_low)}{change}")
    if item.best_trader:
        lines.append(f"Trader: {item.best_trader} {rub(item.best_trader_price)}")
    slots = ""
    if item.slots > 1:
        slots = f" ({item.size})" if item.size else f" ({item.slots} slots)"
    lines.append(f"Per slot: {rub(item.per_slot)}{slots}   sell to: {item.best_place}")
    if item.hideout:
        lines.append("Hideout: " + ", ".join(item.hideout))
    if item.quests:
        quests = item.quests[:3] + ([f"+{len(item.quests) - 3} more"] if len(item.quests) > 3 else [])
        lines.append("Quests: " + ", ".join(quests))
    return lines
