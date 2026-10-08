"""Made-up but realistic tarkov.dev data, for testing the app window
without internet access. Not used by the real app.

    python -m tests.demo            # serve the app with demo data on port 47999
"""

from __future__ import annotations

import base64
import random
import re
import time
from datetime import datetime, timedelta, timezone

from tarkov_display.prices import EUR_ID, USD_ID

rnd = random.Random(7)


def svg_icon(text: str, hue: int, w: int = 64, h: int = 64) -> str:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
        f'<rect width="{w}" height="{h}" fill="hsl({hue},22%,22%)"/>'
        f'<rect x="6" y="6" width="{w - 12}" height="{h - 12}" rx="6" fill="hsl({hue},30%,34%)"/>'
        f'<text x="{w / 2}" y="{h / 2 + 5}" font-family="Arial" font-size="13" font-weight="bold" '
        f'fill="#f2ead6" text-anchor="middle">{text[:6]}</text></svg>'
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def oid(n: int) -> str:
    return f"{n:024x}"


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


NOW = datetime.now(timezone.utc)

TRADER_NAMES = ["Prapor", "Therapist", "Fence", "Skier", "Peacekeeper", "Mechanic", "Ragman", "Jaeger", "Ref"]
TRADERS = []
for i, name in enumerate(TRADER_NAMES):
    TRADERS.append({
        "id": oid(1000 + i), "name": name, "normalizedName": name.lower(), "description": f"{name} trades goods.",
        "resetTime": iso(NOW + timedelta(minutes=7 + i * 23)), "imageLink": svg_icon(name[:2], i * 40),
        "image4xLink": svg_icon(name[:2], i * 40), "currency": {"id": USD_ID if name == "Peacekeeper" else oid(1),
                                                                "name": "Dollars" if name == "Peacekeeper" else "Roubles",
                                                                "shortName": "USD" if name == "Peacekeeper" else "RUB"},
        "levels": [{"id": oid(1100 + i * 10 + l), "level": l, "requiredPlayerLevel": [1, 15, 26, 36][l - 1],
                    "requiredReputation": [0, 0.2, 0.35, 0.5][l - 1], "requiredCommerce": [0, 400000, 800000, 1500000][l - 1],
                    "payRate": 0.5, "insuranceRate": 0.2, "repairCostMultiplier": 1} for l in range(1, 5)],
    })
T = {t["name"]: t for t in TRADERS}

# (name, short, tags, slots, size, base, flea avg, trader, trader price)
ITEM_ROWS = [
    ("LEDX Skin Transilluminator", "LEDX", ["barter"], 1, "1x1", 450000, 1020000, "Therapist", 652000),
    ("Graphics card", "GPU", ["barter"], 2, "2x1", 120000, 452000, "Mechanic", 186000),
    ("Physical Bitcoin", "0.2BTC", ["barter"], 1, "1x1", 160000, 498000, "Therapist", 228000),
    ("Tetriz portable game console", "Tetriz", ["barter"], 2, "1x2", 26000, 41000, "Mechanic", 18200),
    ("Salewa first aid kit", "Salewa", ["meds"], 2, "1x2", 12000, 19800, "Therapist", 9800),
    ("IFAK individual first aid kit", "IFAK", ["meds"], 1, "1x1", 9000, 15200, "Therapist", 7400),
    ("Grizzly medical kit", "Grizzly", ["meds"], 4, "2x2", 24000, 33500, "Therapist", 17000),
    ("Propital regenerative stimulant injector", "Propital", ["meds", "injectors"], 1, "1x1", 22000, 41000, "Therapist", 13200),
    ("Bottle of water (0.6L)", "Water", ["provisions"], 2, "1x2", 3000, 9400, "Therapist", 2100),
    ("Can of beef stew (Large)", "Tushonka", ["provisions"], 2, "1x2", 4100, 17500, "Therapist", 3000),
    ("Bottle of Fierce Hatchling moonshine", "Moonshine", ["barter", "provisions"], 2, "1x2", 18000, 172000, "Therapist", 11000),
    ("Intelligence folder", "Intelligence", ["barter"], 2, "2x1", 34000, 228000, "Therapist", 25500),
    ("Military power filter", "MPF", ["barter"], 2, "1x2", 14000, 41000, "Mechanic", 9800),
    ("Electric drill", "Drill", ["barter"], 4, "2x2", 8000, 21000, "Mechanic", 5600),
    ("Toolset", "Toolset", ["barter"], 4, "2x2", 13000, 32000, "Mechanic", 9100),
    ("Gas analyzer", "GasAn", ["barter"], 2, "1x2", 5000, 18500, "Therapist", 3500),
    ("Wires", "Wires", ["barter"], 1, "1x1", 3500, 14800, "Mechanic", 2400),
    ("Bolts", "Bolts", ["barter"], 1, "1x1", 4000, 23500, "Mechanic", 2800),
    ("Duct tape", "Tape", ["barter"], 1, "1x1", 2500, 12100, "Mechanic", 1700),
    ("Corrugated hose", "Hose", ["barter"], 1, "1x1", 6000, 27800, "Mechanic", 4200),
    ("Power cord", "Cord", ["barter"], 1, "1x1", 7000, 34200, "Mechanic", 4900),
    ("Printed circuit board", "PCB", ["barter"], 1, "1x1", 6500, 25800, "Mechanic", 4600),
    ("CPU fan", "CPU Fan", ["barter"], 1, "1x1", 5000, 18900, "Mechanic", 3500),
    ("Hunting matches", "Matches", ["barter"], 1, "1x1", 1500, 9800, "Therapist", 1100),
    ("Pack of sugar", "Sugar", ["barter", "provisions"], 1, "1x1", 4000, 29800, "Therapist", 2800),
    ("Dorm room 314 marked key", "314", ["keys"], 1, "1x1", 140000, 3150000, "Therapist", 98000),
    ("Factory emergency exit key", "Factory", ["keys"], 1, "1x1", 2500, 18500, "Prapor", 1700),
    ("KIBA Arms outer door key", "KIBA", ["keys"], 1, "1x1", 9000, 162000, "Prapor", 6300),
    ("TerraGroup Labs keycard (Red)", "Red", ["keys", "noFlea"], 1, "1x1", 650000, None, "Therapist", 455000),
    ("Dorm room 206 key", "206", ["keys"], 1, "1x1", 4800, 41000, "Prapor", 3400),
    ("Gas station storage room key", "GS", ["keys"], 1, "1x1", 5000, 52000, "Prapor", 3500),
    ("MS2000 Marker", "MS2000", ["barter"], 1, "1x1", 3000, 14000, "Prapor", 2100),
    ("Kalashnikov AK-74N 5.45x39 assault rifle", "AK-74N", ["gun", "preset"], 8, "4x2", 22000, 58000, "Prapor", 15400),
    ("Colt M4A1 5.56x45 assault rifle", "M4A1", ["gun"], 8, "4x2", 32000, 78000, "Peacekeeper", 220),
    ("6B43 6A Zabralo-Sh body armor", "6B43", ["armor", "wearable"], 12, "3x4", 120000, 395000, "Ragman", 84000),
    ("PACA Soft Armor", "PACA", ["armor", "wearable"], 9, "3x3", 18000, 38000, "Ragman", 12600),
    ("S I C C organizational pouch", "SICC", ["container"], 4, "2x2", 900000, 1450000, "Therapist", 630000),
    ("Item case", "Items", ["container", "noFlea"], 16, "4x4", 1200000, None, "Therapist", 840000),
    ("WI-FI Camera", "WiFi Cam", ["barter"], 1, "1x1", 7000, 52000, "Mechanic", 4900),
    ("Golden rooster figurine", "Rooster", ["barter"], 4, "2x2", 44000, 128000, "Peacekeeper", 260),
    ("Silver Badge", "Badge", ["barter"], 1, "1x1", 22000, 82000, "Ragman", 64),
    ("Dollars", "USD", ["barter"], 1, "1x1", 142, 160, None, None),
    ("Euros", "EUR", ["barter"], 1, "1x1", 160, 176, None, None),
]

