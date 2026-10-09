"""tarkov.dev's data files (json.tarkov.dev) turned into the app's shapes.

The sample files follow the layout tarkov.dev's data manager writes
(jobs/update-*.mjs): ids instead of objects, translation keys plus an
English file, attribute lists turned into objects.
"""

import copy
import time

import pytest

from tarkov_display import staticapi
from tarkov_display.datasets import DataStore
from tarkov_display.prices import PriceDB
from tarkov_display.staticapi import STATIC_URL, jsonpath

NOW_MS = time.time() * 1000


def files():
    def doc(data, *translations):
        return {"data": data, "translations": list(translations)}

    no_rewards = {"traderStanding": [], "items": [], "offerUnlock": [], "skillLevelReward": [], "traderUnlock": [],
                  "craftUnlock": [], "achievement": [], "customization": []}
    tasks = {
        "debut": {
            "id": "debut", "name": "debut name", "normalizedName": "debut", "experience": 1700, "wikiLink": "https://wiki/debut",
            "taskImageLink": "debut.webp", "minPlayerLevel": 1, "kappaRequired": True, "lightkeeperRequired": False,
            "factionName": "Any", "restartable": False, "trader": "prapor", "map": "customs",
            "taskRequirements": [], "traderRequirements": [],
            "neededKeys": [{"map": "customs", "keys": ["key-dorm"]}],
            "objectives": [
                {"id": "obj-shoot", "type": "shoot", "description": "obj-shoot", "optional": False, "maps": ["customs"],
                 "count": 5, "targetNames": ["Savage"], "bodyParts": ["Head"], "shotType": "kill",
                 "distance": {"compareMethod": ">=", "value": 50}, "timeFromHour": 22, "timeUntilHour": 5,
                 "usingWeapon": ["ammo-ps"], "usingWeaponMods": [["marker"]], "wearing": [[{"id": "key-dorm"}]],
                 "notWearing": [{"id": "marker"}],
                 "zones": [{"id": "zone-dorms", "map": "customs", "name": "zone-dorms", "position": {"x": 1, "y": 2, "z": 3}}],
                 "healthEffect": {"bodyParts": ["Chest"], "effects": ["Fracture"]}},
                {"id": "obj-extract", "type": "extract", "description": "obj-extract", "optional": False,
                 "maps": ["customs"], "count": 1, "exitStatus": ["Survived", "Runner"], "exitName": "ex1 key"},
                {"id": "obj-find", "type": "findQuestItem", "description": "obj-find", "optional": False, "maps": [],
                 "questItem": "folder", "possibleLocations": [{"map": "customs", "positions": [{"x": 1, "y": 0, "z": 2}]}]},
                {"id": "obj-give", "type": "giveItem", "description": "obj-give", "optional": False, "count": 2,
                 "foundInRaid": True, "items": ["ledx"]},
                {"id": "obj-mark", "type": "mark", "description": "obj-mark", "optional": True, "maps": ["customs"],
                 "markerItem": "marker", "requiredKeys": [["key-dorm"]]},
                {"id": "obj-quest", "type": "findQuestItem", "description": "obj-quest", "optional": False, "maps": [],
                 "questItem": "folder"},
                {"id": "obj-skill", "type": "skill", "description": "obj-skill", "optional": False, "maps": [],
                 "skill": "Endurance", "level": 3},
                {"id": "obj-ll", "type": "traderLevel", "description": "obj-ll", "optional": False,
                 "trader": "therapist", "level": 2},
            ],
            "failConditions": [{"id": "fail-1", "type": "taskStatus", "description": "fail-1", "optional": False,
                                "task": "shortage", "status": ["fail"]}],
            "startRewards": copy.deepcopy(no_rewards), "failureOutcome": copy.deepcopy(no_rewards),
            "finishRewards": {
                **copy.deepcopy(no_rewards),
                "traderStanding": [{"trader": "prapor", "standing": 0.02}],
                "items": [{"item": "ledx", "count": 1, "attributes": {}}],
                "offerUnlock": [{"trader": "prapor", "level": 1, "item": "ammo-ps"}],
                "skillLevelReward": [{"skill": "Endurance", "level": 1}],
                "traderUnlock": ["therapist"],
                "craftUnlock": [{"id": "craft-1", "station": "medstation", "level": 1, "item": "ammo-ps", "count": 60}],
            },
        },
        "shortage": {
            "id": "shortage", "name": "shortage name", "normalizedName": "shortage", "experience": 2800, "minPlayerLevel": 2,
            "kappaRequired": True, "lightkeeperRequired": False, "factionName": "Any", "trader": "therapist", "map": None,
            "taskRequirements": [{"task": "debut", "status": ["complete"]}],
            "traderRequirements": [{"trader": "therapist", "requirementType": "level", "compareMethod": ">=", "value": 1}],
            "objectives": [], "failConditions": [],
            "startRewards": copy.deepcopy(no_rewards), "finishRewards": copy.deepcopy(no_rewards),
            "failureOutcome": copy.deepcopy(no_rewards),
        },
    }
    items = {
        "ledx": {"id": "ledx", "name": "ledx Name", "shortName": "ledx ShortName", "description": "ledx Description",
                 "normalizedName": "ledx-skin-transilluminator", "basePrice": 125000, "width": 1, "height": 1, "weight": 0.1,
                 "iconLink": "ledx-icon.webp", "wikiLink": "https://wiki/ledx", "link": "https://tarkov.dev/item/ledx",
                 "types": ["barter"], "avg24hPrice": 1000000, "lastLowPrice": 950000, "low24hPrice": 900000,
                 "high24hPrice": 1100000, "changeLast48hPercent": 2.5, "lastOfferCount": 40, "updated": "2026-10-08",
                 "categories": ["cat-meds", "cat-item"], "properties": None, "containsItems": [],
                 "buyFromTrader": [{"trader": "therapist", "price": 1000, "priceRUB": 140000, "currency": "USD",
                                    "minTraderLevel": 4, "taskUnlock": "shortage", "buyLimit": 1, "restockAmount": 2}],
                 "sellToTrader": [{"trader": "therapist", "price": 80000, "priceRUB": 80000, "currency": "RUB"},
                                  {"trader": "prapor", "price": 60000, "priceRUB": 60000, "currency": "RUB"}]},
        "ammo-ps": {"id": "ammo-ps", "name": "ammo-ps Name", "shortName": "ammo-ps ShortName", "basePrice": 100,
                    "width": 1, "height": 1, "iconLink": "ps.webp", "types": ["ammo"], "avg24hPrice": 120,
                    "lastLowPrice": 110, "categories": [staticapi.AMMO_CATEGORY, "cat-item"], "buyFromTrader": [],
                    "sellToTrader": [], "properties": {"propertiesType": "ItemPropertiesAmmo", "caliber": "Caliber545x39",
                                                       "ammoType": "bullet", "damage": 50, "penetrationPower": 30,
                                                       "projectileCount": 1, "armorDamage": 52, "fragmentationChance": 0.2,
                                                       "slots": [{"name": "slot key"}]}},
        "marker": {"id": "marker", "name": "marker Name", "shortName": "marker ShortName", "types": ["noFlea"],
                   "categories": [], "buyFromTrader": [], "sellToTrader": []},
        "key-dorm": {"id": "key-dorm", "name": "key-dorm Name", "shortName": "key-dorm ShortName", "types": ["keys"],
                     "categories": [], "buyFromTrader": [], "sellToTrader": []},
    }
    traders = {
        "prapor": {"id": "prapor", "name": "prapor Nickname", "normalizedName": "prapor", "description": "prapor Description",
                   "imageLink": "prapor.webp", "resetTime": "2026-10-08T21:00:00.000Z", "currency": "RUB",
                   "levels": [{"id": "prapor-1", "level": 1, "requiredPlayerLevel": 1, "requiredReputation": 0,
                               "requiredCommerce": 0, "payRate": 0.5, "insuranceRate": 0.25, "repairCostMultiplier": 1}],
                   "reputationLevels": [], "buyAllowed": {}, "buyProhibited": {}},
        "therapist": {"id": "therapist", "name": "therapist Nickname", "normalizedName": "therapist",
                      "imageLink": "therapist.webp", "resetTime": "2026-10-08T22:00:00.000Z", "currency": "RUB",
                      "levels": [], "reputationLevels": []},
    }
    maps = {
        "maps": {
            "customs": {"id": "customs", "name": "customs Name", "normalizedName": "customs", "nameId": "bigmap",
                        "wiki": "https://wiki/customs", "description": "customs Description", "enemies": ["Savage", "Pmc"],
                        "raidDuration": 40, "players": "8-12", "minPlayerLevel": 0, "maxPlayerLevel": 0,
                        "accessKeys": [], "accessKeysMinPlayerLevel": 0,
                        "bosses": [{"mob": "reshala", "spawnChance": 0.38, "spawnTime": -1, "spawnTimeRandom": False,
                                    "spawnTrigger": "trigger key", "spawnLocations": [{"name": "dorms key", "chance": 0.5}],
                                    "escorts": [{"mob": "guard", "amount": [{"count": 4, "chance": 1}]}], "supports": []}],
                        "extracts": [{"id": "ex1", "name": "ex1 key", "faction": "pmc", "switches": []}],
                        "transits": [{"id": "tr1", "description": "tr1 key", "conditions": "tr1 conditions", "map": "woods"}],
                        "locks": [{"lockType": "door", "key": "key-dorm", "needsPower": False}],
                        "hazards": [{"hazardType": "minefield", "name": "mines key"}],
                        "switches": [], "lootContainers": [], "lootLoose": [], "stationaryWeapons": []},
            "woods": {"id": "woods", "name": "woods Name", "normalizedName": "woods", "nameId": "Woods", "bosses": [],
                      "extracts": [], "transits": [], "locks": [], "hazards": []},
        },
        "mobs": {
            "reshala": {"id": "reshala", "name": "reshala key", "normalizedName": "reshala", "imagePortraitLink": "r.webp",
                        "imagePosterLink": "rp.webp", "health": [{"bodyPart": "Head", "max": 35}],
                        "equipment": [{"item": "ammo-ps", "count": 30, "attributes": {}, "contains": []}], "items": []},
            "guard": {"id": "guard", "name": "guard key", "normalizedName": "guard", "health": [], "equipment": [], "items": []},
        },
        "goonReports": [{"map": "woods", "timestamp": str(int(NOW_MS) - 60000)},
                        {"map": "customs", "timestamp": str(int(NOW_MS))}],
        "lootContainers": {}, "stationaryWeapons": {},
    }
    hideout = {
        "medstation": {"id": "medstation", "name": "medstation name", "normalizedName": "medstation", "imageLink": "med.webp",
                       "levels": [{"id": "medstation-1", "level": 1, "constructionTime": 7200, "description": "med1 desc",
                                   "itemRequirements": [{"id": "r1", "item": "ledx", "count": 1, "quantity": 1,
                                                         "attributes": {"foundInRaid": True}}],
                                   "stationLevelRequirements": [{"station": "medstation", "level": 0}],
                                   "traderRequirements": [{"trader": "therapist", "requirementType": "loyaltyLevel",
                                                           "compareMethod": ">=", "value": 2}],
                                   "skillRequirements": [{"skill": "Endurance key", "level": 2}],
                                   "bonuses": [{"type": "HealthRegeneration", "name": "bonus key", "value": 0.1,
                                                "passive": True, "production": False}]}]},
    }
    return {
        "regular/tasks": doc({"tasks": tasks, "questItems": {"folder": {"id": "folder", "name": "folder name",
                                                                         "shortName": "folder short", "iconLink": "f.webp"}},
                              "achievements": {"ach": {"id": "ach", "name": "ach name", "description": "ach description",
                                                       "hidden": False, "side": "Pmc", "normalizedSide": "pmc",
                                                       "rarity": "rarity key", "normalizedRarity": "common",
                                                       "playersCompletedPercent": 40.5,
                                                       "adjustedPlayersCompletedPercent": 55.1, "imageLink": "a.webp"}},
                              "prestige": []},
                             "$.data.tasks.*.name", "$.data.tasks.*.objectives[*].description",
                             "$.data.tasks.*.objectives[*].exitName", "$.data.tasks.*.objectives[*].exitStatus[*]",
                             "$.data.tasks.*.objectives[*].zones[*].name", "$.data.tasks.*.failConditions[*].description",
                             "$.data.tasks.*.objectives[*].targetNames[*]", "$.data.tasks.*.objectives[*]..bodyParts[*]",
                             "$.data.tasks.*.objectives[*]['healthEffect','playerHealthEffect','enemyHealthEffect'].effects[*]",
                             "$.data.questItems.*.name", "$.data.questItems.*.shortName", "$.data.achievements.*.name",
                             "$.data.achievements.*.description", "$.data.achievements.*.side", "$.data.achievements.*.rarity"),
        "regular/tasks_en": doc({"debut name": "Debut", "shortage name": "Shortage", "obj-shoot": "Kill 5 Scavs",
                                 "obj-give": "Hand over 2 LEDX", "obj-mark": "Mark the truck", "obj-quest": "Find the folder",
                                 "obj-skill": "Reach Endurance 3", "obj-ll": "Therapist LL2", "Savage": "Scav",
                                 "Head": "Head", "Chest": "Thorax", "Fracture": "Fracture", "folder name": "Secure folder",
                                 "folder short": "Folder", "ach name": "Welcome", "ach description": "Finish a raid",
                                 "obj-extract": "Survive and extract", "obj-find": "Find the folder", "ex1 key": "Crossroads",
                                 "Survived": "Survived", "Runner": "Run through", "zone-dorms": "Dorms",
                                 "fail-1": "Shortage must not fail",
                                 "Pmc": "PMC", "rarity key": "Common"}),
        "regular/items": doc({"items": items, "itemCategories": {"cat-meds": {"id": "cat-meds", "name": "cat-meds name"},
                                                                 "cat-item": {"id": "cat-item", "name": "cat-item name"}},
                              "fleaMarket": {"name": "flea name", "normalizedName": "flea-market", "minPlayerLevel": 15,
                                             "enabled": True, "sellOfferFeeRate": 0.05, "sellRequirementFeeRate": 0.05,
                                             "foundInRaidRequired": False, "reputationLevels": [{"offers": 2, "minRep": 0, "maxRep": 1}]}},
                             "$.data.items.*.name", "$.data.items.*.shortName", "$.data.items.*.description",
                             "$.data.items.*.properties.slots[*].name", "$.data.itemCategories.*.name"),
        "regular/items_en": doc({"ledx Name": "LEDX Skin Transilluminator", "ledx ShortName": "LEDX",
                                 "ledx Description": "A medical device", "ammo-ps Name": "5.45x39mm PS gs",
                                 "ammo-ps ShortName": "PS", "marker Name": "MS2000 Marker", "marker ShortName": "MS2000",
                                 "key-dorm Name": "Dorm room 314 marked key", "key-dorm ShortName": "314",
                                 "cat-meds name": "Medical supplies", "cat-item name": "Item"}),
        "regular/traders": doc(traders, "$.data.*.name", "$.data.*.description"),
        "regular/traders_en": doc({"prapor Nickname": "Prapor", "prapor Description": "Weapons", "therapist Nickname": "Therapist"}),
        "regular/maps": doc(maps, "$.data.maps.*.name", "$.data.maps.*.description", "$.data.maps.*.enemies[*]",
                            "$.data.maps.*.bosses[*].spawnLocations[*].name", "$.data.maps.*.extracts[*].name",
                            "$.data.maps.*.hazards[*].name", "$.data.maps.*.transits[*].description",
                            "$.data.mobs.*.health[*].bodyPart", "$.data.mobs.*.name"),
        "regular/maps_en": doc({"customs Name": "Customs", "customs Description": "An industrial zone", "woods Name": "Woods",
                                "Savage": "Scavs", "Pmc": "PMCs", "dorms key": "Dorms", "ex1 key": "Crossroads",
                                "mines key": "Minefield", "tr1 key": "To Woods", "tr1 conditions": "Pay 5000 roubles",
                                "trigger key": "Opening the door", "Head": "Head", "reshala key": "Reshala",
                                "guard key": "Guard"}),
        "regular/hideout": doc(hideout, "$.data.*.name", "$.data.*.levels[*].description",
                               "$.data.*.levels[*].skillRequirements[*].skill", "$.data.*.levels[*].bonuses[*].name"),
        "regular/hideout_en": doc({"medstation name": "Medstation", "med1 desc": "Basic healing",
                                   "Endurance key": "Endurance", "bonus key": "Health regeneration"}),
        "regular/barters": doc([{"id": "barter-1", "trader": "prapor", "minTraderLevel": 2, "buyLimit": 3, "taskUnlock": "debut",
                                 "requiredItems": [{"item": "ledx", "count": 1, "attributes": {}}],
                                 "offeredItem": {"item": "ammo-ps", "count": 120, "attributes": {}}}]),
        "regular/crafts": doc([{"id": "craft-1", "station": "medstation", "level": 1, "duration": 3600, "taskUnlock": None,
                                "requiredItems": [{"item": "ledx", "count": 1, "attributes": {"tool": True}}],
                                "requiredQuestItems": [], "productItem": {"item": "ammo-ps", "count": 60, "attributes": {}}}]),
        "status": doc({"generalStatus": {"name": "Global", "message": "", "status": 0, "statusCode": "OK"},
                       "currentStatuses": [{"name": "Trading", "message": "", "status": 0, "statusCode": "OK"}],
                       "messages": []}),
        "regular/prices/ledx": doc([{"price": 990000, "priceMin": 900000, "offerCount": 30, "timestamp": NOW_MS - 3600e3},
                                    {"price": 1, "priceMin": 1, "offerCount": 1, "timestamp": NOW_MS - 30 * 86400e3}]),
    }


