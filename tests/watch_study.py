"""One-off study of the price watch's rules on tarkov.dev's live data.

    python -m tests.watch_study [--sample N]

For a random sample of items it downloads the price history and prints how
each candidate rule (what the price list alone can tell) would have picked
the items that really are far from their weekly level, so the rules can be
tuned on real prices instead of guesses.
"""

from __future__ import annotations

import argparse
import random
import statistics
from collections import Counter

from tarkov_display import pricewatch, staticapi
from tarkov_display.client import TarkovClient
from tarkov_display.prices import PriceDB


def mean_by_day(points, key):
    import time
    now = time.time()
    days = {}
    for p in points:
        v, ts = pricewatch._number(p.get(key)), pricewatch._number(p.get("timestamp"))
        if v > 0 and ts > 0:
            days.setdefault(int((now * 1000 - ts) // 86400e3), []).append(v)
    if len(days) < 2:
        return None
    return sum(sum(v) / len(v) for v in days.values()) / len(days)


def study(mode: str, sample: int) -> None:
    client = TarkovClient(mode)
    db = PriceDB(cache_path=None, game_mode=mode)
    items = db.fetch_items()
    eligible = [i for i in items if pricewatch.eligible(i) and i.avg24h and pricewatch.typical_price(i) >= 5000]
    print(f"\n== {mode}: {len(items)} items, {len(eligible)} sold on the flea and worth 5k+ ==")

    # What the price list alone says, for every eligible item (no downloads).
    gaps = [i.last_low / i.avg24h - 1 for i in eligible]
    changes = [i.change48h for i in eligible if i.change48h is not None]
    print("  lowest offer vs 24h avg: median %+.0f%%, quartiles %+.0f%% / %+.0f%%" % (
        100 * statistics.median(gaps), 100 * statistics.quantiles(gaps, n=4)[0], 100 * statistics.quantiles(gaps, n=4)[2]))
    for cut in (-0.25, -0.4, -0.5, -0.6):
        print(f"    lowest {cut:+.0%} or more under 24h avg: {sum(g <= cut for g in gaps)}")
    for cut in (0.25, 0.5, 1.0):
        print(f"    lowest {cut:+.0%} or more over 24h avg: {sum(g >= cut for g in gaps)}")
    for cut in (15, 25, 40):
        print(f"    48h change <= -{cut}%: {sum(c <= -cut for c in changes)}   >= +{cut}%: {sum(c >= cut for c in changes)}")
    offers = Counter()

    rng = random.Random(7)
    picked = rng.sample(eligible, min(sample, len(eligible)))
    # ... plus every item with a strong signal, so rare real cases show up.
    strong = [i for i in eligible if abs(i.last_low / i.avg24h - 1) >= 0.5 or abs(i.change48h or 0) >= 30]
    picked += [i for i in rng.sample(strong, min(sample, len(strong))) if i not in picked]
    rows = []
    for it in picked:
        try:
            points = staticapi.price_history(client, it.id)
        except Exception as exc:
            print("   history failed:", it.name, exc)
            continue
        low7, avg7 = mean_by_day(points, "priceMin"), mean_by_day(points, "price")
        if not low7 or not avg7:
            continue
        last = points[-1]
        n = int(pricewatch._number(last.get("offerCount")))
        offers[min(n, 10)] += 1
        rows.append((it, low7, avg7, n))
    print(f"  looked up {len(rows)} histories ({len(picked)} picked)")
    print("  usual lowest vs usual average (7 days): median %+.0f%%" % (100 * statistics.median(l / a - 1 for _, l, a, _ in rows)))
    print("  offers at the latest point (10 = 10+):", dict(sorted(offers.items())))

    def report(title, hits, rule_sets):
        print(f"  {title}: {len(hits)} in the sample")
        for it, low7, avg7, n in hits[:12]:
            print(f"    {it.name[:38]:38} low {it.last_low:>9} usual low {low7:>11.0f} ({it.last_low / low7 - 1:+.0%}) "
                  f"24h {it.avg24h:>9} usual avg {avg7:>11.0f} ({it.avg24h / avg7 - 1:+.0%}) offers {n:>3} "
                  f"gap {it.last_low / it.avg24h - 1:+.0%} 48h {it.change48h if it.change48h is None else round(it.change48h)}")
        for name, rule in rule_sets:
            caught = sum(1 for r in hits if rule(r[0]))
            fired = sum(1 for i in eligible if rule(i))
            print(f"    rule {name:44} catches {caught}/{len(hits)}, fires for {fired} of {len(eligible)}")

    t = 0.5
    cheap = [r for r in rows if r[0].last_low <= (1 - t) * r[1]]
    cheap_vs_avg = [r for r in rows if r[0].last_low <= (1 - t) * r[2]]
    high_low = [r for r in rows if r[0].last_low >= (1 + t) * r[1]]
    high = [r for r in high_low if r[0].avg24h >= (1 + t) * r[2]]
    high_liquid = [r for r in high if r[3] >= 3]

    def gap(i):
        return i.last_low / i.avg24h - 1

    cheap_rules = [
        ("gap <= -25% or 48h <= -25%", lambda i: gap(i) <= -0.25 or (i.change48h or 0) <= -25),
        ("gap <= -40% or 48h <= -25%", lambda i: gap(i) <= -0.4 or (i.change48h or 0) <= -25),
        ("gap <= -50% or 48h <= -25%", lambda i: gap(i) <= -0.5 or (i.change48h or 0) <= -25),
        ("gap <= -40% or 48h <= -15%", lambda i: gap(i) <= -0.4 or (i.change48h or 0) <= -15),
        ("gap <= -50%", lambda i: gap(i) <= -0.5),
        ("48h <= -25%", lambda i: (i.change48h or 0) <= -25),
    ]
    high_rules = [
        ("48h >= +25%", lambda i: (i.change48h or 0) >= 25),
        ("48h >= +15%", lambda i: (i.change48h or 0) >= 15),
        ("48h >= +25% or gap >= +50%", lambda i: (i.change48h or 0) >= 25 or gap(i) >= 0.5),
        ("old rule: |gap| or |48h| >= 25%", lambda i: abs(gap(i)) >= 0.25 or abs(i.change48h or 0) >= 25),
    ]
    report("cheap: lowest 50%+ under its usual lowest", cheap, cheap_rules)
    report("cheap by the old measure (lowest vs usual AVERAGE)", cheap_vs_avg, cheap_rules[:1])
    report("high: lowest 50%+ over its usual lowest", high_low, high_rules[-1:])
    report("high: ... and 24h avg 50%+ over its usual average", high, high_rules)
    report("high: ... and 3+ offers", high_liquid, high_rules)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=250)
    args = parser.parse_args()
    for mode in ("regular", "pve"):
        study(mode, args.sample)


if __name__ == "__main__":
    main()
