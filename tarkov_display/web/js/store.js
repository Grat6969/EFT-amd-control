// App state, data loading and the game logic (prices, quests, needs).

import { api } from "./lib.js";

export const store = {
  boot: null,
  state: {},
  progress: null,
  display: null,
  items: [],
  itemsById: new Map(),
  itemsUpdated: 0,
  itemsError: null,
  data: {},       // dataset name -> {data, updated, error}
  scans: [],
  gameEvents: [],  // from the game log reader / TarkovTracker
};

const listeners = new Set();
export function on(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export function emit(kind, detail) { for (const fn of [...listeners]) { try { fn(kind, detail); } catch (e) { console.error(e); } } }

export async function loadBoot() {
  store.boot = await api("bootstrap");
  store.state = store.boot.state;
  store.progress = store.boot.progress;
  store.display = store.boot.display;
  return store.boot;
}

export async function loadItems() {
  const res = await api("items");
  store.items = res.items;
  store.itemsById = new Map(res.items.map((i) => [i.id, i]));
  store.itemsUpdated = res.updated;
  store.itemsError = res.error;
  indexes.cash = null;
  emit("items");
  return store.items;
}

const pending = {};
export async function dataset(name, { wait = 25 } = {}) {
  const have = store.data[name];
  if (have && have.data) return have.data;
  if (!pending[name]) {
    pending[name] = api(`data/${name}?wait=${wait}`).then((res) => {
      store.data[name] = res;
      if (name === "cashoffers") indexes.cash = null;
      return res;
    }).finally(() => { delete pending[name]; });
  }
  const res = await pending[name];
  if (!res.data) throw new Error(res.error || "No data yet. tarkov.dev hasn't answered; retrying in the background.");
  return res.data;
}

export function peek(name) {
  return store.data[name] ? store.data[name].data : null;
}

export function invalidate(name) {
  if (name === "prices") return;
  delete store.data[name];
  if (name === "cashoffers") indexes.cash = null;
}

export async function setProgress(op) {
  store.progress = await api("progress", { method: "POST", body: op });
  emit("progress");
  return store.progress;
}

export async function displayChange(op) {
  store.display = await api("display", { method: "POST", body: op });
  emit("display");
  return store.display;
}

// -- items and prices -----------------------------------------------------------------

export function item(id) { return store.itemsById.get(id); }

const indexes = { cash: null };

export function cashOffers(id) {
  if (!indexes.cash) {
    const traders = peek("cashoffers");
    if (!traders) return [];
    indexes.cash = new Map();
    for (const t of traders) {
      for (const o of t.cashOffers || []) {
        if (!o.item) continue;
        const list = indexes.cash.get(o.item.id) || [];
        list.push({ trader: t.name, level: o.minTraderLevel || 1, priceRUB: o.priceRUB, price: o.price,
          currency: o.currency, buyLimit: o.buyLimit, taskUnlock: o.taskUnlock });
        indexes.cash.set(o.item.id, list);
      }
    }
  }
  return indexes.cash.get(id) || [];
}

export function fleaPrice(it) {
  if (!it || it.banned) return null;
  return it.avg || it.low || null;
}

// Flea market fee. Formula from tarkov.dev (MIT licence), which follows the
// game wiki: https://escapefromtarkov.fandom.com/wiki/Trading#Fees
export function fleaFee(basePrice, sellPrice, count = 1) {
  if (!basePrice || !sellPrice) return 0;
  const flea = peek("flea") || {};
  const Ti = flea.sellOfferFeeRate ?? 0.03;
  const Tr = flea.sellRequirementFeeRate ?? 0.03;
  const p = store.progress || {};
  const V0 = basePrice, VR = sellPrice;
  let P0 = Math.log10(V0 / VR), PR = Math.log10(VR / V0);
  if (VR < V0) P0 = Math.pow(P0, 1.08);
  if (VR >= V0) PR = Math.pow(PR, 1.08);
  let IC = 1;
  if ((p.intel_center || 0) >= 3) IC = 1 - (0.01 * (p.hideout_management || 0) + 1) * 0.3;
  return Math.round(Math.ceil(V0 * Ti * Math.pow(4, P0) * count + VR * Tr * Math.pow(4, PR) * count) * IC);
}

// Cheapest way to get one: flea (lowest listing) or a trader's cash offer.
export function buyPrice(id) {
  const it = item(id);
  let best = null;
  const flea = it && !it.banned ? (it.low || it.avg) : null;
  if (flea) best = { price: flea, source: "Flea" };
  for (const o of cashOffers(id)) {
    if (o.priceRUB && (!best || o.priceRUB < best.price)) best = { price: o.priceRUB, source: `${o.trader} ${o.level}` };
  }
  return best;
}

// Best you can get for one: flea after fees, or the best trader.
export function sellValue(id) {
  const it = item(id);
  if (!it) return null;
  let best = null;
  const flea = fleaPrice(it);
  if (flea) best = { value: flea - fleaFee(it.base, flea), source: "Flea", gross: flea };
  if (it.traderPrice && (!best || it.traderPrice > best.value)) best = { value: it.traderPrice, source: it.trader };
  return best;
}

export function perSlot(it) {
  const v = Math.max(fleaPrice(it) || 0, it.traderPrice || 0);
  return v ? Math.floor(v / Math.max(1, it.slots || 1)) : 0;
}

export function searchItems(query, limit = 50) {
  const q = (query || "").toLowerCase().trim();
  if (!q) return [];
  const tokens = q.split(/\s+/);
  const scored = [];
  for (const it of store.items) {
    const name = it.name.toLowerCase(), short = (it.short || "").toLowerCase();
    let rank;
    if (short === q || name === q) rank = 0;
    else if (name.startsWith(q) || short.startsWith(q)) rank = 1;
    else if (tokens.every((t) => name.includes(t) || short.includes(t))) rank = 2;
    else continue;
    scored.push([rank, it.tags?.includes("preset") ? 1 : 0, -(fleaPrice(it) || it.traderPrice || 0), it]);
  }
  scored.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]);
  return scored.slice(0, limit).map((s) => s[3]);
}