class StaticClient:
    """Serves the sample files; GraphQL is "down" unless told otherwise."""

    def __init__(self, game_mode="regular", data=None, graphql=None):
        self.game_mode = game_mode
        self.files = data if data is not None else files()
        self.graphql = graphql
        self.urls, self.queries = [], []

    def get_json(self, url):
        self.urls.append(url)
        path = url[len(STATIC_URL):]
        if path not in self.files:
            raise RuntimeError(f"HTTP 404 for {path}")
        return copy.deepcopy(self.files[path])

    def query(self, template, variables=None, **params):
        self.queries.append(template)
        if self.graphql is None:
            raise RuntimeError("HTTP 422: GraphQL server unavailable. Try again later.")
        return self.graphql


def ref(item_id, name, short, icon):
    return {"id": item_id, "name": name, "shortName": short, "iconLink": icon}


LEDX = ref("ledx", "LEDX Skin Transilluminator", "LEDX", "ledx-icon.webp")
PS = ref("ammo-ps", "5.45x39mm PS gs", "PS", "ps.webp")


# -- JSONPath and translations --------------------------------------------------------------

def test_jsonpath_steps():
    doc = {"data": {"a": {"objectives": [{"x": {"bodyParts": ["h", "c"]}}, {"bodyParts": ["l"]}]},
                    "b": {"objectives": [], "rewards": {"one": [1], "two": [2]}}}}
    found = lambda path: [parent[key] for parent, key in jsonpath(doc, path)]  # noqa: E731
    assert sorted(found("$.data.*.objectives[*]..bodyParts[*]")) == ["c", "h", "l"]
    assert found("$.data.b['rewards'][*]") == [[1], [2]]
    assert found("$.data.b.rewards['two','missing'][*]") == [2]
    assert found("$.data.nothing.*") == []
    with pytest.raises(ValueError):
        jsonpath(doc, "$.data[?(@.x)]")