AMMO_ROWS = [
    # caliber, name, short, damage, pen, armor dmg, frag, speed, tracer, price
    ("Caliber545x39", "5.45x39mm PS gs", "PS", 51, 31, 52, 0.4, 890, False, 210),
    ("Caliber545x39", "5.45x39mm BT gs", "BT", 48, 37, 51, 0.16, 880, True, 340),
    ("Caliber545x39", "5.45x39mm BS gs", "BS", 45, 54, 57, 0.17, 830, False, 1400),
    ("Caliber545x39", "5.45x39mm PPBS gs \"Igolnik\"", "PPBS", 37, 62, 64, 0.02, 905, False, 2400),
    ("Caliber545x39", "5.45x39mm PRS gs", "PRS", 70, 13, 30, 0.3, 865, False, 140),
    ("Caliber545x39", "5.45x39mm 7N40", "7N40", 55, 42, 60, 0.1, 915, False, 980),
    ("Caliber556x45NATO", "5.56x45mm M855A1", "M855A1", 49, 44, 52, 0.34, 945, False, 1100),
    ("Caliber556x45NATO", "5.56x45mm M995", "M995", 42, 53, 58, 0.32, 1013, False, 1900),
    ("Caliber556x45NATO", "5.56x45mm SSA AP", "SSA AP", 38, 57, 60, 0.02, 1013, False, 2200),
    ("Caliber556x45NATO", "5.56x45mm M856A1", "M856A1", 52, 38, 52, 0.33, 940, True, 720),
    ("Caliber556x45NATO", "5.56x45mm FMJ", "FMJ", 54, 23, 33, 0.5, 957, False, 230),
    ("Caliber762x39", "7.62x39mm BP gzh", "BP", 58, 47, 63, 0.12, 730, False, 1500),
    ("Caliber762x39", "7.62x39mm PS gzh", "PS", 61, 35, 52, 0.25, 700, False, 330),
    ("Caliber762x39", "7.62x39mm MAI AP", "MAI AP", 53, 58, 76, 0.05, 875, False, 2600),
    ("Caliber762x51", "7.62x51mm M61", "M61", 70, 64, 83, 0.13, 849, False, 3100),
    ("Caliber762x51", "7.62x51mm M80", "M80", 80, 41, 66, 0.17, 833, False, 950),
    ("Caliber12g", "12/70 flechette", "Flechette", 25, 31, 26, 0.0, 320, False, 600),
    ("Caliber12g", "12/70 7mm buckshot", "7mm", 39, 3, 26, 0.0, 415, False, 90),
    ("Caliber9x19PARA", "9x19mm PBP gzh", "PBP", 52, 39, 53, 0.05, 560, False, 880),
    ("Caliber9x19PARA", "9x19mm AP 6.3", "AP 6.3", 52, 30, 48, 0.05, 392, False, 600),
]

