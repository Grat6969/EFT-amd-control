"""Flea market and trader prices from the free tarkov.dev API."""

from __future__ import annotations

import json
import logging
import os
import re
import gzip
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

API_URL = "https://api.tarkov.dev/graphql"
FLEA = "Flea Market"

ITEMS_QUERY = """
query Items {
  items(lang: en%(mode)s) {
    id name shortName types width height basePrice
    avg24hPrice lastLowPrice low24hPrice changeLast48hPercent updated link
    sellFor { priceRUB vendor { name } }
    usedInTasks { name }
  }
}
"""

# Fetched separately: if it fails, prices still work, just without hideout info.
HIDEOUT_QUERY = """
query Hideout {
  hideoutStations(lang: en%(mode)s) {
    name
    levels { level itemRequirements { count item { id } } }
  }
}
"""


class ApiError(RuntimeError):
    pass


def error_message(body: bytes, status: int, reason: str) -> str:
    """Best explanation available from an error response."""
    try:
        errors = json.loads(body).get("errors") or []
        messages = [e.get("message", str(e)) if isinstance(e, dict) else str(e) for e in errors]
        if messages:
            return f"HTTP {status}: " + "; ".join(messages[:3])
    except (ValueError, AttributeError):
        pass
    text = body.decode("utf-8", "replace").strip()
    return f"HTTP {status} {reason}" + (f": {text[:300]}" if text else "")


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
    width: int = 1
    height: int = 1
    flea_banned: bool = False
    is_preset: bool = False
    best_trader: Optional[str] = None
    best_trader_price: int = 0
    quests: List[str] = field(default_factory=list)
    hideout: List[str] = field(default_factory=list)
    link: str = ""

    @property
    def slots(self) -> int:
        return max(1, self.width * self.height)

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
        return self.best_value // self.slots

    @property
    def needed_for(self) -> str:
        parts = []
        if self.hideout:
            parts.append("Hideout: " + ", ".join(self.hideout))
        if self.quests:
            parts.append("Quests: " + ", ".join(self.quests))
        return " | ".join(parts)


def parse_items(data: dict) -> List[Item]:
    """Turn a tarkov.dev GraphQL response into Item objects."""
    hideout: Dict[str, List[str]] = {}
    for station in data.get("hideoutStations") or []:
        for level in station.get("levels") or []:
            for req in level.get("itemRequirements") or []:
                item = req.get("item") or {}
                if item.get("id"):
                    hideout.setdefault(item["id"], []).append(
                        f"{station['name']} {level['level']} (x{req.get('count', 1)})"
                    )

    items = []
    for raw in data.get("items") or []:
        types = raw.get("types") or []
        best_name, best_price = None, 0
        for offer in raw.get("sellFor") or []:
            vendor = (offer.get("vendor") or {}).get("name")
            price = offer.get("priceRUB") or 0
            if vendor and vendor != FLEA and price > best_price:
                best_name, best_price = vendor, price
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
                width=raw.get("width") or 1,
                height=raw.get("height") or 1,
                flea_banned="noFlea" in types,
                is_preset="preset" in types,
                best_trader=best_name,
                best_trader_price=best_price,
                quests=sorted({t["name"] for t in raw.get("usedInTasks") or [] if t and t.get("name")}),
                hideout=hideout.get(raw["id"], []),
                link=raw.get("link") or "",
            )
        )
    return items


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


class PriceDB:
    """Holds the item list, cached on disk and refreshed in the background."""

    def __init__(self, cache_path: Optional[Path] = None, game_mode: str = "regular", max_age: float = 600):
        self.cache_path = cache_path
        self.game_mode = game_mode
        self.max_age = max_age
        self.items: List[Item] = []
        self.updated: float = 0.0
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
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.warning("Ignoring price cache: %s", exc)

    def save_cache(self) -> None:
        if not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(
                {"updated": self.updated, "game_mode": self.game_mode, "items": [asdict(i) for i in self.items]},
                fh,
            )
        os.replace(tmp, self.cache_path)

    def query(self, template: str) -> dict:
        mode = ", gameMode: pve" if self.game_mode == "pve" else ""
        body = json.dumps({"query": template % {"mode": mode}}).encode()
        req = urllib.request.Request(
            API_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                # Plain JSON: errors come back in the body with HTTP 200
                # instead of a bare 4xx status.
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "User-Agent": "TarkovDisplay/0.3",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            if exc.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            raise ApiError(error_message(raw, exc.code, exc.reason)) from None
        payload = json.loads(raw)
        if payload.get("errors"):
            log.debug("tarkov.dev reported: %s", payload["errors"])
        if not payload.get("data"):
            raise ApiError(error_message(raw, 200, "OK"))
        return payload["data"]

    def fetch(self) -> dict:
        data = {"items": self.query(ITEMS_QUERY).get("items") or []}
        try:
            data["hideoutStations"] = self.query(HIDEOUT_QUERY).get("hideoutStations") or []
        except Exception as exc:
            log.warning("Hideout requirements unavailable: %s", exc)
        return data

    def refresh(self) -> bool:
        with self._lock:
            try:
                items = parse_items(self.fetch())
            except Exception as exc:
                self.error = str(exc)
                log.warning("Could not update prices from tarkov.dev: %s", exc)
                return False
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
    slots = f" ({item.width}x{item.height})" if item.slots > 1 else ""
    lines.append(f"Per slot: {rub(item.per_slot)}{slots}   sell to: {item.best_place}")
    if item.hideout:
        lines.append("Hideout: " + ", ".join(item.hideout))
    if item.quests:
        quests = item.quests[:3] + ([f"+{len(item.quests) - 3} more"] if len(item.quests) > 3 else [])
        lines.append("Quests: " + ", ".join(quests))
    return lines