def test_translations_follow_the_file_paths():
    doc = {"data": {"t": {"name": "t name", "id": "t name", "tags": ["a", "b"]}}, "translations": ["$.data.*.name", "$.data.*.tags[*]"]}
    staticapi.translate(doc, {"t name": "Debut", "a": "Alpha"})
    assert doc["data"]["t"] == {"name": "Debut", "id": "t name", "tags": ["Alpha", "b"]}  # ids stay; missing keys stay


# -- datasets in the GraphQL shapes ------------------------------------------------------------

def test_tasks():
    tasks = {t["id"]: t for t in staticapi.tasks(StaticClient())}
    debut = tasks["debut"]
    assert debut["name"] == "Debut" and debut["kappaRequired"] is True and debut["experience"] == 1700
    assert debut["trader"] == {"id": "prapor", "name": "Prapor", "normalizedName": "prapor", "imageLink": "prapor.webp"}
    assert debut["map"] == {"id": "customs", "name": "Customs", "normalizedName": "customs"}
    shoot, extract, find, give, mark, quest, skill, ll = debut["objectives"]
    assert shoot["description"] == "Kill 5 Scavs" and shoot["targetNames"] == ["Scav"] and shoot["count"] == 5
    assert shoot["maps"] == [{"id": "customs", "name": "Customs", "normalizedName": "customs"}]
    assert shoot["shotType"] == "kill" and shoot["bodyParts"] == ["Head"] and shoot["distance"]["value"] == 50
    assert (shoot["timeFromHour"], shoot["timeUntilHour"]) == (22, 5)
    assert shoot["zones"] == [{"id": "zone-dorms", "map": {"id": "customs"}}] and shoot["zoneNames"] == ["Dorms"]
    assert shoot["usingWeapon"] == [PS] and shoot["usingWeaponMods"][0][0]["id"] == "marker"
    assert shoot["wearing"][0][0]["name"] == "Dorm room 314 marked key" and shoot["notWearing"][0]["id"] == "marker"
    assert extract["exitStatus"] == ["Survived", "Run through"] and extract["exitName"] == "Crossroads"
    assert find["questItem"]["name"] == "Secure folder" and find["possibleLocations"] == [{"map": {"id": "customs"}}]
    assert debut["neededKeys"] == [{"keys": [ref("key-dorm", "Dorm room 314 marked key", "314", None)],
                                    "map": {"id": "customs", "name": "Customs", "normalizedName": "customs"}}]
    assert debut["failConditions"] == [{"id": "fail-1", "type": "taskStatus", "description": "Shortage must not fail",
                                        "optional": False, "maps": [], "status": ["fail"],
                                        "task": {"id": "shortage", "name": "Shortage"}}]
    assert give["items"] == [LEDX] and give["foundInRaid"] is True and give["count"] == 2 and give["maps"] == []
    assert mark["markerItem"] == ref("marker", "MS2000 Marker", "MS2000", None) and mark["optional"] is True
    assert mark["requiredKeys"] == [[ref("key-dorm", "Dorm room 314 marked key", "314", None)]]
    assert quest["questItem"] == {"id": "folder", "name": "Secure folder", "shortName": "Folder", "iconLink": "f.webp"}
    assert skill["skillLevel"] == {"name": "Endurance", "level": 3}
    assert ll["trader"]["name"] == "Therapist" and ll["level"] == 2
    rewards = debut["finishRewards"]
    assert rewards["items"] == [{"count": 1, "item": LEDX}]
    assert rewards["traderStanding"][0]["trader"]["name"] == "Prapor" and rewards["traderStanding"][0]["standing"] == 0.02
    assert rewards["offerUnlock"] == [{"level": 1, "trader": debut["trader"], "item": PS}]
    assert rewards["skillLevelReward"] == [{"name": "Endurance", "level": 1}]
    assert rewards["traderUnlock"][0]["name"] == "Therapist"
    assert rewards["craftUnlock"][0]["station"]["name"] == "Medstation"
    assert rewards["craftUnlock"][0]["rewardItems"] == [{"count": 60, "item": PS}]
    shortage = tasks["shortage"]
    assert shortage["map"] is None
    assert shortage["taskRequirements"] == [{"task": {"id": "debut", "name": "Debut"}, "status": ["complete"]}]
    assert shortage["traderRequirements"][0]["trader"]["name"] == "Therapist"


