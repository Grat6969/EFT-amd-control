"""Price watch: items whose flea price is far from their weekly average.

Two lists, rebuilt after every price update:

- cheap now: the lowest offer is at least ``threshold`` below the item's
  average price over the last 7 days (worth buying)
- selling high: the lowest offer is at least ``threshold`` above it (worth
  selling: you'd list just under that offer)

The price list (prices.py) has every item's lowest offer and 24 hour
average, but no weekly average: that takes the item's price history, one
download per item from tarkov.dev's data files (what its price chart
uses). Downloading thousands of them every 15 minutes would be rude, so:

- Only items whose price has visibly moved are looked up: a lowest offer
  far from the 24h average, or a big change over 48 hours. A move older than
  that has mostly worked its way into the weekly average anyway: an item
  that dropped 50% four days ago is now only about 30% below it.
- A weekly average changes slowly, so each one is kept for hours (on disk
  too) and compared with the latest lowest offer at every price update.
- A check downloads a few dozen histories at most, most promising first;
  the rest wait for the next check.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from .prices import Item

log = logging.getLogger(__name__)

LISTS = ("cheap", "high")
LISTED_MAX_AGE = 6 * 3600      # look up an item on a list again after this long...
AVERAGE_MAX_AGE = 12 * 3600    # ... and any other item whose price still moves after this long
AVERAGE_KEEP = 24 * 3600       # forget a weekly average older than this
FETCHES_PER_CHECK = 40         # price histories downloaded per check after a price update...
FETCHES_NOW = 120              # ... and per check you asked for
WORKERS = 4                    # downloads at a time
MIN_POINTS = 12                # a weekly average needs this many prices...
MIN_DAYS = 2.0                 # ... spread over at least this many days
ALERT_AGAIN_AFTER = 6 * 3600   # an item back on a list it left is news again after this long
MAX_ENTRIES = 200              # per list


@dataclass
class Average:
    """An item's average price over the last 7 days, from its history."""

    fetched: float           # when the history was downloaded
    price: Optional[float]   # None: not enough history to say
    points: int = 0
    days: float = 0.0        # how many days the history covers
    offers: Optional[int] = None  # offers on the flea at the latest point


