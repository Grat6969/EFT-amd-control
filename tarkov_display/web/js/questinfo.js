// How and where to do quest objectives, and what a raid plan needs.

import { itemChip } from "./components.js";
import { ext, h, icon, stepper } from "./lib.js";
import { peek, setProgress, store } from "./store.js";

const MAP_URL = "https://tarkov.dev/map/";
const CMP = { ">=": "at least", ">": "more than", "<=": "at most", "<": "less than", "=": "exactly", "==": "exactly" };

// Objectives done in raid (the rest happen at traders, in the hideout or over time).
const IN_RAID = new Set(["shoot", "extract", "findItem", "findQuestItem", "mark", "plantItem", "plantQuestItem",
  "visit", "useItem", "experience"]);

export function isInRaid(o) {
  return IN_RAID.has(o.type) || objectiveMapIds(o).length > 0;
}

function words(list, joiner = "or") {
  const xs = (list || []).filter(Boolean);
  if (xs.length <= 1) return xs[0] || "";
  return `${xs.slice(0, -1).join(", ")} ${joiner} ${xs[xs.length - 1]}`;
}

const hour = (n) => `${String(n).padStart(2, "0")}:00`;
const cmp = (c, v, unit = "") => `${CMP[c] || c || ""} ${v}${unit}`.trim();

function mapIndex() {
  return new Map((peek("maps") || []).map((m) => [m.id, m]));
}

// Every map an objective takes place on (ids).
export function objectiveMapIds(o) {
  const ids = new Set((o.maps || []).map((m) => m?.id).filter(Boolean));
  for (const z of o.zones || []) if (z?.map?.id) ids.add(z.map.id);
  for (const loc of o.possibleLocations || []) if (loc?.map?.id) ids.add(loc.map.id);
  return [...ids];
}

// Maps a quest involves (its own map and its objectives' maps).
export function taskMapIds(task) {
  const ids = new Set(task.map?.id ? [task.map.id] : []);
  for (const o of task.objectives || []) for (const id of objectiveMapIds(o)) ids.add(id);
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
  return h("span.obj-items.inline", (items || []).filter(Boolean).slice(0, 12).map((it) => itemChip(it, count ?? null, { compact: true, fullName: full })));
}

function line(label, ...content) {
  return h("div.how-line", h("span.how-label", label), h("span.how-body", ...content));
}