def test_hideout_barters_crafts():
    client = StaticClient()
    (med,) = staticapi.hideout(client)
    assert med["name"] == "Medstation" and med["imageLink"] == "med.webp"
    lvl = med["levels"][0]
    assert lvl["description"] == "Basic healing" and lvl["constructionTime"] == 7200
    assert lvl["itemRequirements"] == [{"count": 1, "item": LEDX,
                                        "attributes": [{"type": "foundInRaid", "name": "foundInRaid", "value": "true"}]}]
    assert lvl["stationLevelRequirements"][0]["station"]["name"] == "Medstation"
    assert lvl["traderRequirements"][0]["trader"]["name"] == "Therapist" and lvl["traderRequirements"][0]["value"] == 2
    assert lvl["skillRequirements"] == [{"name": "Endurance", "level": 2}]
    assert lvl["bonuses"][0]["name"] == "Health regeneration"

    (barter,) = staticapi.barters(client)
    assert barter["level"] == 2 and barter["buyLimit"] == 3 and barter["trader"]["name"] == "Prapor"
    assert barter["taskUnlock"] == {"id": "debut", "name": "Debut"}
    assert barter["requiredItems"] == [{"count": 1, "attributes": [], "item": LEDX}]
    assert barter["rewardItems"] == [{"count": 120, "attributes": [], "item": PS}]

    (craft,) = staticapi.crafts(client)
    assert craft["station"]["name"] == "Medstation" and craft["duration"] == 3600 and craft["taskUnlock"] is None
    assert craft["requiredItems"][0]["attributes"] == [{"type": "tool", "name": "tool", "value": "true"}]
    assert craft["rewardItems"] == [{"count": 60, "attributes": [], "item": PS}]


