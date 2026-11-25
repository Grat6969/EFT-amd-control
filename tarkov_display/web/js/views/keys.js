// Keys: the keys for a map, best first (marked rooms, keys your quests need,
// then by the loot near their doors), and the keys you have: tick them off,
// add one you just found, or read them off a screenshot of your key tool.

import { itemChip, ownedStepper, thumb } from "../components.js";
import { badge, button, card, empty, errorBox, fmt, h, icon, loading, local, mount, searchInput, select, stat, toast, toggle, TOKEN } from "../lib.js";
import { buyPrice, dataset, on, questContext, questState, searchItems, setProgress, store } from "../store.js";

const MINE = "*mine*";  // the "My keys" choice in the map list
const SKIP_MAP_WORDS = ["Tutorial", "Infected"];
const GOOD = 30;  // loot points near the door (see keyrooms.py) for "good loot"...
const SOME = 10;  // ... and for "some loot"
const TIERS = [
  ["marked", "Marked rooms", "Marked loot spawns: the best keys on the map", "accent"],
  ["quest", "For your quests", "Your open quests need these", "info"],
  ["good", "Good loot near the door", "Safes, weapon boxes, valuable loose loot", "good"],
  ["some", "Some loot near the door", "", "muted"],
  ["little", "Little behind the door", "Hardly any containers or loot near it", "muted"],
  ["unknown", "No loot data", "tarkov.dev's map data doesn't place loot near these doors", "muted"],
];
const state = { map: local.get("keys.map", null), q: "", mine: false };
let reading = null;  // the screenshot being read, and what was found (survives redraws)

export default {
  title: "Keys",
  subtitle: "The best keys for each map, and the keys you have",
  async render(root) {
    mount(root, loading("Loading maps and keys…"));
    let maps, tasks;
    try {
      [maps, tasks] = await Promise.all([dataset("maps"), dataset("tasks").catch(() => []), dataset("cashoffers").catch(() => [])]);
    } catch (e) {
      mount(root, errorBox(e.message, () => this.render(root)));
      return;
    }
    maps = maps.filter((m) => !SKIP_MAP_WORDS.some((w) => (m.name || "").includes(w)) && (m.locks || []).some((l) => l.key))
      .sort((a, b) => a.name.localeCompare(b.name));
    if (!state.map || (state.map !== MINE && !maps.some((m) => m.normalizedName === state.map))) state.map = maps[0]?.normalizedName || MINE;

    const summary = h("div.stat-grid");
    const list = h("div.stack");
    const adder = h("div");
    const toolbar = h("div.toolbar",
      select([...maps.map((m) => [m.normalizedName, m.name]), [MINE, "My keys (all maps)"]], state.map, (v) => { state.map = v; draw(); }),
      searchInput("Search keys…", state.q, (v) => { state.q = v; draw(); }),
      toggle("Only keys I have", state.mine, (v) => { state.mine = v; draw(); }));

    const draw = () => {
      local.set("keys.map", state.map);
      const rows = state.map === MINE ? myKeys(maps) : mapKeys(maps.find((m) => m.normalizedName === state.map), tasks);
      const owned = store.progress.owned || {};
      const shown = rows.filter((r) => (!state.mine || owned[r.id]) && matchesQuery(r));
      mount(summary,
        stat(state.map === MINE ? "Keys you have" : "Keys for this map", rows.length, { kind: "accent" }),
        stat("You have", rows.filter((r) => owned[r.id]).length, { sub: state.map === MINE ? "across all maps" : "of these" }),
        stat("Marked rooms", rows.filter((r) => r.tier === "marked").length),
        stat("For your quests", rows.filter((r) => r.tier === "quest" || r.quests.length).length));
      if (!shown.length) {
        mount(list, empty(state.map === MINE ? "No keys ticked yet." : "No keys match.",
          state.map === MINE ? "Tick the keys you have on a map's list, add one below, or read them off a screenshot." : ""));
        return;
      }
      if (state.map === MINE) {
        mount(list, card("Your keys", h("div.key-list", shown.map((r) => keyRow(r, true)))));
        return;
      }
      mount(list, TIERS.map(([tier, title, sub, kind]) => {
        const group = shown.filter((r) => r.tier === tier);
        return group.length ? card(h("span", title, " ", badge(String(group.length), kind)), h("div.key-list", group.map((r) => keyRow(r))), { sub }) : null;
      }));
    };

    drawAdder(adder, draw);
    mount(root, summary, toolbar, adder, list,
      h("div.muted.small", { style: { marginTop: "8px" } },
        "Loot near the door is worked out from tarkov.dev's map data: containers and loose loot spawns within about 9 metres of "
        + "the door, on the same floor. It can take in a corridor or the room next door, so treat it as a guide."));
    draw();
    const onPaste = (e) => {
      const file = [...(e.clipboardData?.files || [])].find((f) => f.type.startsWith("image/"));
      if (file) { e.preventDefault(); readPicture(file, "Pasted picture", adder, draw); }
    };
    document.addEventListener("paste", onPaste);
    const off = on((kind, detail) => {
      if (kind === "progress") { draw(); drawAdder(adder, draw); }
      if (kind === "data" && (detail === "maps" || detail === "tasks")) this.render(root);
      if (kind === "items") draw();
    });
    return () => { document.removeEventListener("paste", onPaste); off(); };
  },
};

