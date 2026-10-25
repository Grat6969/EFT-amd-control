"""Price watch: items far below or above their weekly average price."""

import threading
import time

import pytest

from tarkov_display import pricewatch
from tarkov_display.pricewatch import (ALERT_AGAIN_AFTER, AVERAGE_MAX_AGE, LISTED_MAX_AGE, WORKERS, Average,
                                       PriceWatch, classify, signal, weekly_average)
from tarkov_display.prices import Item

NOW = 1_800_000_000.0
DAY = 86400


def item(id, low, avg24=None, change=None, **extra):
    return Item(id=id, name=id.title(), short_name=id.upper(), last_low=low, avg24h=avg24, change48h=change, **extra)


def history(avg, days=7, per_day=4, now=NOW, offers=40, low_ratio=0.9):
    """Points around an average offer price ``avg`` (a number, or a function
    of days ago) over ``days`` days; the lowest offer is ``low_ratio`` of it."""
    points = []
    for k in range(int(days * per_day)):
        ago = k / per_day
        price = avg(ago) if callable(avg) else avg
        points.append({"price": price, "priceMin": int(price * low_ratio), "offerCount": offers,
                       "timestamp": str(int((now - ago * DAY - 60) * 1000))})
    return points[::-1]


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


class Histories:
    """Stands in for tarkov.dev's price history files: by item, the usual
    average offer price, or (price, usual number of offers), or an error."""

    def __init__(self, averages, clock):
        self.averages = dict(averages)
        self.clock = clock
        self.calls = []

    def __call__(self, item_id):
        self.calls.append(item_id)
        avg = self.averages[item_id]
        if isinstance(avg, Exception):
            raise avg
        price, offers = avg if isinstance(avg, tuple) else (avg, 40)
        return history(price, now=self.clock(), offers=offers)


def watch_for(items, averages, path=None, offers=None):
    clock = Clock()
    shown = list(items)
    hist = Histories(averages, clock)
    w = PriceWatch(lambda: shown, hist, path, clock, offers=lambda: dict(offers or {}))
    return w, shown, hist, clock


# Usual lowest offer = 90% of the usual average offer (see history()).
ITEMS = [
    item("gpu", 180_000, 210_000, -45),          # crashed: 56% under its usual lowest (405k)
    item("ledx", 1_700_000, 1_650_000, 60),      # rising: lowest +89%, 24h average +65%
    item("salewa", 9_000, 19_000, -2),           # one cheap offer, 47% under: close but not 50%
    item("bolts", 20_000, 21_000, 1),            # steady: not worth looking up
    item("redcard", 900_000, 1_000_000, -60, flea_banned=True),
    item("m4preset", 30_000, 70_000, -50, is_preset=True),
    item("junk", 2_000, 3_000, -30),             # moved, but too cheap to matter
    item("thin", 20_000, 60_000, -50),           # moved a lot, but only one offer right now
    item("troll", 160_000, 15_000, 0),           # one silly offer left in a sold-out market
]
AVERAGES = {"gpu": 450_000, "ledx": 1_000_000, "salewa": 19_000, "bolts": 21_000, "junk": 4_000, "thin": 60_000,
            "troll": (14_000, 2)}
OFFERS = {"thin": 1}


def ids(entries):
    return [e["id"] for e in entries]


# -- the weekly average ---------------------------------------------------------------------------


def test_weekly_average_counts_each_day_once():
    # A busy last day (many prices at 200k) mustn't outweigh six calm days at 100k.
    points = history(100_000, days=7, per_day=2) + history(200_000, days=1, per_day=48)
    avg = weekly_average(points, NOW)
    assert avg.price == pytest.approx((6 * 100_000 + 200_000) / 7, rel=0.01)
    assert avg.low == pytest.approx(0.9 * avg.price, rel=0.01)  # from the lowest offers
    assert avg.days == pytest.approx(7, abs=0.6) and avg.points == len(points) and avg.offers == 40