def test_maps_bosses_goons():
    client = StaticClient()
    maps = {m["normalizedName"]: m for m in staticapi.maps(client)}
    customs = maps["customs"]
    assert customs["name"] == "Customs" and customs["nameId"] == "bigmap" and customs["enemies"] == ["Scavs", "PMCs"]
    (spawn,) = customs["bosses"]
    assert spawn["boss"] == {"id": "reshala", "name": "Reshala", "normalizedName": "reshala", "imagePortraitLink": "r.webp"}
    assert spawn["spawnTrigger"] == "Opening the door" and spawn["spawnLocations"] == [{"name": "Dorms", "chance": 0.5}]
    assert spawn["escorts"] == [{"boss": {"id": "guard", "name": "Guard", "normalizedName": "guard"},
                                 "amount": [{"count": 4, "chance": 1}]}]
    assert customs["extracts"] == [{"id": "ex1", "name": "Crossroads", "faction": "pmc"}]
    assert customs["transits"] == [{"id": "tr1", "description": "To Woods", "conditions": "Pay 5000 roubles",
                                    "map": {"id": "woods", "name": "Woods", "normalizedName": "woods"}}]
    assert customs["locks"][0]["key"]["name"] == "Dorm room 314 marked key"
    assert customs["hazards"] == [{"hazardType": "minefield", "name": "Minefield"}]

    bosses = {b["id"]: b for b in staticapi.bosses(client)}
    assert bosses["reshala"]["health"] == [{"bodyPart": "Head", "max": 35}]
    assert bosses["reshala"]["equipment"] == [{"count": 30, "item": PS}]

    goons = staticapi.goons(client)
    assert [g["map"]["name"] for g in goons] == ["Customs", "Woods"]  # newest first