function matchesQuery(r) {
  if (!state.q) return true;
  const hay = [r.name, r.short, ...(r.maps || []), ...r.quests].join(" ").toLowerCase();
  return state.q.toLowerCase().split(/\s+/).every((w) => hay.includes(w));
}

// -- which keys, and how good ---------------------------------------------------------------

function keyInfo(id, ref) {
  const it = store.itemsById.get(id);
  return { id, name: it?.name || ref?.name || "Unknown key", short: it?.short || ref?.shortName || "", icon: it?.icon || ref?.iconLink, ref };
}

function questsByKey(tasks, mapId) {
  // Open quests (yours, not done) that need a key, on this map when the quest says where.
  const ctx = questContext(tasks);
  const out = new Map();
  const add = (k, t, s) => {
    if (!k?.id) return;
    const e = out.get(k.id) || { ref: k, open: [], later: [] };
    const list = s === "locked" ? e.later : e.open;
    if (!list.includes(t.name)) list.push(t.name);
    out.set(k.id, e);
  };
  for (const t of tasks) {
    const s = questState(t, ctx);
    if (s === "done" || s === "other") continue;
    for (const nk of t.neededKeys || []) {
      if (!mapId || !nk.map?.id || nk.map.id === mapId) for (const k of nk.keys || []) add(k, t, s);
    }
    for (const o of t.objectives || []) {
      const onMap = !mapId || !(o.maps || []).length || o.maps.some((m) => m.id === mapId);
      if (onMap) for (const k of (o.requiredKeys || []).flat()) add(k, t, s);
    }
  }
  return out;
}

function mapKeys(m, tasks) {
  if (!m) return [];
  const quests = questsByKey(tasks, m.id);
  const keys = new Map();
  for (const l of m.locks || []) {
    if (!l.key?.id) continue;
    const e = keys.get(l.key.id) || { ...keyInfo(l.key.id, l.key), needsPower: false, lockTypes: new Set() };
    e.needsPower = e.needsPower || !!l.needsPower;
    e.lockTypes.add(l.lockType || "door");
    keys.set(l.key.id, e);
  }
  // Keys a quest on this map needs, even where tarkov.dev places no door for them.
  for (const [id, q] of quests) if (!keys.has(id) && q.open.length) keys.set(id, { ...keyInfo(id, q.ref), lockTypes: new Set() });
  const loot = m.keyLoot || null;
  return [...keys.values()].map((k) => {
    const q = quests.get(k.id) || { open: [], later: [] };
    const near = loot ? loot[k.id] : undefined;
    const price = buyPrice(k.id)?.price ?? null;
    let tier;
    if (/marked/i.test(k.name)) tier = "marked";
    else if (q.open.length) tier = "quest";
    else if (!near) tier = loot && k.lockTypes.size ? "little" : "unknown";
    else tier = near.score >= GOOD ? "good" : near.score >= SOME ? "some" : "little";
    return { ...k, tier, near, price, quests: q.open, later: q.later, score: near?.score || 0 };
  }).sort((a, b) => b.score - a.score || (b.price || 0) - (a.price || 0) || a.name.localeCompare(b.name));
}

