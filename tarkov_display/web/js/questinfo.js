// How and where to do quest objectives, and what a raid plan needs.

import { itemChip } from "./components.js";
import { ext, h, icon, stepper } from "./lib.js";
import { peek, setProgress, store } from "./store.js";

const MAP_URL = "https://tarkov.dev/map/";

// tarkov.dev's data can change shape. Read every list through these, so one
// odd objective shows less instead of blanking the whole page.
export const list = (x) => (Array.isArray(x) ? x : []);
export const objs = (x) => list(x).filter((v) => v && typeof v === "object" && !Array.isArray(v));
const itemGroups = (x) => list(x).map(objs).filter((g) => g.length);
const text = (x) => (typeof x === "string" || typeof x === "number" ? String(x) : "");
const CMP = { ">=": "at least", ">": "more than", "<=": "at most", "<": "less than", "=": "exactly", "==": "exactly" };

// Objectives done in raid (the rest happen at traders, in the hideout or over time).
const IN_RAID = new Set(["shoot", "extract", "findItem", "findQuestItem", "mark", "plantItem", "plantQuestItem",
  "visit", "useItem", "experience"]);

export function isInRaid(o) {
  return IN_RAID.has(o.type) || objectiveMapIds(o).length > 0;
}

function words(items, joiner = "or") {
  const xs = list(items).map(text).filter(Boolean);
  if (xs.length <= 1) return xs[0] || "";
  return `${xs.slice(0, -1).join(", ")} ${joiner} ${xs[xs.length - 1]}`;
}

const hour = (n) => `${String(n).padStart(2, "0")}:00`;
const cmp = (c, v, unit = "") => `${CMP[c] || c || ""} ${v}${unit}`.trim();

function mapIndex() {
  return new Map(objs(peek("maps")).map((m) => [m.id, m]));
}

// Every map an objective takes place on (ids).
export function objectiveMapIds(o) {
  const ids = new Set(objs(o.maps).map((m) => m.id).filter(Boolean));
  for (const z of objs(o.zones)) if (z.map?.id) ids.add(z.map.id);
  for (const loc of objs(o.possibleLocations)) if (loc.map?.id) ids.add(loc.map.id);
  return [...ids];
}

// Maps a quest involves (its own map and its objectives' maps).
export function taskMapIds(task) {
  const ids = new Set(task.map?.id ? [task.map.id] : []);
  for (const o of objs(task.objectives)) for (const id of objectiveMapIds(o)) ids.add(id);
  return [...ids];
}

// Is this objective part of a raid on `mapId`? (Objectives with no map work anywhere.)
export function onMap(o, mapId) {
  if (!mapId) return true;
  const ids = objectiveMapIds(o);
  return !ids.length || ids.includes(mapId);
}

// -- progress on single objectives ------------------------------------------------------------

export function objectiveTarget(o) {
  return Math.max(1, Number(o.count) || 1);
}

export function objectiveProgress(o) {
  return Math.min(objectiveTarget(o), (store.progress?.objectives || {})[o.id] || 0);
}

export function objectiveDone(o) {
  return objectiveProgress(o) >= objectiveTarget(o);
}

function progressControl(o) {
  const target = objectiveTarget(o), have = objectiveProgress(o);
  const set = (n) => setProgress({ op: "objective", id: o.id, count: Math.max(0, Math.min(target, n)) });
  if (target === 1) {
    return h("button.obj-check" + (have ? ".on" : ""), { type: "button", title: have ? "Mark not done" : "Mark done",
      onclick: (e) => { e.stopPropagation(); set(have ? 0 : 1); } }, have ? icon("check", 14) : null);
  }
  return h("div.obj-count", { onclick: (e) => e.stopPropagation() }, stepper(have, 0, target, set), h("span.muted.small", `/ ${target}`));
}

// -- how ----------------------------------------------------------------------------------------

function chips(items, count, full = false) {
  return h("span.obj-items.inline", objs(items).slice(0, 12).map((it) => itemChip(it, count ?? null, { compact: true, fullName: full })));
}

function line(label, ...content) {
  return h("div.how-line", h("span.how-label", label), h("span.how-body", ...content));
}