def test_traders_offers_ammo_flea_status_achievements():
    client = StaticClient()
    traders = {t["id"]: t for t in staticapi.traders(client)}
    assert traders["prapor"]["name"] == "Prapor" and traders["prapor"]["resetTime"] == "2026-10-08T21:00:00.000Z"
    assert traders["prapor"]["currency"] == {"id": "RUB", "name": "Roubles", "shortName": "RUB"}
    assert traders["prapor"]["levels"][0]["payRate"] == 0.5

    (offers,) = staticapi.cashoffers(client)
    assert offers["name"] == "Therapist"
    assert offers["cashOffers"] == [{"minTraderLevel": 4, "price": 1000, "currency": "USD", "priceRUB": 140000,
                                     "buyLimit": 1, "taskUnlock": {"id": "shortage", "name": "Shortage"}, "item": LEDX}]

    (ps,) = staticapi.ammo(client)
    assert ps["item"] == PS and ps["caliber"] == "Caliber545x39" and ps["penetrationPower"] == 30 and ps["damage"] == 50

    assert staticapi.flea(client)["sellOfferFeeRate"] == 0.05
    assert staticapi.status(client)["currentStatuses"][0]["name"] == "Trading"
    (ach,) = staticapi.achievements(client)
    assert ach["name"] == "Welcome" and ach["side"] == "PMC" and ach["rarity"] == "Common" and ach["normalizedSide"] == "pmc"