function effectText(e, who) {
  if (!e) return null;
  const parts = `${words(e.effects, "and")}${e.bodyParts?.length ? ` on ${who === "you" ? "your" : "their"} ${words(e.bodyParts)}` : ""}`;
  const time = e.time ? ` for ${cmp(e.time.compareMethod, e.time.value, " s")}` : "";
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
      if (o.bodyParts?.length) out.push(line("Hits to", words(o.bodyParts)));
      if (o.distance && o.distance.value) out.push(line("Range", `from ${cmp(o.distance.compareMethod, o.distance.value, " m")}`));
      if (o.timeFromHour != null && o.timeUntilHour != null && o.timeFromHour !== o.timeUntilHour) {
        out.push(line("Time", `between ${hour(o.timeFromHour)} and ${hour(o.timeUntilHour)} (in-game)`));
      }
      if (o.usingWeapon?.length) out.push(line(o.usingWeapon.length > 1 ? "Weapon (any)" : "Weapon", chips(o.usingWeapon)));
      for (const mods of o.usingWeaponMods || []) if (mods?.length) out.push(line("With mods", chips(mods)));
      if (o.wearing?.length) {
        out.push(line(o.wearing.length > 1 ? "Wearing (any)" : "Wearing",
          ...o.wearing.map((set, i) => [i ? h("span.muted", " or ") : null, chips(set)])));
      }
      if (o.notWearing?.length) out.push(line("Not wearing", chips(o.notWearing)));
      if (o.playerHealthEffect) out.push(line("While", effectText(o.playerHealthEffect, "you")));
      if (o.enemyHealthEffect) out.push(line("While", effectText(o.enemyHealthEffect, "them")));
      break;
    }
    case "extract": {
      const status = words(o.exitStatus) || "Survived";
      out.push(line("Extract", `${o.count > 1 ? `${o.count} times ` : ""}with status: ${status}`));
      if (o.exitName) out.push(line("Exit", o.exitName));
      break;
    }
    case "giveItem": case "findItem": case "haveItem": case "sellItem": {
      const verb = { giveItem: "Hand over", findItem: "Find", haveItem: "Have", sellItem: "Sell" }[o.type];
      const many = (o.items || []).length > 1;
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
      for (const a of o.attributes || []) {
        if (a?.requirement?.value) out.push(line(a.name, cmp(a.requirement.compareMethod, a.requirement.value)));
      }
      if (o.containsAll?.length) out.push(line("With parts", chips(o.containsAll)));
      if (o.containsCategory?.length) out.push(line("And a", words(o.containsCategory.map((c) => c.name))));
      break;
    case "experience":
      if (o.healthEffect) out.push(line("Have", effectText(o.healthEffect, "you").replace(/^You have /, "")));
      break;
    case "skill":
      if (o.skillLevel) out.push(line("Skill", `${o.skillLevel.name} level ${o.skillLevel.level}`));
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

// Link to tarkov.dev's interactive map with this objective's spots highlighted.
export function mapLink(o, task) {
  const maps = mapIndex();
  const ids = objectiveMapIds(o);
  const mapId = ids[0] || task?.map?.id;
  const norm = (o.maps || []).find((m) => m?.id === mapId)?.normalizedName || maps.get(mapId)?.normalizedName
    || (task?.map?.id === mapId ? task.map.normalizedName : null);
  if (!norm) return null;
  const q = (o.zones || []).map((z) => z?.id).filter(Boolean);
  if (o.type === "findQuestItem" && o.questItem?.id) q.push(o.questItem.id);
  return `${MAP_URL}${norm}${q.length ? `?q=${encodeURIComponent([...new Set(q)].join(","))}` : ""}`;
}

export function objectiveWhere(o, task) {
  const maps = mapIndex();
  const name = (id) => maps.get(id)?.name || (o.maps || []).find((m) => m?.id === id)?.name || (task?.map?.id === id ? task.map.name : null);
  const ids = objectiveMapIds(o);
  const out = [];
  if (ids.length) {
    const what = o.type === "findQuestItem" ? "Spawns on" : "Map";
    out.push(line(what, words(ids.map(name).filter(Boolean)) || "–"));
  } else if (isInRaid(o)) {
    out.push(line("Map", "any map"));
  }
  if (o.zoneNames?.length && o.type !== "visit") out.push(line(o.type === "shoot" ? "Inside" : "Area", words(o.zoneNames)));
  for (const group of o.requiredKeys || []) {
    if (group?.length) out.push(line(group.length > 1 ? "Key (any)" : "Key", chips(group, null, true)));
  }
  const link = (ids.length || o.zones?.length) ? mapLink(o, task) : null;
  if (link) out.push(h("div.how-line", h("span.how-label"), ext(link, o.zones?.length || o.type === "findQuestItem" ? "Show the spot on tarkov.dev's map" : "Open the map on tarkov.dev")));
  return out;
}

// -- one objective --------------------------------------------------------------------------------

export function objectiveView(o, task, { track = false, fail = false } = {}) {
  const tracked = track && !!o.id;
  const done = tracked && objectiveDone(o);
  return h("li.obj.rich" + (o.optional ? ".optional" : "") + (done ? ".done" : "") + (fail ? ".fail" : ""),
    tracked ? progressControl(o) : h("span.obj-dot"),
    h("div.obj-main",
      h("div.obj-text", o.description || o.type, o.optional ? h("span.muted", " (optional)") : null),
      h("div.how", ...objectiveHow(o), ...objectiveWhere(o, task))));
}

// tarkov.dev builds this list from the objectives' keys, so only show keys no objective lists.
export function neededKeysView(task) {
  const shown = new Set((task.objectives || []).flatMap((o) => (o.requiredKeys || []).flat()).map((k) => k?.id));
  const groups = (task.neededKeys || []).map((g) => ({ ...g, keys: (g?.keys || []).filter((k) => k && !shown.has(k.id)) }))
    .filter((g) => g.keys.length);
  if (!groups.length) return null;
  return h("div", { style: { marginTop: "14px" } }, h("div.section-title", "Keys this quest needs"),
    h("div.how", groups.map((g) => line(g.map?.name || "Any map", chips(g.keys, null, true)))));
}

export function failView(task) {
  const fails = task.failConditions || [];
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
    for (const o of task.objectives || []) {
      if (objectiveDone(o)) continue;
      const here = onMap(o, mapId);
      const quests = [task.name];
      if (here) {
        for (const group of o.requiredKeys || []) {
          if (group?.length) addKit(bring, "key:" + group.map((k) => k.id).sort().join("|"), { kind: "Key", items: group, count: 1, quests });
        }
        if (o.type === "mark" && o.markerItem) addKit(bring, "mark:" + o.markerItem.id, { kind: "Marker", items: [o.markerItem], count: 1, quests });
        if (o.type === "plantItem" && o.items?.length) {
          addKit(bring, "plant:" + o.items.map((i) => i.id).sort().join("|"), { kind: "To place", items: o.items, count: o.count || 1, quests });
        }
        if (o.type === "useItem" && o.useAny?.length) {
          addKit(bring, "use:" + o.useAny.map((i) => i.id).sort().join("|"), { kind: "To use", items: o.useAny, count: o.count || 1, quests });
        }
        if (o.type === "shoot" && o.usingWeapon?.length) {
          addKit(bring, "weapon:" + o.usingWeapon.map((i) => i.id).sort().join("|"), { kind: "Weapon", items: o.usingWeapon, count: 1, quests });
        }
        if (o.type === "shoot") {
          for (const set of o.wearing || []) {
            if (set?.length) addKit(bring, "wear:" + set.map((i) => i.id).sort().join("|"), { kind: "Wear", items: set, count: 1, quests, all: true });
          }
        }
        if (o.type === "findQuestItem" && o.questItem) {
          addKit(find, "quest:" + o.questItem.id, { kind: "Quest item", items: [o.questItem], count: o.count || 1, quests });
        }
      }
      if ((o.type === "giveItem" || o.type === "findItem") && o.foundInRaid && o.items?.length) {
        addKit(find, "fir:" + o.items.map((i) => i.id).sort().join("|"), { kind: "Found in raid", items: o.items, count: o.count || 1, quests });
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