ITEMS = []
for i, (name, short, tags, slots, size, base, avg, trader, tprice) in enumerate(ITEM_ROWS):
    uid = USD_ID if name == "Dollars" else EUR_ID if name == "Euros" else oid(2000 + i)
    cur = "$" if trader in ("Peacekeeper",) else "€" if trader == "Ragman" and name == "Silver Badge" else "₽"
    ITEMS.append({
        "uid": uid, "name": name, "shortName": short, "tags": tags, "basePrice": base,
        "price": int(avg * 0.96) if avg else None, "avg24hPrice": avg,
        "traderName": trader, "traderPrice": tprice, "traderPriceCur": cur if trader else None,
        "updated": iso(NOW), "slots": slots, "diff24h": 0, "icon": svg_icon(short, (i * 37) % 360),
        "link": f"https://tarkov.dev/item/{short.lower()}", "wikiLink": "https://escapefromtarkov.fandom.com/wiki/" + name.replace(" ", "_"),
        "_size": size,
    })
AMMO = []
for j, (cal, name, short, dmg, pen, armor, frag, speed, tracer, price) in enumerate(AMMO_ROWS):
    uid = oid(3000 + j)
    ITEMS.append({"uid": uid, "name": name, "shortName": short, "tags": ["ammo"], "basePrice": price // 2,
                  "price": price, "avg24hPrice": int(price * 1.05), "traderName": "Prapor", "traderPrice": price // 3,
                  "traderPriceCur": "₽", "updated": iso(NOW), "slots": 1, "icon": svg_icon(short, 30 + j * 11),
                  "link": "", "wikiLink": "", "_size": "1x1"})
    AMMO.append({"caliber": cal, "ammoType": "buckshot" if cal == "Caliber12g" else "bullet", "tracer": tracer,
                 "tracerColor": "red" if tracer else None, "projectileCount": 8 if short == "7mm" else 1,
                 "damage": dmg, "armorDamage": armor, "fragmentationChance": frag, "ricochetChance": 0.1,
                 "penetrationChance": 0.5, "penetrationPower": pen, "initialSpeed": speed, "accuracyModifier": 0,
                 "recoilModifier": 0, "lightBleedModifier": 0, "heavyBleedModifier": 0,
                 "item": {"id": uid, "name": name, "shortName": short, "iconLink": svg_icon(short, 30 + j * 11)}})

BY_SHORT = {i["shortName"]: i for i in ITEMS}


def ref(short):
    i = BY_SHORT[short]
    return {"id": i["uid"], "name": i["name"], "shortName": i["shortName"], "iconLink": i["icon"]}


def contained(short, count=1, tool=False):
    return {"count": count, "quantity": count, "attributes": [{"type": "tool", "name": "tool", "value": "true"}] if tool else [],
            "item": ref(short)}


MAP_NAMES = [("Customs", "customs", "8-12", 40), ("Woods", "woods", "8-14", 45), ("Factory", "factory", "4-6", 20),
             ("Interchange", "interchange", "10-14", 45), ("Reserve", "reserve", "9-12", 40),
             ("Shoreline", "shoreline", "10-13", 45), ("Lighthouse", "lighthouse", "9-12", 40),
             ("Streets of Tarkov", "streets-of-tarkov", "12-16", 50), ("The Lab", "the-lab", "6-10", 35)]
MAPS_MIN = {norm: {"id": oid(4000 + k), "name": name, "normalizedName": norm} for k, (name, norm, _, _) in enumerate(MAP_NAMES)}
NAME_IDS = {"customs": "bigmap", "woods": "Woods", "factory": "factory4_day", "interchange": "Interchange",
            "reserve": "RezervBase", "shoreline": "Shoreline", "lighthouse": "Lighthouse",
            "streets-of-tarkov": "TarkovStreets", "the-lab": "laboratory"}

BOSS_ROWS = [("Reshala", "customs", 0.38, 3), ("Shturman", "woods", 0.39, 2), ("Killa", "interchange", 0.38, 0),
             ("Glukhar", "reserve", 0.39, 6), ("Sanitar", "shoreline", 0.39, 2), ("Tagilla", "factory", 0.39, 0),
             ("Kaban", "streets-of-tarkov", 0.4, 6), ("Knight", "lighthouse", 0.31, 2), ("Raiders", "the-lab", 1.0, 0),
             ("Rogues", "lighthouse", 1.0, 0)]
BOSSES = []
for k, (name, mp, chance, escorts) in enumerate(BOSS_ROWS):
    hp = [("head", 35), ("chest", 85), ("stomach", 70), ("leftArm", 60), ("rightArm", 60), ("leftLeg", 65), ("rightLeg", 65)]
    BOSSES.append({"id": oid(5000 + k), "name": name, "normalizedName": name.lower(), "imagePortraitLink": svg_icon(name[:3], k * 30 + 10),
                   "imagePosterLink": None, "health": [{"bodyPart": p, "max": v * (3 if name not in ("Raiders", "Rogues") else 1)} for p, v in hp],
                   "equipment": [contained("6B43"), contained("AK-74N"), contained("Salewa", 2)] if k % 2 == 0 else [contained("M4A1"), contained("PACA")]})