def test_weekly_average_needs_enough_history():
    assert weekly_average(history(1000, days=1, per_day=24), NOW).price is None   # one day isn't a week
    assert weekly_average(history(1000, days=7, per_day=1)[:5], NOW).low is None  # too few prices
    assert weekly_average([], NOW).price is None
    junk = [{"price": None, "timestamp": "x"}, "nonsense", {"price": -5, "timestamp": 1}]
    assert weekly_average(junk + history(1000), NOW).price == pytest.approx(1000)
    no_low = [{k: v for k, v in p.items() if k not in ("priceMin", "offerCount")} for p in history(1000)]
    avg = weekly_average(no_low, NOW)
    assert avg.low == pytest.approx(1000) and avg.offers is None  # lowest offer unknown: the average stands in
    counts = history(1000, offers=30)[:20] + history(1000, offers=1)[20:]  # sold out lately
    assert weekly_average(counts, NOW).offers == 30  # the usual number, not the latest


def test_classify():
    usual = Average(NOW, low=100, price=110, points=30, days=7, offers=20)
    assert classify(item("a", 50, 100), usual, 0.5) == ("cheap", -0.5)
    assert classify(item("a", 51, 100), usual, 0.5) is None
    assert classify(item("a", 160, 170), usual, 0.5) == ("high", pytest.approx(170 / 110 - 1))
    assert classify(item("a", 160, 120), usual, 0.5) is None   # only the lowest offer is up
    assert classify(item("a", 155, 200), usual, 0.5) == ("high", pytest.approx(0.55))  # the smaller rise
    assert classify(item("a", 70, 100), usual, 0.3) == ("cheap", pytest.approx(-0.3))
    thin = Average(NOW, low=100, price=110, points=30, days=7, offers=2)
    assert classify(item("a", 20, 100), thin, 0.5) is None     # no real market price
    assert classify(item("a", 20, 100), Average(NOW, None, None), 0.5) is None


def test_signal():
    assert signal(item("a", 55, 100), 0.5) == pytest.approx(1.0)        # lowest 45% under the 24h average
    assert signal(item("a", 100, 100, -20), 0.5) == pytest.approx(1.0)  # down 20% in 48h
    assert signal(item("a", 100, 100, 20), 0.5) == pytest.approx(1.0)   # up 20% in 48h
    assert signal(item("a", 100, 100, 10), 0.5) == pytest.approx(0.5)
    assert signal(item("a", 200, 100), 0.5) == 0  # a lowest offer over the 24h average says nothing
    assert signal(item("a", 100), 0.5) == 0


# -- the lists --------------------------------------------------------------------------------------


def test_cheap_now_and_selling_high():
    w, _, hist, _ = watch_for(ITEMS, AVERAGES, offers=OFFERS)
    result = w.check(threshold=0.5, min_price=10_000)
    assert ids(result["cheap"]) == ["gpu"] and ids(result["high"]) == ["ledx"]
    gpu = result["cheap"][0]
    assert gpu["avg7"] == 405_000 and gpu["avg7All"] == 450_000 and gpu["low"] == 180_000
    assert gpu["diff"] == pytest.approx(-0.5556, abs=1e-3) and gpu["diff"] == gpu["lowDiff"]
    assert gpu["avg24"] == 210_000 and gpu["days"] >= 6 and gpu["offers"] == 40 and gpu["list"] == "cheap"
    ledx = result["high"][0]
    assert ledx["diff"] == pytest.approx(0.65) and ledx["lowDiff"] == pytest.approx(0.8889, abs=1e-3)
    # Looked up: items whose price list entry shows a big move, sold on the flea,
    # possibly worth 10k, with offers right now. Not the troll (its lowest offer
    # being over the 24h average isn't a move worth a look) nor the thin market.
    assert sorted(hist.calls) == ["gpu", "ledx", "salewa"]
    assert result["compared"] == 3 and result["waiting"] == 0 and result["error"] is None


def test_thin_markets_are_left_out():
    # Without offer counts (say, the item file is unavailable) the thin market
    # and the troll get looked up, but their history shows too few offers.
    items = ITEMS + [item("dry", 20_000, 60_000, -50)]
    w, _, hist, _ = watch_for(items, dict(AVERAGES, dry=(60_000, 1)))
    result = w.check(threshold=0.5, min_price=10_000)
    assert "thin" in hist.calls and "dry" in hist.calls
    assert ids(result["cheap"]) == ["thin", "gpu"]  # thin's history is fine: 40 offers usually
    assert "dry" not in ids(result["cheap"]) and ids(result["high"]) == ["ledx"]