// -- quests -------------------------------------------------------------------------

export function questContext(tasks) {
  const p = store.progress || { tasks: [], player_level: 1, faction: "USEC" };
  return { byId: new Map(tasks.map((t) => [t.id, t])), done: new Set(p.tasks), level: p.player_level,
    faction: p.faction, memo: new Map() };
}

export function forFaction(task, faction) {
  return !task.factionName || task.factionName === "Any" || task.factionName === faction;
}

// "done" | "available" | "locked" | "other" (other faction)
export function questState(task, ctx, depth = 0) {
  if (ctx.memo.has(task.id)) return ctx.memo.get(task.id);
  let state = "available";
  if (ctx.done.has(task.id)) state = "done";
  else if (!forFaction(task, ctx.faction)) state = "other";
  else if ((task.minPlayerLevel || 0) > ctx.level) state = "locked";
  else {
    for (const r of task.taskRequirements || []) {
      const req = ctx.byId.get(r.task?.id);
      if (!req) continue;
      if ((r.status || []).includes("complete")) {
        if (!ctx.done.has(req.id)) { state = "locked"; break; }
      } else if (depth < 50 && questState(req, ctx, depth + 1) === "locked") {
        state = "locked"; break;
      }
    }
  }
  ctx.memo.set(task.id, state);
  return state;
}

// Every unfinished quest that has to be completed before this one.
export function prerequisites(task, ctx) {
  const out = new Set();
  const walk = (t, depth) => {
    for (const r of t.taskRequirements || []) {
      const req = ctx.byId.get(r.task?.id);
      if (!req || !(r.status || []).includes("complete") || out.has(req.id) || depth > 60) continue;
      if (!ctx.done.has(req.id)) out.add(req.id);
      walk(req, depth + 1);
    }
  };
  walk(task, 0);
  return [...out];
}

export const NEED_TYPES = new Set(["giveItem", "plantItem", "mark"]);