def test_files_are_downloaded_once_for_all_datasets():
    client = StaticClient()
    staticapi.tasks(client)
    staticapi.hideout(client)
    staticapi.barters(client)
    assert client.urls.count(STATIC_URL + "regular/items") == 1
    assert client.urls.count(STATIC_URL + "regular/items_en") == 1


def test_pve_uses_pve_files():
    data = {k.replace("regular/", "pve/"): v for k, v in files().items()}
    client = StaticClient("pve", data=data)
    assert staticapi.tasks(client)
    assert all("/regular/" not in u for u in client.urls)


# -- the app uses them first ----------------------------------------------------------------------

def test_datastore_prefers_files_and_falls_back_to_graphql(tmp_path):
    client = StaticClient()
    store = DataStore(tmp_path, "regular", client)
    assert store.refresh("tasks")["data"][0]["trader"]["name"] in ("Prapor", "Therapist")
    assert client.queries == []  # GraphQL not needed

    # A missing file: GraphQL answers instead.
    staticapi.clear_cache()  # downloads are shared by all clients
    broken = StaticClient(data={}, graphql={"hideoutStations": [{"id": "from-graphql"}]})
    snap = DataStore(tmp_path / "b", "regular", broken).refresh("hideout")
    assert snap["data"] == [{"id": "from-graphql"}] and broken.queries

    # Both down: the error names both.
    snap = DataStore(tmp_path / "c", "regular", StaticClient(data={})).refresh("barters")
    assert snap["data"] is None and "Data file" in snap["error"] and "GraphQL server unavailable" in snap["error"]