def test_threshold_and_minimum_price():
    w, _, _, _ = watch_for(ITEMS, AVERAGES, offers=OFFERS)
    result = w.check(threshold=0.3, min_price=10_000)
    assert ids(result["cheap"]) == ["gpu", "salewa"]   # biggest discount first
    result = w.check(threshold=0.5, min_price=500_000)
    assert ids(result["cheap"]) == [] and ids(result["high"]) == ["ledx"]


def test_biggest_moves_are_looked_up_first():
    items = [item(f"i{k}", 40_000, 40_000, -k * 10) for k in range(1, 9)]  # down 10%..80% over 48h
    w, _, hist, _ = watch_for(items, {f"i{k}": 100_000 for k in range(1, 9)})
    result = w.check(threshold=0.5, min_price=0, budget=3)
    assert sorted(hist.calls) == ["i6", "i7", "i8"]  # i1 barely moved: not looked up at all
    assert sorted(ids(result["cheap"])) == ["i6", "i7", "i8"] and result["waiting"] == 4
    result = w.check(threshold=0.5, min_price=0, budget=3)
    assert sorted(hist.calls[3:]) == ["i3", "i4", "i5"] and result["waiting"] == 1  # the next ones, not the same again
    assert len(result["cheap"]) == 6


def test_weekly_averages_are_kept_and_reused():
    w, shown, hist, clock = watch_for(ITEMS, AVERAGES, offers=OFFERS)
    w.check()
    assert len(hist.calls) == 3
    # Items on a list are looked up again after a few hours...
    clock.now = NOW + LISTED_MAX_AGE + 1
    w.check()
    assert sorted(hist.calls[3:]) == ["gpu", "ledx"]
    # ... others whose price still moves (Salewa's cheap offer) later.
    clock.now = NOW + AVERAGE_MAX_AGE + 1
    w.check()
    assert sorted(hist.calls[5:]) == ["gpu", "ledx", "salewa"]
    # A newer price list: Salewa's lowest offer drops further. Its weekly
    # average is still known, so it joins the list without downloading anything.
    calls = len(hist.calls)
    shown[2] = item("salewa", 8_000, 18_000, -5)
    clock.now += 900
    result = w.check()
    assert ids(result["cheap"]) == ["gpu", "salewa"] and len(hist.calls) == calls


def test_new_entries_are_news_once():
    w, shown, _, clock = watch_for(ITEMS, AVERAGES, offers=OFFERS)
    assert w.check()["new"] == {"cheap": ["gpu"], "high": ["ledx"]}
    clock.now += 900
    assert w.check()["new"] == {"cheap": [], "high": []}
    first_seen = w.result["cheap"][0]["since"]
    assert first_seen == NOW
    # The GPU recovers, then drops again within a few hours: not news again so soon...
    shown[0] = item("gpu", 400_000, 410_000, -10)
    clock.now += 900
    assert ids(w.check()["cheap"]) == []
    shown[0] = item("gpu", 180_000, 210_000, -45)
    clock.now += 900
    result = w.check()
    assert ids(result["cheap"]) == ["gpu"] and result["new"]["cheap"] == []
    assert result["cheap"][0]["since"] == clock.now  # it rejoined just now
    # ... but it is after a while.
    shown[0] = item("gpu", 400_000, 410_000, -10)
    clock.now += 900
    w.check()
    shown[0] = item("gpu", 180_000, 210_000, -45)
    clock.now = NOW + ALERT_AGAIN_AFTER + 3600
    assert w.check()["new"]["cheap"] == ["gpu"]


def test_quiet_checks_say_nothing():
    w, _, _, _ = watch_for(ITEMS, AVERAGES, offers=OFFERS)
    result = w.check(threshold=0.3, quiet=True)  # say, right after you changed the threshold
    assert ids(result["cheap"]) == ["gpu", "salewa"] and result["new"] == {"cheap": [], "high": []}
    assert w.check(threshold=0.3)["new"] == {"cheap": [], "high": []}  # already shown