MAPS = []
for k, (name, norm, players, duration) in enumerate(MAP_NAMES):
    bosses = [b for b in BOSS_ROWS if b[1] == norm]
    MAPS.append({
        **MAPS_MIN[norm], "nameId": NAME_IDS[norm], "wiki": f"https://escapefromtarkov.fandom.com/wiki/{name.replace(' ', '_')}",
        "description": f"{name}: one of Tarkov's locations.", "enemies": ["PMC", "Scavs"] + [b[0] for b in bosses],
        "raidDuration": duration, "players": players, "minPlayerLevel": 20 if norm == "the-lab" else None, "maxPlayerLevel": None,
        "accessKeysMinPlayerLevel": None, "accessKeys": [ref("Red")] if norm == "the-lab" else [],
        "bosses": [{"spawnChance": c, "spawnTime": 0, "spawnTimeRandom": False, "spawnTrigger": None,
                    "boss": {"id": oid(5000 + [x[0] for x in BOSS_ROWS].index(b)), "name": b, "normalizedName": b.lower(),
                             "imagePortraitLink": svg_icon(b[:3], 20)},
                    "spawnLocations": [{"name": "Dorms", "chance": 0.5}, {"name": "New gas station", "chance": 0.5}][: 1 + k % 2],
                    "escorts": [{"boss": {"id": oid(6000), "name": "Guard", "normalizedName": "guard"}, "amount": [{"count": e, "chance": 1}]}] if e else []}
                   for (b, _, c, e) in bosses],
        "extracts": [{"id": oid(7000 + k * 10 + n), "name": ex, "faction": f} for n, (ex, f) in enumerate(
            [("ZB-1011", "pmc"), ("Crossroads", "pmc"), ("Old Gas Station", "pmc"), ("Railroad to Tarkov", "shared"),
             ("Trailer Park", "pmc"), ("Scav Checkpoint", "scav"), ("Sniper Roadblock", "scav")])],
        "transits": [{"id": oid(7500 + k), "description": f"Transit to {MAP_NAMES[(k + 1) % len(MAP_NAMES)][0]}",
                      "conditions": "Pay 1 500 roubles", "map": MAPS_MIN[MAP_NAMES[(k + 1) % len(MAP_NAMES)][1]]}],
        "locks": [{"lockType": "door", "needsPower": False, "key": ref("314")}, {"lockType": "door", "needsPower": False, "key": ref("206")},
                  {"lockType": "container", "needsPower": True, "key": ref("KIBA")}],
        "hazards": [{"hazardType": "minefield", "name": "Minefield"}, {"hazardType": "sniper", "name": "Scav sniper"}][: k % 3],
    })

QUESTS = []


def quest(n, name, trader, level, prereq=None, kappa=True, lk=False, objectives=(), rewards=None, map_=None, faction="Any"):
    q = {
        "id": oid(8000 + n), "name": name, "normalizedName": name.lower().replace(" ", "-"), "experience": 1000 + n * 450,
        "wikiLink": "https://escapefromtarkov.fandom.com/wiki/" + name.replace(" ", "_"), "taskImageLink": None,
        "minPlayerLevel": level, "kappaRequired": kappa, "lightkeeperRequired": lk, "factionName": faction, "restartable": False,
        "trader": {k: T[trader][k] for k in ("id", "name", "normalizedName", "imageLink")},
        "map": MAPS_MIN.get(map_) if map_ else None,
        "taskRequirements": [{"task": {"id": oid(8000 + p), "name": next(x["name"] for x in QUESTS if x["id"] == oid(8000 + p))},
                              "status": ["complete"]} for p in (prereq or [])],
        "traderRequirements": [],
        "objectives": list(objectives),
        "finishRewards": rewards or {"items": [contained("Salewa", 2)], "traderStanding": [{"trader": {"id": T[trader]["id"], "name": trader}, "standing": 0.02}],
                                     "offerUnlock": [], "skillLevelReward": [], "traderUnlock": [], "craftUnlock": []},
    }
    QUESTS.append(q)
    return q


def give(short, count, fir=True, desc=None):
    return {"id": oid(rnd.randrange(1 << 30)), "type": "giveItem", "optional": False, "maps": [],
            "description": desc or f"Hand over {count} {BY_SHORT[short]['name']}", "count": count, "foundInRaid": fir,
            "items": [ref(short)], "requiredKeys": []}


def basic(desc, map_=None, type_="visit", keys=()):
    return {"id": oid(rnd.randrange(1 << 30)), "type": type_, "optional": False, "description": desc,
            "maps": [MAPS_MIN[map_]] if map_ else [], "requiredKeys": [[ref(k)] for k in keys]}


def shoot(desc, count, map_=None):
    return {"id": oid(rnd.randrange(1 << 30)), "type": "shoot", "optional": False, "description": desc,
            "maps": [MAPS_MIN[map_]] if map_ else [], "count": count, "targetNames": ["Scav"]}