function effectText(e, who) {
  if (!e || typeof e !== "object") return null;
  const parts = `${words(e.effects, "and")}${words(e.bodyParts) ? ` on ${who === "you" ? "your" : "their"} ${words(e.bodyParts)}` : ""}`;
  const time = e.time && typeof e.time === "object" && e.time.value != null ? ` for ${cmp(e.time.compareMethod, e.time.value, " s")}` : "";
  return `${who === "you" ? "You have" : "Target has"} ${parts}${time}`;
}

// Lines that spell out what the game checks for an objective.
export function objectiveHow(o) {
  const out = [];
  const n = o.count > 1 ? `${o.count}× ` : "";
  switch (o.type) {
    case "shoot": {
      const targets = words(o.targetNames) || "targets";
      out.push(line(o.shotType === "kill" || !o.shotType ? "Kill" : "Hit", `${n}${targets}`));
      if (words(o.bodyParts)) out.push(line("Hits to", words(o.bodyParts)));
      if (o.distance && o.distance.value) out.push(line("Range", `from ${cmp(o.distance.compareMethod, o.distance.value, " m")}`));
      if (o.timeFromHour != null && o.timeUntilHour != null && o.timeFromHour !== o.timeUntilHour) {
        out.push(line("Time", `between ${hour(o.timeFromHour)} and ${hour(o.timeUntilHour)} (in-game)`));
      }
      const weapons = objs(o.usingWeapon), wearing = itemGroups(o.wearing);
      if (weapons.length) out.push(line(weapons.length > 1 ? "Weapon (any)" : "Weapon", chips(weapons)));
      for (const mods of itemGroups(o.usingWeaponMods)) out.push(line("With mods", chips(mods)));
      if (wearing.length) {
        out.push(line(wearing.length > 1 ? "Wearing (any)" : "Wearing",
          ...wearing.map((set, i) => [i ? h("span.muted", " or ") : null, chips(set)])));
      }
      if (objs(o.notWearing).length) out.push(line("Not wearing", chips(o.notWearing)));
      if (o.playerHealthEffect) out.push(line("While", effectText(o.playerHealthEffect, "you")));
      if (o.enemyHealthEffect) out.push(line("While", effectText(o.enemyHealthEffect, "them")));
      break;
    }
    case "extract": {
      const status = words(o.exitStatus) || "Survived";
      out.push(line("Extract", `${o.count > 1 ? `${o.count} times ` : ""}with status: ${status}`));
      if (text(o.exitName)) out.push(line("Exit", text(o.exitName)));
      break;
    }
    case "giveItem": case "findItem": case "haveItem": case "sellItem": {
      const verb = { giveItem: "Hand over", findItem: "Find", haveItem: "Have", sellItem: "Sell" }[o.type];
      const many = objs(o.items).length > 1;
      out.push(line(verb, `${o.count || 1}×${many ? " any of" : ""}`, chips(o.items),
        o.foundInRaid ? h("span.fir", { title: "Found in raid" }, "FiR") : null));
      if (o.dogTagLevel) out.push(line("Dogtag", `level ${o.dogTagLevel} or higher`));
      if (o.minDurability || (o.maxDurability && o.maxDurability < 100)) {
        out.push(line("Durability", `${o.minDurability || 0}–${o.maxDurability ?? 100}%`));
      }
      break;
    }
    case "plantItem":
      out.push(line("Place", `${n}`, chips(o.items)));
      break;
    case "mark":
      out.push(line("Mark with", chips([o.markerItem])));
      break;
    case "findQuestItem": case "giveQuestItem": case "plantQuestItem": {
      const verb = { findQuestItem: "Find", giveQuestItem: "Hand over", plantQuestItem: "Place" }[o.type];
      out.push(line(verb, chips([o.questItem], null, true)));
      break;
    }
    case "useItem":
      out.push(line(o.useAny?.length > 1 ? "Use any of" : "Use", `${n}`, chips(o.useAny)));
      break;
    case "visit":
      out.push(line("Go to", words(o.zoneNames) || "the place in the description"));
      break;
    case "buildWeapon":
      out.push(line("Build", chips([o.item])));
      for (const a of objs(o.attributes)) {
        if (a?.requirement?.value) out.push(line(a.name, cmp(a.requirement.compareMethod, a.requirement.value)));
      }
      if (objs(o.containsAll).length) out.push(line("With parts", chips(o.containsAll)));
      if (words(objs(o.containsCategory).map((c) => c.name))) out.push(line("And a", words(objs(o.containsCategory).map((c) => c.name))));
      break;
    case "experience":
      if (o.healthEffect) out.push(line("Have", effectText(o.healthEffect, "you").replace(/^You have /, "")));
      break;
    case "skill":
      if (text(o.skillLevel?.name)) out.push(line("Skill", `${text(o.skillLevel.name)} level ${text(o.skillLevel.level) || "?"}`));
      break;
    case "traderLevel":
      out.push(line("Trader", `${o.trader?.name || "Trader"} loyalty level ${o.level}`));
      break;
    case "traderStanding":
      out.push(line("Standing", `${o.trader?.name || "Trader"} ${cmp(o.compareMethod, o.value)}`));
      break;
    case "taskStatus":
      out.push(line("Quest", `${o.task?.name || "another quest"}: ${words(o.status)}`));
      break;
    case "playerLevel":
      out.push(line("Level", `reach level ${o.playerLevel}`));
      break;
    case "hideoutStation":
      out.push(line("Hideout", `build ${o.hideoutStation?.name || "the station"} level ${o.stationLevel}`));
      break;
    default:
      break;
  }
  return out;
}