def test_item_details_from_files(tmp_path):
    client = StaticClient()
    store = DataStore(tmp_path, "regular", client)
    for name in ("tasks", "barters", "crafts"):
        store.refresh(name)
    result = store.item("ledx")
    item = result["item"]
    assert item["name"] == "LEDX Skin Transilluminator" and item["description"] == "A medical device"
    assert item["category"] == {"name": "Medical supplies"} and item["high24hPrice"] == 1100000
    assert item["sellFor"][0] == {"price": 950000, "currency": "RUB", "priceRUB": 950000,
                                  "vendor": {"name": "Flea Market", "normalizedName": "flea-market"}}
    assert [o["vendor"]["name"] for o in item["sellFor"][1:]] == ["Therapist", "Prapor"]
    trader_buy = item["buyFor"][1]
    assert trader_buy["vendor"]["minTraderLevel"] == 4 and trader_buy["vendor"]["taskUnlock"]["name"] == "Shortage"
    assert [t["name"] for t in item["usedInTasks"]] == ["Debut"]
    assert [t["name"] for t in item["receivedFromTasks"]] == ["Debut"]
    assert [b["id"] for b in item["bartersUsing"]] == ["barter-1"] and item["bartersFor"] == []
    assert [c["id"] for c in item["craftsUsing"]] == ["craft-1"]
    assert [p["price"] for p in result["history"]] == [990000]  # last 7 days only
    assert client.queries == []


def test_prices_from_files_for_pve_and_as_pvp_fallback():
    data = {k.replace("regular/", "pve/"): v for k, v in files().items()}
    pve = PriceDB(game_mode="pve")
    pve.client = StaticClient("pve", data=data)
    assert pve.refresh() is True and pve.error is None
    ledx = next(i for i in pve.items if i.id == "ledx")
    assert ledx.name == "LEDX Skin Transilluminator" and ledx.flea_price == 1000000
    assert ledx.best_trader == "Therapist" and ledx.best_trader_price == 80000
    assert ledx.hideout == ["Medstation 1 x1"] and ledx.quests == ["Debut x2 FiR"]
    assert pve.client.queries == []

    # PvP: the plain item list fails, the data file answers.
    pvp = PriceDB()
    pvp.client = StaticClient()
    assert pvp.refresh() is True
    assert any(i.id == "ammo-ps" for i in pvp.items) and pvp.client.queries == []


def test_records_kept_in_lists_work_too():
    data = files()
    data["regular/traders"]["data"] = list(data["regular/traders"]["data"].values())
    data["regular/tasks"]["data"]["questItems"] = list(data["regular/tasks"]["data"]["questItems"].values())
    data["regular/maps"]["data"]["mobs"] = list(data["regular/maps"]["data"]["mobs"].values())
    data["regular/traders"]["translations"] = ["$.data[*].name"]
    client = StaticClient(data=data)
    debut = next(t for t in staticapi.tasks(client) if t["id"] == "debut")
    assert debut["trader"]["name"] == "Prapor"
    assert debut["objectives"][5]["questItem"]["name"] == "Secure folder"
    assert staticapi.maps(client)[0]["bosses"][0]["boss"]["name"] == "Reshala"