quest(0, "Debut", "Prapor", 1, objectives=[shoot("Eliminate 5 Scavs all over the Tarkov territory", 5), give("Tushonka", 2, False)], map_=None)
quest(1, "Checking", "Prapor", 2, [0], objectives=[basic("Locate the bronze pocket watch in the truck on Customs", "customs"), give("Tetriz", 1, False)], map_="customs")
quest(2, "Shootout Picnic", "Prapor", 4, [0], objectives=[shoot("Eliminate 15 Scavs on Woods", 15, "woods")], map_="woods")
quest(3, "Delivery from the Past", "Prapor", 6, [1], objectives=[basic("Stash the secure folder in the Tarcone office on Customs", "customs", "plant"), basic("Survive and extract from Customs", "customs", "extract")], map_="customs")
quest(4, "Shortage", "Therapist", 1, objectives=[give("Salewa", 3), give("Water", 2, False)])
quest(5, "Sanitary Standards - Part 1", "Therapist", 4, [4], objectives=[basic("Obtain the package of graphics cards on Customs", "customs"), give("GasAn", 1)], map_="customs")
quest(6, "Operation Aquarius - Part 1", "Therapist", 5, [4], objectives=[basic("Locate the hidden water stash on Customs", "customs", keys=["206"]), give("Water", 4, False)], map_="customs")
quest(7, "Painkiller", "Therapist", 8, [5], objectives=[give("IFAK", 4), give("Propital", 1)])
quest(8, "Private Clinic", "Therapist", 23, [7], objectives=[give("LEDX", 2), give("Salewa", 2)], lk=True)
quest(9, "Health Care Privacy - Part 1", "Therapist", 9, [5], objectives=[basic("Find the ambulance on Woods", "woods")], map_="woods")
quest(10, "Gunsmith - Part 1", "Mechanic", 2, objectives=[{"id": oid(9901), "type": "buildWeapon", "optional": False, "maps": [],
      "description": "Modify an MP-133 to comply with the given specifications", "item": ref("AK-74N")}])
quest(11, "Introduction", "Mechanic", 3, [10], objectives=[give("Drill", 1), give("Toolset", 1)])
quest(12, "Signal - Part 1", "Mechanic", 8, [11], objectives=[give("GPU", 1), give("CPU Fan", 3), give("PCB", 2)])
quest(13, "Farming - Part 1", "Mechanic", 12, [11], objectives=[give("Wires", 5), give("Bolts", 4)], map_="factory")
quest(14, "Bad Rep Evidence", "Skier", 5, objectives=[basic("Obtain the secure folder 0031 on Customs", "customs", keys=["314"])], map_="customs")
quest(15, "Supplier", "Skier", 4, objectives=[give("PACA", 1, False), give("AK-74N", 1, False)])
quest(16, "Chumming", "Skier", 7, [14], objectives=[{"id": oid(9902), "type": "mark", "optional": False, "maps": [MAPS_MIN["customs"]],
      "description": "Mark the dorms with an MS2000 Marker", "markerItem": ref("MS2000"), "requiredKeys": []}], map_="customs")
quest(17, "Fishing Gear", "Peacekeeper", 12, objectives=[basic("Hide a sniper rifle in the boat on Shoreline", "shoreline", "plant")], map_="shoreline")
quest(18, "Wet Job - Part 1", "Peacekeeper", 18, [17], objectives=[shoot("Eliminate Scav snipers on Shoreline", 5, "shoreline")], map_="shoreline")
quest(19, "The Punisher - Part 1", "Prapor", 21, [2], objectives=[shoot("Eliminate 15 Scavs on Shoreline", 15, "shoreline")], map_="shoreline")
quest(20, "Gratitude", "Jaeger", 6, objectives=[give("Moonshine", 1), give("Sugar", 3)], kappa=False)
quest(21, "The Survivalist Path - Unprotected but Dangerous", "Jaeger", 8, objectives=[shoot("Eliminate Scavs without armor", 5, "woods")], map_="woods")
quest(22, "Out of Curiosity", "Ragman", 10, objectives=[give("Badge", 1)], kappa=False)
quest(23, "The Huntsman Path - Secured Perimeter", "Jaeger", 14, objectives=[shoot("Eliminate PMCs on Factory", 8, "factory")], map_="factory")
quest(24, "Long Road", "Ref", 25, [13], faction="USEC", objectives=[give("Rooster", 1)])
quest(25, "Network Provider - Part 1", "Ref", 30, [12], lk=True, objectives=[give("WiFi Cam", 3), give("Intelligence", 2)])

STATIONS = []


def station(n, name, levels):
    STATIONS.append({"id": oid(9000 + n), "name": name, "normalizedName": name.lower().replace(" ", "-"),
                     "imageLink": svg_icon(name[:3], n * 45), "levels": [
                         {"id": oid(9100 + n * 10 + i), "level": i + 1, "constructionTime": (i + 1) * 3600 * (n % 3 + 1),
                          "description": f"{name} level {i + 1}", "itemRequirements": [contained(s, c) for s, c in reqs],
                          "stationLevelRequirements": [], "traderRequirements": [{"trader": {"id": T["Therapist"]["id"], "name": "Therapist"},
                                                                                "requirementType": "level", "compareMethod": ">=", "value": i + 1}] if i else [],
                          "skillRequirements": [], "bonuses": []} for i, reqs in enumerate(levels)]})