// -- where ------------------------------------------------------------------------------------

// The map (normalizedName) an objective is on, if one.
function objectiveMapNorm(o, task) {
  const maps = mapIndex();
  const ids = objectiveMapIds(o);
  const mapId = ids[0] || task?.map?.id;
  if (!mapId) return null;
  return objs(o.maps).find((m) => m.id === mapId)?.normalizedName || maps.get(mapId)?.normalizedName
    || (task?.map?.id === mapId ? task.map.normalizedName : null);
}

// Link to tarkov.dev's interactive map with this objective's spots highlighted.
export function mapLink(o, task) {
  const norm = objectiveMapNorm(o, task);
  if (!norm) return null;
  const q = objs(o.zones).map((z) => z.id).filter(Boolean);
  if (o.type === "findQuestItem" && o.questItem?.id) q.push(o.questItem.id);
  return `${MAP_URL}${norm}${q.length ? `?q=${encodeURIComponent([...new Set(q)].join(","))}` : ""}`;
}

export function objectiveWhere(o, task) {
  const maps = mapIndex();
  const name = (id) => maps.get(id)?.name || objs(o.maps).find((m) => m.id === id)?.name || (task?.map?.id === id ? task.map.name : null);
  const ids = objectiveMapIds(o);
  const out = [];
  if (ids.length) {
    const what = o.type === "findQuestItem" ? "Spawns on" : "Map";
    out.push(line(what, words(ids.map(name).filter(Boolean)) || "–"));
  } else if (isInRaid(o)) {
    out.push(line("Map", "any map"));
  }
  if (words(o.zoneNames) && o.type !== "visit") out.push(line(o.type === "shoot" ? "Inside" : "Area", words(o.zoneNames)));
  for (const group of itemGroups(o.requiredKeys)) {
    out.push(line(group.length > 1 ? "Key (any)" : "Key", chips(group, null, true)));
  }
  const link = (ids.length || objs(o.zones).length) ? mapLink(o, task) : null;
  // The app's own map, zoomed to this quest's markers, when tarkov.dev has the spots.
  const spots = objs(o.zones).some((z) => z.position) || objs(o.possibleLocations).some((l) => list(l.positions).length);
  const norm = spots && task?.id ? objectiveMapNorm(o, task) : null;
  const here = norm ? h("a", { href: `#/maps/${norm}?quest=${encodeURIComponent(task.id)}` }, "Show on the map") : null;
  if (link || here) {
    out.push(h("div.how-line", h("span.how-label"), here, here && link ? h("span.muted", " · ") : null,
      link ? ext(link, objs(o.zones).length || o.type === "findQuestItem" ? "Show the spot on tarkov.dev's map" : "Open the map on tarkov.dev") : null));
  }
  return out;
}

// -- one objective --------------------------------------------------------------------------------

export function objectiveView(o, task, { track = false, fail = false } = {}) {
  const tracked = track && !!o.id;
  const done = tracked && objectiveDone(o);
  return h("li.obj.rich" + (o.optional ? ".optional" : "") + (done ? ".done" : "") + (fail ? ".fail" : ""),
    tracked ? progressControl(o) : h("span.obj-dot"),
    h("div.obj-main",
      h("div.obj-text", text(o.description) || text(o.type) || "Objective", o.optional ? h("span.muted", " (optional)") : null),
      h("div.how", ...objectiveHow(o), ...objectiveWhere(o, task))));
}

