"""Price watch: items whose flea price is far from their weekly average.

Two lists, rebuilt after every price update:

- cheap now: the lowest offer is at least ``threshold`` below the item's
  usual lowest offer, its average over the last 7 days (worth buying)
- selling high: the lowest offer and the 24 hour average are both at least
  ``threshold`` above their 7-day averages (worth selling)

Lowest offer is compared with lowest offer: on tarkov.dev it usually sits
13-18% under the average offer price, which would make every item look
cheap. Items usually listed fewer than MIN_OFFERS times are left out: in
such thin markets the "price" is one person's listing, often a silly one
(1 000 000 for a pistol grip nobody else sells), and a third of all items
are like that. "Selling high" also needs the 24h average up, so one
overpriced offer left in a sold-out market doesn't count.

The price list (prices.py) has every item's lowest offer and 24h average,
but no weekly average: that takes the item's price history, one download
per item from tarkov.dev's data files (what its price chart uses).
Downloading thousands every 15 minutes would be rude, so:

- Only items whose price list entry shows a big move are looked up: a
  lowest offer far under the 24h average, or a big change over 48 hours
  (thresholds measured on tarkov.dev's live data). Items with fewer than
  MIN_OFFERS_NOW offers right now are skipped too. A move older than a
  couple of days has mostly worked its way into the weekly average anyway:
  an item that dropped 50% four days ago is now only about 30% below it.
- A weekly average changes slowly, so each one is kept for hours (on disk
  too) and compared with the latest prices at every price update.
- A check downloads a few dozen histories at most, the most roubles at
  stake first (how big the move is times what the item is worth); the
  rest wait for the next check.
"""

from __future__ import annotations

import json
import logging
import os
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .prices import Item

log = logging.getLogger(__name__)

LISTS = ("cheap", "high")
LISTED_MAX_AGE = 6 * 3600      # look up an item on a list again after this long...
AVERAGE_MAX_AGE = 24 * 3600    # ... and any other item whose price still moves after this long
AVERAGE_KEEP = 36 * 3600       # forget a weekly average older than this
FETCHES_PER_CHECK = 40         # price histories downloaded per check after a price update...
FETCHES_NOW = 120              # ... per check you asked for...
FETCHES_FIRST = 100            # ... and at least this many when nothing is known yet
WORKERS = 4                    # downloads at a time
MIN_POINTS = 12                # a weekly average needs this many prices...
MIN_DAYS = 2.0                 # ... spread over at least this many days
MIN_OFFERS = 3                 # usually listed fewer times than this: no real market price
MIN_OFFERS_NOW = 3             # not even looked up with fewer offers than this right now
# A big move in the price list, as a share of the threshold (0.5 = 50%): the
# lowest offer this far under the 24h average, or a 48h change this big.
CHEAP_GAP = 0.9                # 45% under, for a 50% threshold
CHEAP_CHANGE = 0.4             # down 20% over 48h
HIGH_CHANGE = 0.4              # up 20% over 48h
ALERT_AGAIN_AFTER = 6 * 3600   # an item back on a list it left is news again after this long
MAX_ENTRIES = 200              # per list


@dataclass
class Average:
    """An item's prices over the last 7 days, from its history. ``low`` and
    ``price`` are None when there isn't enough history to say."""

    fetched: float           # when the history was downloaded
    low: Optional[float]     # average of the lowest offer
    price: Optional[float]   # average of the average offer (what the 24h average is made of)
    points: int = 0
    days: float = 0.0        # how many days the history covers
    offers: Optional[int] = None  # how many offers there usually are (median)