station(0, "Medstation", [[("Salewa", 2), ("IFAK", 1)], [("Grizzly", 2), ("Propital", 1)], [("LEDX", 1), ("GasAn", 3)]])
station(1, "Workbench", [[("Drill", 1), ("Toolset", 1)], [("Bolts", 5), ("Wires", 3)], [("PCB", 3), ("Cord", 2)]])
station(2, "Intelligence Center", [[("Intelligence", 1), ("Tetriz", 1)], [("GPU", 1), ("PCB", 2), ("CPU Fan", 3)], [("GPU", 1), ("WiFi Cam", 3)]])
station(3, "Lavatory", [[("Tape", 3), ("Hose", 2)], [("Tape", 3), ("Bolts", 2)], [("Hose", 6), ("MPF", 1)]])
station(4, "Generator", [[("Cord", 1), ("Wires", 2)], [("Cord", 2), ("MPF", 1)], [("Cord", 3), ("GasAn", 2)]])
station(5, "Nutrition Unit", [[("Water", 2), ("Tushonka", 1)], [("Sugar", 2), ("Matches", 2)], [("Moonshine", 1), ("Sugar", 4)]])
station(6, "Booze Generator", [[("Hose", 3), ("Bolts", 3), ("Sugar", 5)]])
station(7, "Bitcoin Farm", [[("GPU", 1), ("CPU Fan", 5)], [("GPU", 2), ("Cord", 4)], [("GPU", 3), ("PCB", 5)]])

BARTERS = []
for n, (trader, lvl, req, rew, limit) in enumerate([
    ("Therapist", 1, [("Water", 2), ("Matches", 1)], [("Salewa", 1)], None),
    ("Therapist", 2, [("Moonshine", 1)], [("Propital", 4)], 2),
    ("Therapist", 3, [("Tetriz", 2), ("Bolts", 1)], [("Grizzly", 1)], None),
    ("Mechanic", 2, [("GPU", 1)], [("M4A1", 1)], 1),
    ("Mechanic", 1, [("Wires", 2), ("Tape", 1)], [("Drill", 1)], None),
    ("Prapor", 1, [("Sugar", 2)], [("AK-74N", 1)], 3),
    ("Prapor", 2, [("Tushonka", 3)], [("Factory", 1)], None),
    ("Ragman", 3, [("Badge", 1), ("Intelligence", 1)], [("6B43", 1)], 1),
    ("Skier", 2, [("Rooster", 1)], [("Toolset", 2)], None),
    ("Peacekeeper", 4, [("0.2BTC", 1)], [("SICC", 1)], 1),
    ("Jaeger", 1, [("Matches", 2), ("Tushonka", 1)], [("Water", 3)], None),
    ("Fence", 1, [("LEDX", 1)], [("0.2BTC", 1)], None),
]):
    BARTERS.append({"id": oid(9500 + n), "level": lvl, "buyLimit": limit,
                    "trader": {k: T[trader][k] for k in ("id", "name", "normalizedName", "imageLink")},
                    "taskUnlock": {"id": QUESTS[4]["id"], "name": QUESTS[4]["name"]} if n == 1 else None,
                    "requiredItems": [contained(s, c) for s, c in req], "rewardItems": [contained(s, c) for s, c in rew]})

CRAFTS = []
for n, (st, lvl, dur, req, rew) in enumerate([
    (0, 1, 3600, [("Water", 2), ("Matches", 1)], [("IFAK", 1)]),
    (0, 2, 7200, [("IFAK", 2), ("Salewa", 1)], [("Grizzly", 1)]),
    (0, 3, 14400, [("Grizzly", 1), ("Moonshine", 1)], [("Propital", 3)]),
    (1, 1, 2700, [("Wires", 1), ("Tape", 1), ("Toolset", 1, True)], [("Cord", 1)]),
    (1, 2, 5400, [("PCB", 1), ("CPU Fan", 1), ("Toolset", 1, True)], [("GPU", 1)]),
    (2, 2, 9000, [("Intelligence", 1), ("Tetriz", 1)], [("0.2BTC", 1)]),
    (5, 1, 4200, [("Sugar", 2), ("Water", 1)], [("Tushonka", 2)]),
    (6, 1, 13000, [("Sugar", 2), ("Water", 1)], [("Moonshine", 1)]),
    (7, 1, 145000, [("GPU", 1, True)], [("0.2BTC", 1)]),
    (3, 2, 10800, [("Hose", 2), ("Bolts", 1)], [("MPF", 1)]),
]):
    s = STATIONS[st]
    CRAFTS.append({"id": oid(9700 + n), "level": lvl, "duration": dur,
                   "station": {"id": s["id"], "name": s["name"], "normalizedName": s["normalizedName"], "imageLink": s["imageLink"]},
                   "taskUnlock": None, "requiredItems": [contained(*r) if len(r) == 2 else contained(r[0], r[1], True) for r in req],
                   "rewardItems": [contained(s2, c) for s2, c in rew]})