def test_failed_downloads_and_offer_counts_are_reported_not_fatal():
    items = [item(f"i{k}", 40_000, 100_000, -60) for k in range(12)]
    w, _, hist, _ = watch_for(items, {f"i{k}": RuntimeError("HTTP 404") for k in range(12)})
    result = w.check(min_price=0)
    assert len(hist.calls) == WORKERS  # a whole batch failed: probably offline, stop there
    assert "HTTP 404" in result["error"] and result["cheap"] == []
    averages = {f"i{k}": 100_000 for k in range(12)}
    averages["i3"] = RuntimeError("HTTP 500")
    w, _, hist, _ = watch_for(items, averages)
    w.offers = lambda: 1 / 0  # the item file failed: every item that moved counts
    result = w.check(min_price=0)
    assert len(hist.calls) == 12 and len(result["cheap"]) == 11 and "HTTP 500" in result["error"]


def test_kept_between_runs(tmp_path):
    path = tmp_path / "pricewatch_regular.json"
    w, _, hist, _ = watch_for(ITEMS, AVERAGES, path, OFFERS)
    w.check()
    again, _, hist2, clock = watch_for(ITEMS, AVERAGES, path, OFFERS)
    clock.now += 900
    result = again.check()
    assert hist2.calls == [] and ids(result["cheap"]) == ["gpu"]  # nothing downloaded again
    assert result["new"] == {"cheap": [], "high": []} and result["cheap"][0]["since"] == NOW


def test_a_damaged_save_is_ignored(tmp_path):
    path = tmp_path / "pricewatch_regular.json"
    for junk in ("{not json", '{"averages": {"gpu": [1, 2]}}', '["a list"]', '{"since": {"cheap": 5}}'):
        path.write_text(junk, encoding="utf-8")
        w, _, _, _ = watch_for(ITEMS, AVERAGES, path, OFFERS)
        assert w.averages == {} and w.since == {"cheap": {}, "high": {}}
        assert ids(w.check()["cheap"]) == ["gpu"]


def test_background_checks_queue_up():
    gate = threading.Event()
    w, _, hist, _ = watch_for(ITEMS, AVERAGES, offers=OFFERS)
    real = w.history

    def slow(item_id):
        gate.wait(5)
        return real(item_id)

    w.history = slow
    results = []
    done = threading.Event()

    def got(result):
        results.append(result)
        if len(results) == 2:
            done.set()

    w.request(got, threshold=0.5, min_price=10_000)
    assert w.running
    w.request(got, threshold=0.3, min_price=10_000, quiet=True)   # while the first runs: queued
    w.request(got, threshold=0.3, min_price=10_000, budget=100)   # merged into the queued one
    gate.set()
    assert done.wait(5)
    assert ids(results[0]["cheap"]) == ["gpu"] and ids(results[1]["cheap"]) == ["gpu", "salewa"]
    assert results[1]["threshold"] == 0.3
    for _ in range(50):
        if not w.running:
            break
        time.sleep(0.02)
    assert not w.running and len(results) == 2


def test_background_check_survives_errors(monkeypatch):
    w, _, _, _ = watch_for(ITEMS, AVERAGES)
    done = threading.Event()
    calls = []

    def broken(**options):
        calls.append(options)
        if len(calls) == 1:
            raise RuntimeError("boom")
        done.set()
        return {"cheap": []}

    monkeypatch.setattr(w, "check", broken)
    w.request(lambda r: None)
    for _ in range(50):
        if not w.running:
            break
        time.sleep(0.02)
    w.request(lambda r: None)
    assert done.wait(5) and len(calls) == 2


def test_module_constants_make_sense():
    assert pricewatch.LISTED_MAX_AGE < pricewatch.AVERAGE_MAX_AGE < pricewatch.AVERAGE_KEEP
    assert pricewatch.FETCHES_PER_CHECK <= pricewatch.FETCHES_NOW
    assert pricewatch.MIN_OFFERS_NOW <= pricewatch.MIN_OFFERS


# -- in the app (demo data: see DEALS in tests/demo.py) ---------------------------------------------