// tarkov.dev builds this list from the objectives' keys, so only show keys no objective lists.
export function neededKeysView(task) {
  const shown = new Set(objs(task.objectives).flatMap((o) => itemGroups(o.requiredKeys).flat()).map((k) => k.id));
  const groups = objs(task.neededKeys).map((g) => ({ ...g, keys: objs(g.keys).filter((k) => !shown.has(k.id)) }))
    .filter((g) => g.keys.length);
  if (!groups.length) return null;
  return h("div", { style: { marginTop: "14px" } }, h("div.section-title", "Keys this quest needs"),
    h("div.how", groups.map((g) => line(text(g.map?.name) || "Any map", chips(g.keys, null, true)))));
}

export function failView(task) {
  const fails = objs(task.failConditions);
  if (!fails.length) return null;
  return h("div", { style: { marginTop: "14px" } }, h("div.section-title", "Fails if"),
    h("ul.obj-list", fails.map((o) => objectiveView(o, task, { fail: true }))));
}

// -- what a raid needs --------------------------------------------------------------------------

function addKit(map, key, entry) {
  const have = map.get(key);
  if (have) {
    have.count += entry.count;
    for (const q of entry.quests) if (!have.quests.includes(q)) have.quests.push(q);
  } else {
    map.set(key, { ...entry, quests: [...entry.quests] });
  }
}

// Items to take into a raid on `mapId` for these quests, and what to look for there.
export function raidKit(tasks, mapId) {
  const bring = new Map(), find = new Map();
  for (const task of tasks) {
    for (const o of objs(task.objectives)) {
      if (objectiveDone(o)) continue;
      const here = onMap(o, mapId);
      const quests = [task.name];
      const n = Math.max(1, Number(o.count) || 1);
      const items = objs(o.items), useAny = objs(o.useAny), weapons = objs(o.usingWeapon);
      if (here) {
        for (const group of itemGroups(o.requiredKeys)) {
          addKit(bring, "key:" + group.map((k) => k.id).sort().join("|"), { kind: "Key", items: group, count: 1, quests });
        }
        const marker = objs([o.markerItem])[0], questItem = objs([o.questItem])[0];
        if (o.type === "mark" && marker) addKit(bring, "mark:" + marker.id, { kind: "Marker", items: [marker], count: 1, quests });
        if (o.type === "plantItem" && items.length) {
          addKit(bring, "plant:" + items.map((i) => i.id).sort().join("|"), { kind: "To place", items, count: n, quests });
        }
        if (o.type === "useItem" && useAny.length) {
          addKit(bring, "use:" + useAny.map((i) => i.id).sort().join("|"), { kind: "To use", items: useAny, count: n, quests });
        }
        if (o.type === "shoot" && weapons.length) {
          addKit(bring, "weapon:" + weapons.map((i) => i.id).sort().join("|"), { kind: "Weapon", items: weapons, count: 1, quests });
        }
        if (o.type === "shoot") {
          for (const set of itemGroups(o.wearing)) {
            addKit(bring, "wear:" + set.map((i) => i.id).sort().join("|"), { kind: "Wear", items: set, count: 1, quests, all: true });
          }
        }
        if (o.type === "findQuestItem" && questItem) {
          addKit(find, "quest:" + questItem.id, { kind: "Quest item", items: [questItem], count: n, quests });
        }
      }
      if ((o.type === "giveItem" || o.type === "findItem") && o.foundInRaid && items.length) {
        addKit(find, "fir:" + items.map((i) => i.id).sort().join("|"), { kind: "Found in raid", items, count: n, quests });
      }
    }
  }
  return { bring: [...bring.values()], find: [...find.values()] };
}

export function kitList(entries, emptyText) {
  if (!entries.length) return h("div.muted.small", emptyText);
  return h("div.list", entries.map((e) => h("div.list-row.kit-row",
    h("span.kit-kind", e.kind),
    h("div.grow",
      h("div.obj-items", e.items.slice(0, 8).map((it, i) => [
        i ? h("span.muted.small", e.all ? "+" : "or") : null,
        itemChip(it, i === 0 && e.count > 1 ? e.count : null, { compact: true, fullName: e.kind === "Key" || e.kind === "Quest item" })])),
      h("div.muted.small", e.quests.join(" · "))))));
}