CASH_OFFERS = []
for t in TRADERS:
    offers = []
    for k, i in enumerate(ITEMS[: 30]):
        if (k + len(t["name"])) % 4 == 0 and i.get("avg24hPrice"):
            price = int((i["avg24hPrice"] or i["basePrice"]) * 1.15)
            offers.append({"minTraderLevel": 1 + k % 4, "price": price if t["name"] != "Peacekeeper" else price // 142,
                           "currency": "USD" if t["name"] == "Peacekeeper" else "RUB", "priceRUB": price,
                           "buyLimit": 5 if k % 3 == 0 else None, "taskUnlock": {"id": QUESTS[k % len(QUESTS)]["id"], "name": QUESTS[k % len(QUESTS)]["name"]} if k % 7 == 0 else None,
                           "item": ref(i["shortName"])})
    CASH_OFFERS.append({"id": t["id"], "name": t["name"], "normalizedName": t["normalizedName"], "cashOffers": offers})

ACHIEVEMENTS = [{"id": oid(9800 + n), "name": name, "description": desc, "hidden": hidden, "playersCompletedPercent": pct,
                 "adjustedPlayersCompletedPercent": min(100, pct * 1.6), "side": side, "normalizedSide": side.lower(),
                 "rarity": rarity, "normalizedRarity": rarity.lower(), "imageLink": svg_icon(name[:3], n * 25)}
                for n, (name, desc, hidden, pct, side, rarity) in enumerate([
                    ("Welcome to Tarkov", "Die for the first time", False, 82.1, "All", "Common"),
                    ("The Kappa Path", "Obtain the Kappa container", False, 1.9, "PMC", "Legendary"),
                    ("Snowball", "Kill 100 Scavs", False, 21.4, "PMC", "Common"),
                    ("Firestarter", "Destroy the BTR", True, 0.6, "PMC", "Legendary"),
                    ("Long Live the King!", "Kill Reshala 15 times", False, 3.1, "PMC", "Rare"),
                    ("Butter Fingers", "Drop your weapon in raid", False, 44.7, "All", "Common"),
                    ("Scav Life", "Survive 50 raids as a Scav", False, 12.2, "Scavs", "Rare"),
                    ("Just Business", "Complete 100 quests", False, 8.8, "PMC", "Rare"),
                ])]

STATUS = {"generalStatus": {"name": "Global", "message": "All systems operational", "status": 0, "statusCode": "OK"},
          "currentStatuses": [{"name": n, "message": "", "status": s, "statusCode": "OK"} for n, s in
                              [("Website", 0), ("Forum", 0), ("Authentication", 0), ("Launcher", 0), ("Group lobby", 0),
                               ("Trading", 0), ("Matchmaking", 2), ("Friends and msg", 0), ("Inventory operations", 0)]],
          "messages": [{"content": "Matchmaking may take longer than usual on EU servers.", "time": iso(NOW - timedelta(minutes=50)),
                        "type": 1, "solveTime": None, "statusCode": "Unstable"}]}
GOONS = [{"timestamp": str(int((time.time() - m * 60) * 1000)), "map": MAPS_MIN[n]} for m, n in
         [(14, "lighthouse"), (95, "shoreline"), (260, "woods"), (400, "customs"), (900, "lighthouse")]]
FLEA = {"minPlayerLevel": 15, "enabled": True, "sellOfferFeeRate": 0.03, "sellRequirementFeeRate": 0.03,
        "foundInRaidRequired": True, "reputationLevels": []}
MAP_IMAGES = [{"normalizedName": norm, "maps": [{"key": norm, "projection": "interactive"},
                                                {"key": f"{norm}-2d", "projection": "2D", "author": "Demo artist", "authorLink": "https://example.com"}]}
              for _, norm, _, _ in MAP_NAMES]
WIPES = [{"name": "0.16.8.0", "start": "2025-07-09T07:00:00.000Z"}, {"name": "1.0.0.0", "start": "2025-11-15T09:00:00.000Z"}]