def wait_for(fn, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("timed out")


def shorts(entries):
    return sorted(e["short"] for e in entries)


def test_price_watch_api(webapp):
    from test_server import body, call

    s = webapp.server
    assert body(call(s, "/api/bootstrap"))["pricewatch"]["settings"] == {"enabled": True, "threshold": 0.5,
                                                                         "minPrice": 10000}
    first = body(call(s, "/api/pricewatch"))  # starts a check: the prices are new to it
    state = wait_for(lambda: (lambda w: w if w["checked"] and not w["running"] else None)(body(call(s, "/api/pricewatch"))))
    assert state["version"] > first["version"]
    assert shorts(state["cheap"]) == ["GPU", "KIBA", "Moonshine"] and shorts(state["high"]) == ["0.2BTC", "Tetriz"]
    gpu = next(e for e in state["cheap"] if e["short"] == "GPU")
    assert gpu["low"] == 180000 and 370000 < gpu["avg7"] < 420000 and gpu["avg24"] == 260000

    def settle(change):
        body(call(s, "/api/pricewatch", "POST", change))
        return wait_for(lambda: (lambda w: w if not w["running"] else None)(body(call(s, "/api/pricewatch"))))

    state = settle({"threshold": 0.3})
    assert state["settings"]["threshold"] == 0.3 and "Salewa" in shorts(state["cheap"])
    state = settle({"threshold": 0.5, "minPrice": 200000})
    assert shorts(state["cheap"]) == ["GPU"] and shorts(state["high"]) == ["0.2BTC"]
    assert body(call(s, "/api/pricewatch", "POST", {"threshold": 5}))["settings"]["threshold"] == 0.9  # kept in range
    assert call(s, "/api/pricewatch", "POST", {"threshold": "lots"})[0] == 400
    assert call(s, "/api/pricewatch", "POST", ["not", "settings"])[0] == 400
    state = settle({"enabled": False, "threshold": 0.5, "minPrice": 10000})
    assert state["settings"]["enabled"] is False and webapp.app.config.watch.enabled is False
    saved = (webapp.cfg_dir / "config.json").read_text(encoding="utf-8")
    assert '"watch"' in saved and '"enabled": false' in saved
    assert body(call(s, "/api/pricewatch/check", "POST", {}))["settings"]["enabled"] is False


def test_announces_new_deals_after_price_updates(webapp, monkeypatch):
    from tarkov_display import webapp as webapp_mod
    from tests import demo

    events = []
    monkeypatch.setattr(webapp, "publish", lambda event, data: events.append((event, data)))
    news = lambda: [d["new"] for e, d in events if e == "pricewatch"]  # noqa: E731
    webapp._watch_after_update()  # what the app does after every price update
    first = wait_for(news)[0]
    assert sorted(first["cheap"]) == sorted(demo.BY_SHORT[k]["uid"] for k in ("GPU", "KIBA", "Moonshine"))
    assert sorted(first["high"]) == sorted(demo.BY_SHORT[k]["uid"] for k in ("0.2BTC", "Tetriz"))
    webapp._watch_after_update()  # the same price list: nothing to do
    time.sleep(0.3)
    assert len(news()) == 1

    # The next price list: one more item crashes.
    monkeypatch.setitem(demo.BY_SHORT["Intelligence"], "price", 90000)
    monkeypatch.setitem(demo.BY_SHORT["Intelligence"], "avg24hPrice", 220000)
    assert webapp.app.prices.refresh()
    webapp._watch_after_update()
    second = wait_for(lambda: news()[1:])[0]
    assert second == {"cheap": [demo.BY_SHORT["Intelligence"]["uid"]], "high": []}

    # Off, or an old price list from last time: no background checks.
    webapp.app.prices.updated += 1
    webapp.app.config.watch.enabled = False
    webapp._watch_after_update()
    webapp.app.config.watch.enabled = True
    webapp.app.prices.updated = time.time() - webapp_mod.WATCH_FRESH - 60
    webapp._watch_after_update()
    time.sleep(0.3)
    assert len(news()) == 2


def test_a_check_from_before_a_game_mode_switch_is_dropped(webapp, monkeypatch):
    events = []
    monkeypatch.setattr(webapp, "publish", lambda event, data: events.append(event))
    gate = threading.Event()
    old = webapp.watch
    real = old.history
    old.history = lambda item_id: gate.wait(5) and real(item_id)
    webapp._watch_now(quiet=False)
    webapp.set_game_mode("pve")
    try:
        assert webapp.watch is not old and webapp.watch.path.name == "pricewatch_pve.json"
        gate.set()
        wait_for(lambda: not old.running)
        assert "pricewatch" not in events  # PvP results mustn't show up as PvE's
    finally:
        webapp.app.prices.stop()