function myKeys(maps) {
  const owned = store.progress.owned || {};
  const where = new Map();
  for (const m of maps) for (const l of m.locks || []) {
    if (!l.key?.id) continue;
    const list = where.get(l.key.id) || [];
    if (!list.includes(m.name)) list.push(m.name);
    where.set(l.key.id, list);
  }
  return Object.keys(owned).filter((id) => owned[id] && isKey(id))
    .map((id) => ({ ...keyInfo(id), maps: where.get(id) || [], quests: [], later: [], price: buyPrice(id)?.price ?? null }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

function isKey(id) {
  return (store.itemsById.get(id)?.tags || []).includes("keys");
}

// -- a row ------------------------------------------------------------------------------------

function lootText(near) {
  if (!near) return null;
  const bits = (near.containers || []).slice(0, 4).map((c) => (c.count > 1 ? `${c.count}× ${c.name}` : c.name));
  const more = (near.containers || []).slice(4).reduce((n, c) => n + c.count, 0);
  if (more) bits.push(`${more} more`);
  const loose = (near.loose || []).slice(0, 3).map((i) => store.itemsById.get(i.id)?.short || i.shortName || i.name).filter(Boolean);
  return [bits.length ? "Near the door: " + bits.join(", ") : "No containers near the door",
    loose.length ? ` · loose loot can include ${loose.join(", ")}` : ""].join("");
}

function keyRow(r, mine = false) {
  const owned = (store.progress.owned || {})[r.id] || 0;
  const meta = [];
  if (r.quests.length) meta.push(badge(`Quest: ${r.quests.slice(0, 2).join(", ")}${r.quests.length > 2 ? ` +${r.quests.length - 2}` : ""}`, "info"));
  else if (r.later.length) meta.push(h("span.muted", `Later quest: ${r.later[0]}`));
  if (r.needsPower) meta.push(badge("Needs power", "warn"));
  if (mine && r.maps.length) meta.push(h("span.muted", r.maps.join(", ")));
  const loot = mine ? null : lootText(r.near);
  return h("div.key-row" + (owned ? ".have" : ""),
    h("label.key-have", { title: owned ? "You have this key" : "Tick when you have it" },
      h("input", { type: "checkbox", checked: !!owned, onchange: (e) => setProgress({ op: "owned", item: r.id, count: e.target.checked ? Math.max(1, owned) : 0 }) })),
    itemChip(r.ref || r.id, null, { fullName: true }),
    h("div.key-main",
      meta.length ? h("div.key-meta", meta) : null,
      loot ? h("div.key-loot.small", loot) : null),
    h("div.key-price", r.price ? fmt.rub(r.price) : h("span.muted", "–")),
    owned > 1 || mine ? ownedStepper(r.id) : null);
}

// -- adding keys ------------------------------------------------------------------------------

function drawAdder(el, redraw) {
  const results = h("div.key-search-results");
  const findKey = (q) => {
    const found = q ? searchItems(q, 80).filter((it) => (it.tags || []).includes("keys")).slice(0, 8) : [];
    const owned = store.progress.owned || {};
    mount(results, found.map((it) => h("button.key-suggest", {
      type: "button",
      onclick: () => setProgress({ op: "owned", item: it.id, count: (owned[it.id] || 0) + 1 })
        .then(() => toast(`Added ${it.name}.`, { kind: "good" })).catch((e) => toast(e.message, { kind: "bad" })),
    }, thumb(it.icon, 24), h("span", it.name), owned[it.id] ? badge(`have ${owned[it.id]}`, "good") : icon("plus", 14))));
  };
  const picker = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp", style: { display: "none" },
    onchange: (e) => { const f = e.target.files?.[0]; if (f) readPicture(f, f.name, el, redraw); e.target.value = ""; } });
  const drop = h("div.key-drop", {
    ondragover: (e) => { e.preventDefault(); drop.classList.add("over"); },
    ondragleave: () => drop.classList.remove("over"),
    ondrop: (e) => {
      e.preventDefault(); drop.classList.remove("over");
      const f = [...(e.dataTransfer?.files || [])].find((x) => x.type.startsWith("image/"));
      if (f) readPicture(f, f.name, el, redraw);
    },
  },
  h("div.key-drop-buttons",
    button("Read my newest Tarkov screenshot", () => readNewest(el, redraw), { kind: "primary small", iconName: "upload" }),
    button("Choose a picture…", () => picker.click(), { kind: "ghost small" })),
  h("div.muted.small", "Open your key tool or keycase in game so the key labels show, press Print Screen (Tarkov saves the screenshot), "
    + "then read it here. You can also paste a snip (Win+Shift+S, then Ctrl+V) or drop a picture here."),
  picker);
  mount(el, h("div.grid.cols-2",
    card("Add a key you found", h("div",
      searchInput("Key name, e.g. Dorm room 314 or 314…", "", findKey),
      results)),
    card("Read keys from a screenshot", h("div", drop, reading ? readingView(el, redraw) : null))));
}

async function readNewest(el, redraw) {
  try {
    const res = await fetch("/api/keys/screenshot", { headers: { "X-Token": TOKEN } });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || `${res.status} ${res.statusText}`);
    const when = Number(res.headers.get("X-Shot-Time") || 0);
    const name = decodeURIComponent(res.headers.get("X-Shot-Name") || "screenshot");
    await readPicture(await res.blob(), `${name}${when ? ` (taken ${fmt.ago(when)})` : ""}`, el, redraw);
  } catch (e) {
    toast(e.message, { kind: "bad", timeout: 9000 });
  }
}