def _number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _daily_mean(rows: List[Tuple[float, float]], now: float) -> float:
    """The average of each day's average. Days count equally however many
    prices were recorded on each, so a busy day doesn't outweigh the rest."""
    by_day: Dict[int, List[float]] = {}
    for ts, value in rows:
        by_day.setdefault(int((now * 1000 - ts) // 86400e3), []).append(value)
    return sum(sum(v) / len(v) for v in by_day.values()) / len(by_day)


def weekly_average(points: Sequence[dict], now: Optional[float] = None) -> Average:
    """An item's 7-day averages from its price history points."""
    now = time.time() if now is None else now
    prices, lows, counts = [], [], []
    for p in points:
        if not isinstance(p, dict):
            continue
        ts, price = _number(p.get("timestamp")), _number(p.get("price"))
        if ts <= 0 or price <= 0:
            continue
        prices.append((ts, price))
        lows.append((ts, _number(p.get("priceMin")) or price))
        if p.get("offerCount") is not None:
            counts.append(_number(p.get("offerCount")))
    offers = int(statistics.median(counts)) if counts else None
    if len(prices) < MIN_POINTS:
        return Average(now, None, None, len(prices), offers=offers)
    days = (max(ts for ts, _ in prices) - min(ts for ts, _ in prices)) / 86400e3
    if days < MIN_DAYS:
        return Average(now, None, None, len(prices), days, offers)
    return Average(now, _daily_mean(lows, now), _daily_mean(prices, now), len(prices), days, offers)


def eligible(item: Item) -> bool:
    """Sold on the flea right now, and not a weapon preset (priced from its parts)."""
    return bool(item.last_low) and item.last_low > 0 and not item.flea_banned and not item.is_preset


def signal(item: Item, threshold: float) -> float:
    """How big a move the price list shows, compared with what's worth a
    look (see CHEAP_GAP...): 1 or more is a big move, 0 is none."""
    moves = [0.0]
    if item.avg24h and item.last_low:
        moves.append((1 - item.last_low / item.avg24h) / (CHEAP_GAP * threshold))
    if item.change48h is not None:
        change = item.change48h / 100
        moves.append(-change / (CHEAP_CHANGE * threshold))
        moves.append(change / (HIGH_CHANGE * threshold))
    return max(moves)


def typical_price(item: Item) -> float:
    """Roughly what the item went for lately: the most of its lowest offer,
    24h average, and 24h average two days ago."""
    prices = [item.last_low or 0, item.avg24h or 0]
    if item.avg24h and item.change48h is not None and item.change48h > -100:
        prices.append(item.avg24h / (1 + item.change48h / 100))
    return max(prices)


def classify(item: Item, avg: Average, threshold: float) -> Optional[Tuple[str, float]]:
    """("cheap" or "high", how far from usual) for an item far from its
    7-day level, or None. For "high", the smaller of the lowest offer's and
    the 24h average's rise."""
    if not avg.low or not avg.price or not item.last_low:
        return None
    if avg.offers is not None and avg.offers < MIN_OFFERS:
        return None
    low = item.last_low / avg.low - 1
    if low <= -threshold + 1e-9:
        return "cheap", low
    if low >= threshold - 1e-9 and item.avg24h:
        rise = min(low, item.avg24h / avg.price - 1)
        if rise >= threshold - 1e-9:
            return "high", rise
    return None


class PriceWatch:
    """The two lists for one game mode. ``items`` returns the current price
    list; ``history`` downloads one item's price history (see
    staticapi.price_history)."""

    def __init__(self, items: Callable[[], List[Item]], history: Callable[[str], List[dict]],
                 path: Optional[Path] = None, clock: Callable[[], float] = time.time,
                 offers: Callable[[], Dict[str, int]] = dict) -> None:
        self.items = items
        self.history = history
        self.offers = offers  # item id -> offers on the flea right now (where known)
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
            try:
                offers = self.offers() or {}
            except Exception as exc:  # then every item that moved counts
                log.debug("Price watch: no offer counts: %s", exc)
                offers = {}
            wanted = self._wanted(items, threshold, min_price, now, offers)
            if not self.averages:
                budget = max(budget, FETCHES_FIRST)
            error = self._download(wanted[:max(0, budget)], now)

            lists: Dict[str, List[dict]] = {k: [] for k in LISTS}
            compared = 0
            for item in items:
                avg = self.averages.get(item.id)
                if not avg or not avg.low or avg.low < min_price:
                    continue
                if avg.offers is None or avg.offers >= MIN_OFFERS:
                    compared += 1
                found = classify(item, avg, threshold)
                if found:
                    lists[found[0]].append(self._entry(item, avg, found[0], found[1]))
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

    def _wanted(self, items: List[Item], threshold: float, min_price: int, now: float,
                offers: Dict[str, int]) -> List[Item]:
        """Items whose history should be looked up, most important first:
        those on a list (to keep it right), then the most roubles at stake."""
        listed = set(self.since["cheap"]) | set(self.since["high"])
        ranked = []
        for item in items:
            avg = self.averages.get(item.id)
            age = now - avg.fetched if avg is not None else float("inf")
            moved, worth = signal(item, threshold), typical_price(item)
            stake = min(moved, 3) * worth
            if item.id in listed:
                if age >= LISTED_MAX_AGE:
                    ranked.append((0, -stake, item))
            elif (age >= AVERAGE_MAX_AGE and moved >= 1 and worth >= min_price / 2
                  and offers.get(item.id, MIN_OFFERS_NOW) >= MIN_OFFERS_NOW):
                ranked.append((1, -stake, item))
        ranked.sort(key=lambda r: (r[0], r[1]))
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
    def _entry(item: Item, avg: Average, kind: str, diff: float) -> dict:
        return {
            "id": item.id, "name": item.name, "short": item.short_name, "icon": item.icon,
            "low": item.last_low, "avg24": item.avg24h,
            "avg7": round(avg.low), "avg7All": round(avg.price),  # lowest offer's / average offer's
            "diff": round(diff, 4), "lowDiff": round(item.last_low / avg.low - 1, 4),
            "avgDiff": round(item.avg24h / avg.price - 1, 4) if item.avg24h else None,
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
            "averages": {k: [a.fetched, a.low, a.price, a.points, round(a.days, 2), a.offers]
                         for k, a in self.averages.items()},
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
            def number(v):
                return None if v is None else float(v)

            for key, row in (data.get("averages") or {}).items():
                fetched, low, price, points, days, offers = row
                self.averages[str(key)] = Average(float(fetched), number(low), number(price), int(points), float(days),
                                                  None if offers is None else int(offers))
            for kind in LISTS:
                self.since[kind] = {str(k): float(v) for k, v in ((data.get("since") or {}).get(kind) or {}).items()}
            self.alerted = {str(k): float(v) for k, v in (data.get("alerted") or {}).items()}
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            log.warning("Ignoring saved price watch: %s", exc)
            self.averages, self.since, self.alerted = {}, {k: {} for k in LISTS}, {}