export function objectiveItems(o) {
  if (o.items && o.items.length) return o.items.filter(Boolean);
  if (o.markerItem) return [o.markerItem];
  if (o.questItem) return [o.questItem];
  if (o.item) return [o.item];
  if (o.useAny && o.useAny.length) return o.useAny.filter(Boolean);
  return [];
}

// Items still needed for unfinished quests and unbuilt hideout levels.
export function neededItems({ tasks, stations, kappaOnly = false, source = "all" }) {
  const p = store.progress || { tasks: [], hideout: {}, faction: "USEC" };
  const done = new Set(p.tasks);
  const map = new Map();
  const anyOf = [];
  const add = (it, field, count, ref) => {
    const e = map.get(it.id) || { id: it.id, item: it, quest: 0, questFir: 0, hideout: 0, refs: [] };
    e[field] += count;
    if (field === "quest" && ref.fir) e.questFir += count;
    e.refs.push(ref);
    map.set(it.id, e);
  };
  if (source !== "hideout") {
    for (const t of tasks || []) {
      if (done.has(t.id) || !forFaction(t, p.faction) || (kappaOnly && !t.kappaRequired)) continue;
      for (const o of t.objectives || []) {
        if (!NEED_TYPES.has(o.type) || o.optional) continue;
        const items = objectiveItems(o);
        const count = o.count || 1;
        const ref = { kind: "quest", name: t.name, id: t.id, count, fir: !!o.foundInRaid, trader: t.trader?.name };
        if (items.length === 1) add(items[0], "quest", count, ref);
        else if (items.length > 1) anyOf.push({ ...ref, items });
      }
    }
  }
  if (source !== "quests" && !kappaOnly) {
    for (const s of stations || []) {
      const built = p.hideout[s.id] || 0;
      for (const lvl of s.levels || []) {
        if (lvl.level <= built) continue;
        for (const req of lvl.itemRequirements || []) {
          if (!req.item) continue;
          add(req.item, "hideout", req.count || 1, { kind: "hideout", name: `${s.name} ${lvl.level}`, id: s.id, count: req.count || 1 });
        }
      }
    }
  }
  return { items: [...map.values()], anyOf };
}

export function needsFor(id) {
  const tasks = peek("tasks"), stations = peek("hideout");
  if (!tasks && !stations) return null;
  const { items, anyOf } = neededItems({ tasks, stations });
  const e = items.find((x) => x.id === id);
  const alts = anyOf.filter((a) => a.items.some((i) => i.id === id));
  return { entry: e || null, alternatives: alts };
}

// -- names ----------------------------------------------------------------------------

const CALIBERS = {
  Caliber556x45NATO: "5.56x45 NATO", Caliber545x39: "5.45x39", Caliber762x39: "7.62x39", Caliber762x51: "7.62x51 NATO",
  Caliber762x54R: "7.62x54R", Caliber9x19PARA: "9x19 Parabellum", Caliber9x18PM: "9x18 Makarov", Caliber9x21: "9x21 Gyurza",
  Caliber762x25TT: "7.62x25 Tokarev", Caliber46x30: "4.6x30 HK", Caliber57x28: "5.7x28 FN", Caliber1143x23ACP: ".45 ACP",
  Caliber9x39: "9x39", Caliber366TKM: ".366 TKM", Caliber127x55: "12.7x55", Caliber86x70: ".338 Lapua Magnum",
  Caliber762x35: ".300 Blackout", Caliber12g: "12 gauge", Caliber20g: "20 gauge", Caliber23x75: "23x75 (KS-23)",
  Caliber40x46: "40x46 grenade", Caliber40mmRU: "40mm VOG", Caliber30x29: "30x29 grenade", Caliber26x75: "26x75 flare",
  Caliber9x33R: ".357 Magnum", Caliber68x51: "6.8x51", Caliber127x99: ".50 BMG", Caliber93x64: "9.3x64",
  Caliber20x1mm: "20x1mm (toy)", Caliber725: "Shrapnel", Caliber127x33: ".50 AE", Caliber25x59: "25x59",
};
export function caliberName(c) {
  if (!c) return "Other";
  return CALIBERS[c] || c.replace(/^Caliber/, "").replace(/(\d)(\d{2})x/, "$1.$2x");
}