def _number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def weekly_average(points: Sequence[dict], now: Optional[float] = None) -> Average:
    """The average of each day's average price. Days count equally however
    many prices were recorded on each, so a busy day doesn't outweigh the rest."""
    now = time.time() if now is None else now
    good = [(_number(p.get("timestamp")), _number(p.get("price"))) for p in points if isinstance(p, dict)]
    good = [(ts, price) for ts, price in good if ts > 0 and price > 0]
    offers = None
    if good:
        last = max((p for p in points if isinstance(p, dict)), key=lambda p: _number(p.get("timestamp")))
        offers = int(_number(last.get("offerCount"))) if last.get("offerCount") is not None else None
    if len(good) < MIN_POINTS:
        return Average(now, None, len(good), offers=offers)
    days = (max(ts for ts, _ in good) - min(ts for ts, _ in good)) / 86400e3
    if days < MIN_DAYS:
        return Average(now, None, len(good), days, offers)
    by_day: Dict[int, List[float]] = {}
    for ts, price in good:
        by_day.setdefault(int((now * 1000 - ts) // 86400e3), []).append(price)
    daily = [sum(v) / len(v) for v in by_day.values()]
    return Average(now, sum(daily) / len(daily), len(good), days, offers)


def eligible(item: Item) -> bool:
    """Sold on the flea right now, and not a weapon preset (priced from its parts)."""
    return bool(item.last_low) and item.last_low > 0 and not item.flea_banned and not item.is_preset


def signal(item: Item) -> float:
    """How far the price has visibly moved lately, as a fraction (0.3 = 30%):
    the lowest offer against the 24h average, or the change over 48 hours."""
    moves = [0.0]
    if item.avg24h and item.last_low:
        moves.append(abs(item.last_low / item.avg24h - 1))
    if item.change48h is not None:
        moves.append(abs(item.change48h) / 100)
    return max(moves)


def typical_price(item: Item) -> float:
    """Roughly what the item went for lately: the most of its lowest offer,
    24h average, and 24h average two days ago."""
    prices = [item.last_low or 0, item.avg24h or 0]
    if item.avg24h and item.change48h is not None and item.change48h > -100:
        prices.append(item.avg24h / (1 + item.change48h / 100))
    return max(prices)


def classify(low: float, average: float, threshold: float) -> Optional[str]:
    if not low or not average:
        return None
    ratio = low / average
    if ratio <= 1 - threshold + 1e-9:
        return "cheap"
    if ratio >= 1 + threshold - 1e-9:
        return "high"
    return None


class PriceWatch:
    """The two lists for one game mode. ``items`` returns the current price
    list; ``history`` downloads one item's price history (see
    staticapi.price_history)."""

    def __init__(self, items: Callable[[], List[Item]], history: Callable[[str], List[dict]],
                 path: Optional[Path] = None, clock: Callable[[], float] = time.time) -> None:
        self.items = items
        self.history = history
        self.path = path
        self.clock = clock
        self.averages: Dict[str, Average] = {}
        self.since: Dict[str, Dict[str, float]] = {k: {} for k in LISTS}  # list -> item -> when it joined
        self.alerted: Dict[str, float] = {}  # "list:item" -> when it was last news
        self.result: dict = {"cheap": [], "high": [], "checked": 0, "compared": 0, "waiting": 0, "error": None,
                             "new": {k: [] for k in LISTS}}
        self._check_lock = threading.Lock()  # one check at a time
        self._lock = threading.Lock()        # the queue below
        self._queued: Optional[dict] = None
        self._running = False   # the background thread is alive
        self._checking = False  # ... and in the middle of a check
        self._on_done: Callable[[dict], None] = lambda result: None
        self.load()

    # -- checking -------------------------------------------------------

    def check(self, threshold: float = 0.5, min_price: int = 10000, budget: int = FETCHES_PER_CHECK,
              quiet: bool = False) -> dict:
        """Look up what needs looking up (at most ``budget`` histories) and
        rebuild both lists. The result's ``new`` names items that just joined
        a list, unless ``quiet`` (say, after you changed the settings)."""
        with self._check_lock:
            now = self.clock()
            items = [i for i in self.items() if eligible(i)]
            self._forget_old(now)
            wanted = self._wanted(items, threshold, min_price, now)
            error = self._download(wanted[:max(0, budget)], now)

            lists: Dict[str, List[dict]] = {k: [] for k in LISTS}
            compared = 0
            for item in items:
                avg = self.averages.get(item.id)
                if not avg or not avg.price or avg.price < min_price:
                    continue
                compared += 1
                kind = classify(item.last_low, avg.price, threshold)
                if kind:
                    lists[kind].append(self._entry(item, avg, kind, now))
            lists["cheap"].sort(key=lambda e: e["diff"])
            lists["high"].sort(key=lambda e: -e["diff"])

            new = {}
            for kind in LISTS:
                ids = [e["id"] for e in lists[kind]]
                before = self.since[kind]
                self.since[kind] = {i: before.get(i, now) for i in ids}
                joined = [i for i in ids if i not in before
                          and now - self.alerted.get(f"{kind}:{i}", 0) > ALERT_AGAIN_AFTER]
                for i in joined:
                    self.alerted[f"{kind}:{i}"] = now
                new[kind] = [] if quiet else joined
            for kind in LISTS:
                for e in lists[kind]:
                    e["since"] = self.since[kind][e["id"]]

            self.result = {
                "cheap": lists["cheap"][:MAX_ENTRIES], "high": lists["high"][:MAX_ENTRIES],
                "checked": now, "compared": compared, "waiting": max(0, len(wanted) - max(0, budget)),
                "error": error, "new": new, "threshold": threshold, "minPrice": min_price,
            }
            try:
                self.save()
            except OSError as exc:
                log.debug("Could not save the price watch: %s", exc)
            if lists["cheap"] or lists["high"] or wanted:
                log.info("Price watch: %d cheap, %d selling high (%d histories looked up, %d waiting)",
                         len(lists["cheap"]), len(lists["high"]), min(len(wanted), budget), self.result["waiting"])
            return self.result

    def _wanted(self, items: List[Item], threshold: float, min_price: int, now: float) -> List[Item]:
        """Items whose history should be looked up, most important first:
        those on a list (to keep it right), then those whose price moved most."""
        listed = set(self.since["cheap"]) | set(self.since["high"])
        ranked = []
        for item in items:
            avg = self.averages.get(item.id)
            age = now - avg.fetched if avg is not None else float("inf")
            moved = signal(item)
            if item.id in listed:
                if age >= LISTED_MAX_AGE:
                    ranked.append((0, -moved, item))
            elif age >= AVERAGE_MAX_AGE and moved >= threshold / 2 and typical_price(item) >= min_price / 2:
                ranked.append((1, -moved, item))
        ranked.sort(key=lambda r: (r[0], r[1], -(r[2].avg24h or r[2].last_low or 0)))
        return [r[2] for r in ranked]

    def _download(self, items: List[Item], now: float) -> Optional[str]:
        """Download histories a few at a time; stops when a whole batch fails
        (offline, tarkov.dev down). Returns the error if any download failed."""
        if not items:
            return None
        errors: List[str] = []

        def one(item: Item):
            try:
                return weekly_average(self.history(item.id), now)
            except Exception as exc:
                log.debug("No price history for %s: %s", item.name, exc)
                return exc

        with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="PriceWatch") as pool:
            for start in range(0, len(items), WORKERS):
                batch = items[start:start + WORKERS]
                results = list(pool.map(one, batch))
                for item, avg in zip(batch, results):
                    if isinstance(avg, Exception):
                        errors.append(str(avg))
                    else:
                        self.averages[item.id] = avg
                if all(isinstance(r, Exception) for r in results):
                    break
        if errors:
            log.info("Price watch: %d price histories failed to download, e.g. %s", len(errors), errors[0])
            return f"Couldn't download some price histories from tarkov.dev: {errors[0]}"
        return None

    def _forget_old(self, now: float) -> None:
        self.averages = {k: a for k, a in self.averages.items() if now - a.fetched < AVERAGE_KEEP}
        self.alerted = {k: t for k, t in self.alerted.items() if now - t < 7 * 86400}

    @staticmethod
    def _entry(item: Item, avg: Average, kind: str, now: float) -> dict:
        return {
            "id": item.id, "name": item.name, "short": item.short_name, "icon": item.icon,
            "low": item.last_low, "avg24": item.avg24h, "avg7": round(avg.price),
            "diff": round(item.last_low / avg.price - 1, 4),
            "points": avg.points, "days": round(avg.days, 1), "offers": avg.offers, "lookedUp": avg.fetched,
            "trader": item.best_trader, "traderPrice": item.best_trader_price, "base": item.base_price,
            "change48h": item.change48h, "list": kind,
        }

    # -- in the background ----------------------------------------------

    def request(self, on_done: Callable[[dict], None], **options) -> None:
        """Check in the background. Asking while a check runs queues one more
        (merged with anything already queued), so nothing asked for is lost."""
        with self._lock:
            queued = self._queued
            if queued is not None:  # the latest settings, the bigger budget, quiet only if both were
                merged = dict(queued)
                merged.update(options)
                merged["budget"] = max(queued.get("budget", FETCHES_PER_CHECK), options.get("budget", FETCHES_PER_CHECK))
                merged["quiet"] = queued.get("quiet", False) and options.get("quiet", False)
                options = merged
            self._queued = options
            self._on_done = on_done
            if self._running:
                return
            self._running = True
        threading.Thread(target=self._run_queue, name="PriceWatch", daemon=True).start()

    @property
    def running(self) -> bool:
        """A check is running or waiting to."""
        with self._lock:
            return self._checking or self._queued is not None

    def _run_queue(self) -> None:
        while True:
            with self._lock:
                options, self._queued = self._queued, None
                if options is None:
                    self._running = False
                    return
                on_done = self._on_done
                self._checking = True
            try:
                result = self.check(**options)
            except Exception:
                log.exception("Price watch check failed")
                continue
            finally:
                with self._lock:
                    self._checking = False
            try:
                on_done(result)
            except Exception:
                log.exception("Price watch result handler failed")

    # -- saved between runs -----------------------------------------------

    def save(self) -> None:
        if not self.path:
            return
        data = {
            "averages": {k: [a.fetched, a.price, a.points, round(a.days, 2), a.offers] for k, a in self.averages.items()},
            "since": self.since, "alerted": self.alerted,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, self.path)

    def load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            for key, row in (data.get("averages") or {}).items():
                fetched, price, points, days, offers = row
                self.averages[str(key)] = Average(float(fetched), None if price is None else float(price),
                                                  int(points), float(days), None if offers is None else int(offers))
            for kind in LISTS:
                self.since[kind] = {str(k): float(v) for k, v in ((data.get("since") or {}).get(kind) or {}).items()}
            self.alerted = {str(k): float(v) for k, v in (data.get("alerted") or {}).items()}
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            log.warning("Ignoring saved price watch: %s", exc)
            self.averages, self.since, self.alerted = {}, {k: {} for k in LISTS}, {}