// Cut the picture into pieces the text reader takes, enlarged (key labels
// are small), as grey pixels; send each; put the keys found together (a
// label read twice where pieces overlap counts once).
async function readPicture(blob, label, el, redraw) {
  const url = URL.createObjectURL(blob);
  reading = { label, url, status: "Reading…", found: null, lines: [] };
  drawAdder(el, redraw);
  try {
    const info = await fetchJson("keys/ocr");
    if (!info.engine) throw new Error(info.error || "No text reader installed.");
    const bmp = await createImageBitmap(blob);
    const W = bmp.width, H = bmp.height;
    const scale = H <= 700 ? 3 : H <= 1600 ? 2 : 1;
    const size = Math.floor((info.maxDimension || 2600) / scale);
    const overlap = Math.min(80, Math.floor(size / 4));
    const pieces = [];
    for (let y = 0; y < H; y += size - overlap) {
      for (let x = 0; x < W; x += size - overlap) {
        pieces.push([x, y, Math.min(size, W - x), Math.min(size, H - y)]);
        if (x + size >= W) break;
      }
      if (y + size >= H) break;
    }
    const hits = [];
    for (const [i, [x, y, w, hh]] of pieces.entries()) {
      reading.status = `Reading piece ${i + 1} of ${pieces.length}…`;
      drawAdder(el, redraw);
      const cw = w * scale, ch = hh * scale;
      const canvas = document.createElement("canvas");
      canvas.width = cw; canvas.height = ch;
      const c2d = canvas.getContext("2d", { willReadFrequently: true });
      c2d.imageSmoothingEnabled = true; c2d.imageSmoothingQuality = "high";
      c2d.drawImage(bmp, x, y, w, hh, 0, 0, cw, ch);
      const px = c2d.getImageData(0, 0, cw, ch).data;
      const gray = new Uint8Array(cw * ch);
      for (let p = 0, q = 0; q < gray.length; p += 4, q++) gray[q] = (px[p] * 77 + px[p + 1] * 150 + px[p + 2] * 29) >> 8;
      const res = await fetch(`/api/keys/read?w=${cw}&h=${ch}&x=${x}&y=${y}&scale=${scale}`, {
        method: "POST", headers: { "X-Token": TOKEN, "Content-Type": "application/octet-stream" }, body: gray,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
      reading.lines.push(...(data.lines || []));
      for (const f of data.found || []) {
        if (!hits.some((o) => o.id === f.id && Math.abs(o.x - f.x) < 30 && Math.abs(o.y - f.y) < 20)) hits.push(f);
      }
    }
    const byId = new Map();
    for (const f of hits) {
      const e = byId.get(f.id) || { ...f, count: 0, reads: [] };
      e.count += 1;
      if (!e.reads.includes(f.read)) e.reads.push(f.read);
      byId.set(f.id, e);
    }
    reading.found = [...byId.values()].sort((a, b) => a.name.localeCompare(b.name));
    reading.pick = new Set(reading.found.map((f) => f.id));
    reading.status = "";
  } catch (e) {
    reading.status = "";
    reading.error = e.message;
  }
  drawAdder(el, redraw);
}

function readingView(el, redraw) {
  const r = reading;
  const owned = store.progress.owned || {};
  const close = button("Close", () => { URL.revokeObjectURL(r.url); reading = null; drawAdder(el, redraw); }, { kind: "ghost small", iconName: "x" });
  const head = h("div.key-reading-head", h("img.key-shot", { src: r.url, alt: "" }),
    h("div.grow", h("div.small", r.label), r.status ? h("div.muted.small", h("span.spinner"), " ", r.status) : null), close);
  if (r.error) return h("div.key-reading", head, h("div.note.warn", icon("alert", 16), h("div", r.error)));
  if (!r.found) return h("div.key-reading", head);
  if (!r.found.length) {
    return h("div.key-reading", head, h("div.note", icon("info", 16), h("div",
      r.lines.length ? `Read ${r.lines.length} bits of text, but none matched a key's label. ` : "No text found. ",
      "Make sure the key labels show (open the key tool or keycase), and use the game's own screenshot or a snip of just the keys.")),
    linesSeen(r));
  }
  const add = () => {
    const items = {};
    for (const f of r.found) if (r.pick.has(f.id)) items[f.id] = Math.max(owned[f.id] || 0, f.count);
    if (!Object.keys(items).length) return;
    setProgress({ op: "owned_many", items }).then(() => {
      toast(`Added ${Object.keys(items).length} key${Object.keys(items).length > 1 ? "s" : ""}.`, { kind: "good" });
      URL.revokeObjectURL(r.url); reading = null; drawAdder(el, redraw);
    }).catch((e) => toast(e.message, { kind: "bad" }));
  };
  return h("div.key-reading", head,
    h("div.muted.small", `Found ${r.found.length} key${r.found.length > 1 ? "s" : ""}. Untick any it got wrong.`),
    h("div.key-found", r.found.map((f) => h("label.key-found-row",
      h("input", { type: "checkbox", checked: r.pick.has(f.id), onchange: (e) => { if (e.target.checked) r.pick.add(f.id); else r.pick.delete(f.id); } }),
      thumb(f.icon, 24), h("span.grow", f.name, f.count > 1 ? h("span.muted", ` ×${f.count}`) : null),
      h("span.muted.small", `read “${f.reads[0]}”`),
      owned[f.id] ? badge("have", "good") : null))),
    h("div.toolbar", { style: { marginTop: "8px" } }, button(`Add ticked keys`, add, { kind: "good small", iconName: "check" })),
    linesSeen(r));
}

function linesSeen(r) {
  if (!r.lines.length) return null;
  return h("details.key-lines", h("summary.muted.small", "What the reader saw"), h("div.muted.small", r.lines.join(" · ")));
}

async function fetchJson(path) {
  const res = await fetch("/api/" + path, { headers: { "X-Token": TOKEN } });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}