def item_detail(item_id: str) -> dict:
    lite = next((i for i in ITEMS if i["uid"] == item_id), None)
    if not lite:
        return {"item": None, "history": []}
    w, h_ = (int(x) for x in lite.get("_size", "1x1").split("x"))
    avg = lite["avg24hPrice"]
    sell = [{"price": lite["traderPrice"], "currency": "USD" if lite["traderPriceCur"] == "$" else "RUB",
             "priceRUB": int(lite["traderPrice"] * (142 if lite["traderPriceCur"] == "$" else 1)),
             "vendor": {"name": lite["traderName"], "normalizedName": lite["traderName"].lower(), "minTraderLevel": 1}}] if lite["traderName"] else []
    sell += [{"price": int(lite["traderPrice"] * 0.6), "currency": "RUB", "priceRUB": int(lite["traderPrice"] * 0.6),
              "vendor": {"name": "Fence", "normalizedName": "fence", "minTraderLevel": 1}}] if lite["traderName"] else []
    if avg and "noFlea" not in lite["tags"]:
        sell.append({"price": lite["price"], "currency": "RUB", "priceRUB": lite["price"], "vendor": {"name": "Flea Market", "normalizedName": "flea-market"}})
    buy = [{"price": int(avg * 1.02), "currency": "RUB", "priceRUB": int(avg * 1.02), "vendor": {"name": "Flea Market", "normalizedName": "flea-market"}}] if avg else []
    for t in CASH_OFFERS:
        for o in t["cashOffers"]:
            if o["item"]["id"] == item_id:
                buy.append({"price": o["price"], "currency": o["currency"], "priceRUB": o["priceRUB"],
                            "vendor": {"name": t["name"], "normalizedName": t["normalizedName"], "minTraderLevel": o["minTraderLevel"],
                                       "buyLimit": o["buyLimit"], "taskUnlock": o["taskUnlock"]}})
    uses = [q for q in QUESTS if any((o.get("items") or [{}])[0].get("id") == item_id for o in q["objectives"] if o.get("items"))]
    base_t = time.time() * 1000
    history = []
    if avg:
        price = avg
        for hr in range(7 * 24, 0, -2):
            price = max(1, int(price * (1 + rnd.uniform(-0.03, 0.03))))
            history.append({"price": price, "priceMin": int(price * 0.93), "offerCount": rnd.randrange(20, 300),
                            "timestamp": str(int(base_t - hr * 3600 * 1000))})
    return {
        "item": {
            "id": item_id, "name": lite["name"], "shortName": lite["shortName"], "normalizedName": lite["shortName"].lower(),
            "description": f"The {lite['name']}. Demo description text for testing the item panel layout.",
            "basePrice": lite["basePrice"], "width": w, "height": h_, "weight": round(0.2 * w * h_, 2), "backgroundColor": "default",
            "iconLink": lite["icon"], "gridImageLink": lite["icon"], "image512pxLink": lite["icon"], "inspectImageLink": lite["icon"],
            "wikiLink": lite["wikiLink"], "link": lite["link"], "types": lite["tags"],
            "avg24hPrice": avg, "lastLowPrice": lite["price"], "low24hPrice": int(avg * 0.9) if avg else None,
            "high24hPrice": int(avg * 1.12) if avg else None, "changeLast48h": 0, "changeLast48hPercent": rnd.uniform(-8, 8) if avg else None,
            "lastOfferCount": rnd.randrange(5, 400), "updated": iso(NOW), "minLevelForFlea": 15, "category": {"name": lite["tags"][0].title()},
            "sellFor": sell, "buyFor": buy,
            "usedInTasks": [{"id": q["id"], "name": q["name"], "trader": {"name": q["trader"]["name"]}} for q in uses],
            "receivedFromTasks": [],
            "bartersFor": [b for b in BARTERS if any(r["item"]["id"] == item_id for r in b["rewardItems"])],
            "bartersUsing": [b for b in BARTERS if any(r["item"]["id"] == item_id for r in b["requiredItems"])],
            "craftsFor": [c for c in CRAFTS if any(r["item"]["id"] == item_id for r in c["rewardItems"])],
            "craftsUsing": [c for c in CRAFTS if any(r["item"]["id"] == item_id for r in c["requiredItems"])],
        },
        "history": history,
    }


QUERY_DATA = {
    "tasks": QUESTS, "hideoutStations": STATIONS, "barters": BARTERS, "crafts": CRAFTS, "ammo": AMMO, "maps": MAPS,
    "bosses": BOSSES, "achievements": ACHIEVEMENTS, "status": STATUS, "goonReports": GOONS, "fleaMarket": FLEA,
}


class DemoClient:
    """Stands in for TarkovClient: answers queries from the data above."""

    def __init__(self, game_mode="regular", delay=0.0):
        self.game_mode = game_mode
        self.delay = delay

    def query(self, template, variables=None, **params):
        time.sleep(self.delay)
        if "query Item(" in template:
            return item_detail(variables["id"])
        name = re.search(r"query (\w+)", template).group(1)
        if name == "Traders":
            return {"traders": [dict(t) for t in TRADERS]}
        if name == "CashOffers":
            return {"traders": CASH_OFFERS}
        key = re.search(r"query \w+\s*\{\s*(\w+)", template).group(1)
        return {key: QUERY_DATA[key]}

    def get_json(self, url):
        time.sleep(self.delay)
        if url.endswith("/api/v1/items"):
            return ITEMS
        if url.endswith("maps.json"):
            return MAP_IMAGES
        if url.endswith("wipe-details.json"):
            return WIPES
        raise RuntimeError(f"demo has no {url}")


def install(monkeypatch=None):
    """Make every new DataStore/PriceDB use the demo data (undone after the
    test when a pytest ``monkeypatch`` is given)."""
    from tarkov_display import datasets, prices

    setattr_ = monkeypatch.setattr if monkeypatch else setattr
    original_store = datasets.DataStore.__init__

    def store_init(self, cache_dir, game_mode="regular", client=None, on_update=None):
        original_store(self, cache_dir, game_mode, DemoClient(game_mode), on_update)

    setattr_(datasets.DataStore, "__init__", store_init)
    original_prices = prices.PriceDB.__init__

    def prices_init(self, *args, **kwargs):
        original_prices(self, *args, **kwargs)
        self.client = DemoClient(self.game_mode)

    setattr_(prices.PriceDB, "__init__", prices_init)


def main(port: int = 47999) -> None:
    import logging
    import os
    import tempfile

    os.environ["APPDATA"] = tempfile.mkdtemp(prefix="tarkov-demo-")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    install()
    from tarkov_display.webapp import WebApp

    WebApp(open_on_start=False, port=port).run()


if __name__ == "__main__":
    import sys

    main(int(sys.argv[1]) if len(sys.argv) > 1 else 47999)
