import { itemChip } from "../components.js";
import { api, badge, button, card, empty, errorBox, ext, fmt, h, icon, img, loading, local, mount, segmented, select, stat, table, toast, TOKEN } from "../lib.js";
import { objectiveDone } from "../questinfo.js";
import { buyPrice, dataset, on, peek, questContext, questState, setMarkers, setProgress, store } from "../store.js";

// Markers you add are drawn by every map viewer on screen, and redrawn when
// they change here or in another window (a popped-out map). Quest markers are
// redrawn when progress, the raid you're in, or the quest data change.
const live = new Set();
const questLive = new Set();
const redrawAll = () => { for (const fn of [...live]) fn(); };
const redrawQuests = (why) => { for (const fn of [...questLive]) fn(why); };
const COLORS = ["yellow", "red", "green", "blue", "purple", "white"];
const POPOUT_SIZE = "popup,width=980,height=820";

// -- quest markers --------------------------------------------------------------------------
// Placed by the app (questmap.py) on tarkov.dev's drawing of the map, the only
// map picture that comes with the game's coordinates.

const QUEST_FILTERS = [["raid", "Raid plan"], ["available", "Available now"], ["open", "Not done"], ["all", "All quests"], ["off", "Off"]];
// Bright, well separated colours for the first quests on a map; then hues spread round the colour wheel.
const QUEST_COLORS = ["#ff4d4d", "#4da6ff", "#ffd633", "#3ddc84", "#ff5cf0", "#ff9a3c", "#2ee6e6", "#a274ff",
  "#c6f53b", "#ff9ec7", "#ffffff", "#d4a373", "#7dffcf", "#8fb8ff", "#ff6f91", "#b0bec5"];
const questColor = (i) => i < QUEST_COLORS.length ? QUEST_COLORS[i]
  : `hsl(${Math.round((i * 137.508) % 360)} 85% ${i % 2 ? 62 : 74}%)`;

const questMaps = new Map();  // map normalizedName -> Promise of /api/questmap/<map>
function loadQuestMap(norm) {
  if (!questMaps.has(norm)) {
    const p = api(`questmap/${encodeURIComponent(norm)}`);
    p.catch(() => questMaps.delete(norm));
    questMaps.set(norm, p);
  }
  return questMaps.get(norm);
}

// The raid you're in (from the game log reader), if it's on this map.
const raidOn = (m) => { const r = store.state?.raid; return r && r.normalizedName === m.normalizedName ? r : null; };
const raidKey = (m) => { const r = raidOn(m); return r ? [r.normalizedName, r.raidId, r.time].join("|") : null; };
// Raids in which you picked another filter or picture yourself: the raid doesn't take them over again.
const raidChoice = { filter: null, image: null };

// In a raid, only your raid plan's quests (until you pick something else).
function questFilter(m) {
  const key = raidKey(m);
  if (key && raidChoice.filter !== key) return "raid";
  const f = local.get("map.quests", "open");
  return QUEST_FILTERS.some(([v]) => v === f) ? f : "open";
}

function setQuestFilter(m, value) {
  const key = raidKey(m);
  if (key) raidChoice.filter = value === "raid" ? null : key;
  if (!key || value !== "raid") local.set("map.quests", value);
}

// The quests to draw, each with its own colour, and only the spots of
// objectives still to do.
function visibleQuests(data, filter) {
  if (!data?.quests?.length || filter === "off") return [];
  const tasks = peek("tasks") || [];
  const ctx = questContext(tasks);
  const objectives = new Map();
  for (const t of tasks) for (const o of t.objectives || []) if (o?.id) objectives.set(o.id, o);
  const pinned = new Set(store.progress?.pinned || []);
  const out = [];
  for (const q of data.quests) {
    const task = ctx.byId.get(q.id);
    const state = task ? questState(task, ctx) : "available";
    if (filter === "raid" && (!pinned.has(q.id) || state === "done")) continue;
    if (filter === "available" && state !== "available") continue;
    if (filter === "open" && (state === "done" || state === "other")) continue;
    const markers = state === "done" ? q.markers
      : q.markers.filter((mk) => mk.objectives.some((id) => !objectives.has(id) || !objectiveDone(objectives.get(id))));
    if (markers.length) out.push({ ...q, markers, state, pinned: pinned.has(q.id) });
  }
  out.forEach((q, i) => { q.color = questColor(i); });
  return out;
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

export default {
  title: "Maps",
  subtitle: "Map images, quest markers, bosses, extracts, keys and your own markers",
  async render(root, { rest, query = {}, popout = false }) {
    mount(root, loading("Loading maps from tarkov.dev…"));
    let maps;
    try { maps = await dataset("maps"); } catch (e) {
      mount(root, errorBox(e.message, () => this.render(root, { rest, query, popout })));
      return;
    }
    dataset("mapimages").catch(() => {});
    dataset("tasks").catch(() => {});
    maps = maps.filter((m) => m.normalizedName).sort((a, b) => a.name.localeCompare(b.name));
    const selected = maps.find((m) => m.normalizedName === rest[0]) || maps.find((m) => m.normalizedName === "customs") || maps[0];
    let raid = JSON.stringify(store.state?.raid || null);
    const off = on((kind, detail) => {
      if (kind === "markers") redrawAll();
      else if (kind === "progress") redrawQuests("progress");
      else if (kind === "state") {
        const now = JSON.stringify(store.state?.raid || null);
        if (now !== raid) { raid = now; redrawQuests("raid"); }
      } else if (kind === "data" && ["tasks", "maps", "mapimages"].includes(detail)) {
        questMaps.clear();
        redrawQuests("data");
      }
    });
    const cleanup = () => { off(); live.clear(); questLive.clear(); };
    if (popout) {
      await drawPopout(root, maps, selected, query);
      return cleanup;
    }
    const detail = h("div");
    mount(root,
      h("div.map-cards", maps.map((m) => h("a.map-card" + (m === selected ? ".active" : ""), { href: `#/maps/${m.normalizedName}` },
        h("div.map-card-body",
          h("div.map-card-name", m.name),
          h("div.map-card-meta",
            m.players ? h("span", `${m.players} players`) : null,
            m.raidDuration ? h("span", `${m.raidDuration} min`) : null),
          h("div.muted.small", (m.bosses || []).map((b) => b.boss?.name).filter(Boolean).filter((v, i, a) => a.indexOf(v) === i).slice(0, 3).join(", ") || "No bosses"))))),
      detail);
    if (selected) await drawMap(detail, selected, query);
    return cleanup;
  },
};

// The popped-out window: a map picker and the map, filling the window.
async function drawPopout(root, maps, m, query) {
  if (!m) { mount(root, empty("No maps yet.")); return; }
  root.classList.add("popout-view");
  mount(root, loading());
  let images = null;
  try { images = await dataset("mapimages"); } catch { images = null; }
  const picker = select(maps.map((x) => [x.normalizedName, x.name]), m.normalizedName,
    (v) => { location.hash = `#/maps/${v}`; }, { title: "Map" });
  mount(root, mapImage(m, images, { popout: true, picker, imageKey: query.image, quest: query.quest, filter: query.filter }));
}

async function drawMap(root, m, query = {}) {
  const tabs = [["image", "Map"], ["bosses", "Bosses"], ["extracts", "Extracts"], ["keys", "Keys & locks"], ["more", "Transits & hazards"]];
  let tab = "image";
  const body = h("div");
  const bar = h("div");
  const drawBar = () => mount(bar, segmented(tabs, tab, (v) => { tab = v; drawBar(); drawTab(); }));
  const drawTab = async () => {
    if (tab === "image") {
      mount(body, loading());
      let images = null;
      try { images = await dataset("mapimages"); } catch { images = null; }
      mount(body, mapImage(m, images, { quest: query.quest, filter: query.filter }));
    } else if (tab === "bosses") mount(body, bosses(m));
    else if (tab === "extracts") mount(body, extracts(m));
    else if (tab === "keys") mount(body, keys(m));
    else mount(body, more(m));
  };
  root.classList.add("stack");
  mount(root,
    card(m.name, h("div",
      h("div.stat-grid",
        stat("Players", m.players || "–"),
        stat("Raid time", m.raidDuration ? `${m.raidDuration} min` : "–"),
        stat("Bosses", String(new Set((m.bosses || []).map((b) => b.boss?.id)).size)),
        stat("Extracts", String(new Set((m.extracts || []).map((x) => x.name)).size)),
        m.minPlayerLevel || m.maxPlayerLevel ? stat("Player level", `${m.minPlayerLevel || 1}–${m.maxPlayerLevel || "∞"}`) : null),
      m.accessKeys?.length ? h("div.req-line", { style: { marginTop: "12px" } }, h("span.muted", "Needs to enter:"),
        m.accessKeys.map((k) => itemChip(k, null, { compact: true }))) : null,
      m.description ? h("p.desc", { style: { marginTop: "12px" } }, m.description) : null),
    { actions: [m.wiki ? ext(m.wiki, "Wiki") : null, ext(`https://tarkov.dev/map/${m.normalizedName}`, "Interactive map")] }),
    bar, body);
  drawBar();
  drawTab();
}

function imagesFor(m, all) {
  if (!all) return null;
  const n = m.normalizedName;
  if (all[n]) return all[n];
  // Night Factory and Ground Zero 21+ are drawn on Factory's and Ground Zero's maps.
  const alt = Object.values(all).find((g) => (g?.quest?.altMaps || []).includes(n));
  if (alt) return alt;
  const key = Object.keys(all).find((k) => n.startsWith(k) || n.endsWith(k) || k.startsWith(n) || n.replace(/^night-/, "") === k || n.replace(/-21$/, "") === k);
  return key ? all[key] : null;
}

function variantLabel(image) {
  if (image.quest) return "Quests";
  const parts = image.key.split("-");
  const i = parts.findIndex((p) => p === "2d" || p === "3d");
  if (i < 0) return image.key;
  return [parts[i].toUpperCase(), ...parts.slice(i + 1).map((p) => p[0].toUpperCase() + p.slice(1))].join(" ");
}

function mapImage(m, all, { popout = false, picker = null, imageKey, quest: questId, filter: asked } = {}) {
  const entry = imagesFor(m, all);
  const questImage = entry?.quest ? { key: entry.quest.key, quest: true, author: entry.quest.author, authorLink: entry.quest.authorLink } : null;
  const images = [...(questImage ? [questImage] : []), ...(entry?.images || [])];
  if (!images.length) {
    return h("div", picker ? h("div.toolbar.map-bar", picker) : null,
      empty("No map image for this map.", h("span", "Try the ", ext(`https://tarkov.dev/map/${m.normalizedName}`, "interactive map"), " on tarkov.dev.")));
  }
  const saved = () => Math.max(0, images.findIndex((im) => im.key === local.get(`mapimage.${m.normalizedName}`)));
  // Which picture: the one asked for (popped out, or a quest to show), the
  // quest map when you load into a raid here, else the one you last picked.
  const pick = () => {
    if (imageKey) { const i = images.findIndex((im) => im.key === imageKey); imageKey = null; if (i >= 0) return i; }
    if (questImage && (questId || (raidKey(m) && raidChoice.image !== raidKey(m)))) return 0;
    return saved();
  };
  let current = pick();
  let shownRaid = raidKey(m);
  // A filter asked for in the address (the Raid plan's "Show on the map"), or
  // "All quests" to show a quest asked for that the usual filter hides; until
  // you pick one yourself.
  let forced = QUEST_FILTERS.some(([v]) => v === asked) ? asked : null;
  let drawing = 0;
  const holder = h("div" + (popout ? ".popout-map" : ""));
  const draw = async () => {
    const ticket = ++drawing;
    const image = images[current];
    const choose = images.length > 1 ? segmented(images.map((im, i) => [String(i), variantLabel(im)]), String(current), (v) => {
      current = Number(v);
      local.set(`mapimage.${m.normalizedName}`, images[current].key);
      if (raidKey(m)) raidChoice.image = raidKey(m);
      draw();
    }) : null;
    let data = null, picture = null;
    if (image.quest) {
      mount(holder, h("div.toolbar.map-bar", picker, choose), h("div.viewer" + (popout ? ".tall" : ""), h("div.viewer-msg", h("span", h("span.spinner"), " Placing quest markers…"))));
      try {
        // The quests too: which are done, pinned or available decides what's drawn.
        [data] = await Promise.all([loadQuestMap(m.normalizedName), dataset("tasks").catch(() => null)]);
      } catch (e) {
        if (ticket !== drawing) return;
        mount(holder, h("div.toolbar.map-bar", picker, choose), errorBox("Couldn't load the quest map: " + e.message, draw));
        return;
      }
      if (ticket !== drawing) return;
      const p = data.picture;
      if (!p) {
        mount(holder, h("div.toolbar.map-bar", picker, choose),
          empty(data.error ? `Couldn't load tarkov.dev's drawing of ${m.name}: ${data.error}` : `tarkov.dev has no drawing of ${m.name} to put quest markers on.`,
            h("span", "Try the ", ext(`https://tarkov.dev/map/${m.normalizedName}`, "interactive map"), " on tarkov.dev.")));
        return;
      }
      picture = p.kind === "tiles" ? { kind: "tiles", tiles: p.tiles }
        : { kind: "svg", url: `/api/mapsvg/${encodeURIComponent(p.key)}?token=${encodeURIComponent(TOKEN)}` };
      picture.full = `https://tarkov.dev/map/${m.normalizedName}`;
      picture.license = p.license;
    }
    const view = viewer(image, { popout, picture });
    const popOut = () => {
      const url = `/?popout=1#/maps/${m.normalizedName}?image=${encodeURIComponent(image.key)}`;
      if (!window.open(url, "raidready-map", POPOUT_SIZE)) toast("Couldn't open a new window.", { kind: "warn" });
    };
    let filterBox = null, panel = null, refresh = null;
    if (data) {
      filterBox = h("label.field.quest-filter", { title: "Which quests' markers to show" }, icon("quests", 15));
      panel = h("div.quest-panel");
      const shown = () => {
        let filter = forced || questFilter(m);
        let list = visibleQuests(data, filter);
        if (questId && !list.some((q) => q.id === questId) && data.quests.some((q) => q.id === questId)) {
          forced = filter = "all";
          list = visibleQuests(data, filter);
        }
        return [filter, list];
      };
      const choose = (v) => { forced = null; setQuestFilter(m, v); refresh(); };
      refresh = () => {
        const [filter, list] = shown();
        mount(filterBox, icon("quests", 15), select(QUEST_FILTERS, filter, choose));
        view.setQuests(list);
        drawQuestPanel(panel, m, data, list, filter, view, choose);
      };
      view.onSelect = () => { const [filter, list] = shown(); drawQuestPanel(panel, m, data, list, filter, view, choose); };
    }
    mount(holder,
      h("div.toolbar.map-bar",
        picker,
        choose,
        filterBox,
        h("span.grow"),
        view.controls,
        popout ? null : button("Pop out", popOut, { iconName: "external", title: "Open this map in its own window" })),
      view.box,
      panel || (questImage ? h("div.note.quest-hint", icon("info", 16), h("div",
        "Quest markers are on the Quests map: tarkov.dev's drawing of ", m.name, " comes with the game's coordinates, so they land in the right place. ",
        button("Show quest markers", () => { current = 0; local.set(`mapimage.${m.normalizedName}`, images[0].key); draw(); }, { kind: "small" }))) : null),
      markerList(image, view));
    refreshNow = refresh;
    if (refresh) {
      refresh();
      if (questId) { view.focusQuest(questId); questId = null; }
    }
  };
  // Progress, the raid you're in and tarkov.dev's data change what's drawn.
  let refreshNow = null;
  const redrawn = (why) => {
    if (holder.isConnected) holder.dataset.shown = "1";
    else { if (holder.dataset.shown) questLive.delete(redrawn); return; }
    if (why === "raid") {
      // Loaded into a raid on this map: the quest map, with the raid plan's quests.
      const key = raidKey(m);
      if (key === shownRaid) return;
      shownRaid = key;
      if (key && questImage && current !== 0 && raidChoice.image !== key) { current = 0; draw(); return; }
    }
    if (why === "data" && images[current].quest) { draw(); return; }
    refreshNow?.();
  };
  if (questImage) questLive.add(redrawn);
  draw();
  return holder;
}

function drawQuestPanel(panel, m, data, list, filter, view, choose) {
  const raid = raidOn(m);
  const spots = list.reduce((n, q) => n + q.markers.length, 0);
  const emptyText = {
    raid: `None of your raid plan's quests have marked spots on ${m.name}. Pin quests on the Raid plan or Quests page, or pick "Not done" and pin them here.`,
    available: `No quests you can do now have marked spots on ${m.name}.`,
    open: `Every quest with marked spots on ${m.name} is done.`,
    all: `tarkov.dev has no quest spots on ${m.name}.`,
    off: "Quest markers are off.",
  }[filter];
  const floors = (q) => [...new Set(q.markers.map((mk) => mk.floor).filter(Boolean))];
  mount(panel,
    h("div.section-title",
      h("span", "Quest markers", badge(String(list.length), "accent")),
      list.length ? h("span.muted.small", plural(spots, "spot")) : null),
    raid && filter === "raid" ? h("div.note.raid-note", icon("raid", 16), h("div",
      h("strong", `In raid on ${raid.name || m.name}.`), " Showing your raid plan's quests only. ",
      button("Show all quests", () => choose("open"), { kind: "small" }))) : null,
    list.length ? h("div.list.quest-rows", list.map((q) => h("div.list-row.quest-row" + (view.selected === q.id ? ".sel" : ""),
      h("span.marker-dot", { style: `--pin: ${q.color}` }),
      h("button.marker-note", { type: "button", title: "Show on the map", onclick: () => view.focusQuest(q.id) },
        q.name, q.state === "done" ? h("span.muted", " (done)") : q.state === "locked" ? h("span.muted", " (locked)") : null),
      h("span.muted.small.quest-row-sub", [q.trader, plural(q.markers.length, "spot"), ...floors(q)].filter(Boolean).join(" · ")),
      button("", () => setProgress({ op: "pin", ids: [q.id], pinned: !q.pinned }).catch((e) => toast(e.message, { kind: "bad" })),
        { kind: "ghost small" + (q.pinned ? " on" : ""), iconName: "pin", title: q.pinned ? "Unpin from your raid plan" : "Pin to your raid plan" }))))
      : h("div.muted.small", emptyText),
    h("div.muted.small.quest-foot",
      "Circles are quest objectives (the shaded outline is the area that counts), diamonds are places a quest item can be. ",
      "Spots on other floors are marked with the floor. ",
      data.outside ? `${plural(data.outside, "spot")} outside tarkov.dev's map area ${data.outside === 1 ? "isn't" : "aren't"} shown. ` : "",
      "Positions from ", ext(`https://tarkov.dev/map/${m.normalizedName}`, "tarkov.dev"), "."));
}

const markersOn = (image) => store.markers?.[image.key] || [];
const firstLine = (note) => (note || "").split("\n")[0];

// Pan and zoom a map picture; right-click (or "Add marker" then click) to drop
// a marker, click a marker to edit its note, drag it to move it. Quest markers
// (setQuests) are drawn under your own.
function viewer(image, { popout = false, picture: given = null } = {}) {
  let scale = 1, tx = 0, ty = 0, minScale = 0.05;
  let adding = false, editing = null;
  let labels = local.get("map.labels", true);
  let quests = [];
  const tiles = given?.kind === "tiles" ? given.tiles : null;
  let picture;
  if (tiles) {
    // Satellite-style tiles laid side by side (maps tarkov.dev has no drawing of).
    picture = h("div.tile-mosaic", { style: { width: tiles.width + "px", height: tiles.height + "px" } });
    for (let r = 0; r < tiles.rows; r++) {
      for (let c = 0; c < tiles.columns; c++) {
        const src = tiles.url.replace("{z}", tiles.zoom).replace("{x}", tiles.x0 + c).replace("{y}", tiles.y0 + r);
        picture.appendChild(h("img", { src, alt: "", draggable: "false", referrerpolicy: "no-referrer",
          style: { left: c * tiles.size + "px", top: r * tiles.size + "px", width: tiles.size + "px", height: tiles.size + "px" },
          onerror: (e) => e.target.remove() }));
      }
    }
  } else {
    picture = h("img", { src: given?.url || image.url, alt: image.key, draggable: "false", referrerpolicy: "no-referrer" });
  }
  const size = () => tiles ? [tiles.width, tiles.height] : [picture.naturalWidth, picture.naturalHeight];
  const msg = h("div.viewer-msg", h("span", h("span.spinner"), " Loading map image…"));
  const zones = h("svg.quest-zones", { "aria-hidden": "true" });
  const questLayer = h("div.quest-layer");
  const layer = h("div.marker-layer");
  const editor = h("div.marker-editor", { hidden: true });
  const info = h("div.quest-info", { hidden: true });
  const loaded = () => size()[0] > 0;
  // picture fraction <-> position in the viewer
  const toScreen = (x, y) => { const [w, ht] = size(); return [tx + x * w * scale, ty + y * ht * scale]; };
  const toImage = (cx, cy) => { const [w, ht] = size(); return [(cx - tx) / (w * scale), (cy - ty) / (ht * scale)]; };
  const local_ = (e) => { const r = box.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };

  const place = () => {
    for (const pin of [...layer.children, ...questLayer.children]) {
      const [x, y] = toScreen(Number(pin.dataset.x), Number(pin.dataset.y));
      pin.style.transform = `translate(${x}px, ${y}px)`;
    }
    placeEditor();
  };
  const apply = () => {
    picture.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`;
    zones.style.transform = picture.style.transform;
    place();
  };

  const addBtn = button("Add marker", () => setAdding(!adding), { iconName: "plus", title: "Then click the map. Or right-click the map at any time." });
  const labelBtn = button("Labels", () => {
    labels = !labels; local.set("map.labels", labels); drawPins(); drawQuests(); labelBtn.classList.toggle("on", labels);
  }, { iconName: "eye", title: "Show notes and quest names next to markers" });
  labelBtn.classList.toggle("on", labels);
  const setAdding = (on) => { adding = on; addBtn.classList.toggle("primary", on); box.classList.toggle("adding", on); };

  function drawPins() {
    const markers = markersOn(image);
    mount(layer, markers.map((mk) => {
      const pin = h("div.marker-pin.c-" + mk.color + (editing === mk.id ? ".editing" : ""),
        { dataset: { id: mk.id, x: mk.x, y: mk.y }, title: mk.note || "No note. Click to add one." },
        h("svg", { viewBox: "0 0 24 24", width: 26, height: 26, "aria-hidden": "true" },
          h("path", { d: "M12 22s7-6.3 7-12a7 7 0 0 0-14 0c0 5.7 7 12 7 12z" }), h("circle", { cx: 12, cy: 10, r: 2.6 })),
        labels && mk.note ? h("span.marker-label", firstLine(mk.note)) : null);
      pinDrag(pin, mk);
      return pin;
    }));
    if (editing && !markers.some((mk) => mk.id === editing)) closeEditor({ quiet: true });  // removed elsewhere
    if (loaded()) place();
  }

  // -- quest markers --
  const api_ = { selected: null, onSelect: null };
  function drawQuests() {
    const sel = api_.selected;
    if (sel && !quests.some((q) => q.id === sel)) api_.selected = null;
    const dim = (q) => api_.selected && api_.selected !== q.id;
    const [w, ht] = size();
    if (w) {
      zones.setAttribute("width", w);
      zones.setAttribute("height", ht);
      zones.setAttribute("viewBox", `0 0 ${w} ${ht}`);
      mount(zones, quests.flatMap((q) => q.markers.filter((mk) => mk.outline).map((mk) => h("polygon", {
        points: mk.outline.map(([x, y]) => `${(x * w).toFixed(1)},${(y * ht).toFixed(1)}`).join(" "),
        style: `--q: ${q.color}`, class: dim(q) ? "dim" : null }))));
    }
    mount(questLayer, quests.flatMap((q) => q.markers.map((mk) => {
      const tip = [q.name + (mk.floor ? ` (${mk.floor})` : ""), mk.text, mk.item ? `Item: ${mk.item}` : null, mk.optional ? "Optional" : null]
        .filter(Boolean).join("\n");
      const pin = h("div.quest-pin" + (mk.kind === "item" ? ".item" : "") + (dim(q) ? ".dim" : "") + (api_.selected === q.id ? ".sel" : ""),
        { dataset: { x: mk.x, y: mk.y }, style: `--q: ${q.color}` },
        h("span.qp-dot", { title: tip }),
        labels ? h("span.qp-label", q.name + (mk.floor ? ` · ${mk.floor}` : "")) : null);
      pin.firstChild.addEventListener("click", (e) => { e.stopPropagation(); selectQuest(q, mk); });
      return pin;
    })));
    drawInfo();
    if (loaded()) place();
  }

  function selectQuest(q, mk) {
    api_.selected = q && api_.selected !== q.id ? q.id : null;
    api_.shown = api_.selected ? mk : null;
    drawQuests();
    api_.onSelect?.(api_.selected);
  }

  // The quest of the marker you clicked: what to do there.
  function drawInfo() {
    const q = quests.find((x) => x.id === api_.selected);
    const mk = api_.shown;
    if (!q) { info.hidden = true; info.replaceChildren(); return; }
    const here = mk ? q.markers.filter((x) => x.x === mk.x && x.y === mk.y) : [];
    mount(info,
      h("div.quest-info-head", h("span.marker-dot", { style: `--pin: ${q.color}` }), h("strong.grow", q.name),
        button("", () => selectQuest(null), { kind: "ghost small", iconName: "x", title: "Close" })),
      h("div.muted.small", [q.trader, plural(q.markers.length, "spot") + " on this map"].filter(Boolean).join(" · ")),
      here.length ? h("ul.quest-info-list", here.map((x) => h("li", x.text || (x.kind === "item" ? "Quest item" : "Objective"),
        x.item ? h("div.muted.small", `Item: ${x.item}`) : null,
        x.floor ? h("div.muted.small", x.floor) : null))) : null,
      h("div.quest-info-actions",
        button(q.pinned ? "Pinned" : "Pin", () => setProgress({ op: "pin", ids: [q.id], pinned: !q.pinned }).catch((e) => toast(e.message, { kind: "bad" })),
          { kind: "small" + (q.pinned ? " on" : ""), iconName: "pin", title: q.pinned ? "Unpin from your raid plan" : "Pin to your raid plan" }),
        h("a.btn.small", { href: `#/quests?q=${encodeURIComponent(q.name)}` }, h("span", "Quest"))));
    info.hidden = false;
  }

  // Zoom to a quest's markers and pick it out.
  function focusQuest(id) {
    const q = quests.find((x) => x.id === id);
    if (!q) return;
    api_.selected = id;
    api_.shown = q.markers.length === 1 ? q.markers[0] : null;
    drawQuests();
    api_.onSelect?.(id);
    if (!loaded()) return;
    const [w, ht] = size();
    const r = box.getBoundingClientRect();
    const xs = q.markers.map((mk) => mk.x * w), ys = q.markers.map((mk) => mk.y * ht);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const span = Math.max(maxX - minX, maxY - minY, Math.max(w, ht) * 0.06);
    scale = Math.max(minScale, Math.min(6, (Math.min(r.width, r.height) * 0.7) / span));
    tx = r.width / 2 - ((minX + maxX) / 2) * scale;
    ty = r.height / 2 - ((minY + maxY) / 2) * scale;
    apply();
  }

  function pinDrag(pin, mk) {
    let start = null;
    pin.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.stopPropagation();
      start = { x: e.clientX, y: e.clientY, moved: false };
      pin.setPointerCapture(e.pointerId);
    });
    pin.addEventListener("pointermove", (e) => {
      if (!start) return;
      if (!start.moved && Math.hypot(e.clientX - start.x, e.clientY - start.y) < 4) return;
      start.moved = true;
      pin.classList.add("moving");
      const [x, y] = toImage(...local_(e));
      pin.dataset.x = Math.max(0, Math.min(1, x));
      pin.dataset.y = Math.max(0, Math.min(1, y));
      place();
    });
    const end = async () => {
      if (!start) return;
      const moved = start.moved;
      start = null;
      pin.classList.remove("moving");
      if (!moved) return openEditor(mk.id);
      await change({ op: "update", id: mk.id, x: Number(pin.dataset.x), y: Number(pin.dataset.y) });
    };
    pin.addEventListener("pointerup", end);
    pin.addEventListener("pointercancel", end);
    pin.addEventListener("contextmenu", (e) => { e.preventDefault(); e.stopPropagation(); openEditor(mk.id); });
  }

  async function change(op) {
    try {
      return await setMarkers({ image: image.key, ...op });
    } catch (e) {
      toast("Couldn't save the marker: " + e.message, { kind: "bad" });
      drawPins();
      return null;
    }
  }

  async function addAt(cx, cy) {
    if (!loaded()) return;
    const [x, y] = toImage(cx, cy);
    if (x < 0 || x > 1 || y < 0 || y > 1) return;
    const before = new Set(markersOn(image).map((mk) => mk.id));
    const color = local.get("map.color", COLORS[0]);
    if (!(await change({ op: "add", x, y, note: "", color }))) return;
    setAdding(false);
    const added = markersOn(image).find((mk) => !before.has(mk.id));
    if (added) openEditor(added.id, { fresh: true });
  }

  // Closing the editor saves what you typed, except Cancel (or Escape), which
  // drops your changes, and removes the marker if you had only just added it.
  let saveEdits = null, discardEdits = null;

  function openEditor(id, { fresh = false } = {}) {
    const mk = markersOn(image).find((x) => x.id === id);
    if (!mk || editing === id) return;
    closeEditor();
    editing = id;
    let color = mk.color;
    const note = h("textarea", { rows: 4, maxlength: 500, placeholder: "Note: loot spot, key door, sniper perch…", spellcheck: "true" });
    note.value = mk.note;
    const swatches = h("div.marker-colors");
    const drawSwatches = () => mount(swatches, COLORS.map((c) => h("button.swatch.c-" + c + (c === color ? ".on" : ""),
      { type: "button", title: c, onclick: () => { color = c; drawSwatches(); note.focus({ preventScroll: true }); } })));
    drawSwatches();
    saveEdits = () => {
      local.set("map.color", color);
      if (note.value.trim() !== mk.note || color !== mk.color) change({ op: "update", id, note: note.value, color });
    };
    discardEdits = () => { if (fresh) change({ op: "delete", id }); };
    note.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || !e.shiftKey)) { e.preventDefault(); closeEditor(); }
      else if (e.key === "Escape") { e.preventDefault(); closeEditor({ discard: true }); }
    });
    mount(editor,
      note, swatches,
      h("div.marker-editor-actions",
        button("Delete", () => { closeEditor({ quiet: true }); change({ op: "delete", id }); }, { kind: "danger small", iconName: "trash" }),
        h("span.grow"),
        button("Cancel", () => closeEditor({ discard: true }), { kind: "ghost small", title: fresh ? "Remove this new marker" : "Forget your changes" }),
        button("Save", () => closeEditor(), { kind: "primary small" })),
      h("div.muted.small", "Enter saves, Shift+Enter for a new line"));
    editor.hidden = false;
    drawPins();
    note.focus({ preventScroll: true });
  }

  function closeEditor({ discard = false, quiet = false } = {}) {
    if (!editing) return;
    const save = saveEdits, drop = discardEdits;
    editing = null;
    saveEdits = discardEdits = null;
    editor.hidden = true;
    editor.replaceChildren();
    layer.querySelector(".editing")?.classList.remove("editing");
    if (quiet) return;
    if (discard) drop?.();
    else save?.();
  }

  function placeEditor() {
    if (!editing || editor.hidden) return;
    const pin = layer.querySelector(`[data-id="${editing}"]`);
    if (!pin) return;
    const [x, y] = toScreen(Number(pin.dataset.x), Number(pin.dataset.y));
    const r = box.getBoundingClientRect();
    const w = editor.offsetWidth || 280, hgt = editor.offsetHeight || 170;
    editor.style.left = Math.max(8, Math.min(r.width - w - 8, x - w / 2)) + "px";
    editor.style.top = (y + 14 + hgt > r.height - 8 ? Math.max(8, y - hgt - 34) : y + 14) + "px";
  }

  // Centre a marker in the view and open its note (from the list below).
  function focus(id) {
    const mk = markersOn(image).find((x) => x.id === id);
    if (!mk || !loaded()) return;
    const [w, ht] = size();
    const r = box.getBoundingClientRect();
    if (scale < minScale * 3) scale = Math.min(6, minScale * 4);
    tx = r.width / 2 - mk.x * w * scale;
    ty = r.height / 2 - mk.y * ht * scale;
    apply();
    openEditor(id);
  }

  const credit = given?.kind ? (image.author ? h("div.viewer-credit", "Map by ",
    image.authorLink ? h("a", { href: image.authorLink, target: "_blank", rel: "noopener noreferrer" }, image.author) : image.author,
    " for tarkov.dev", given.license ? [" · ", h("a", { href: given.license.link, target: "_blank", rel: "noopener noreferrer" }, given.license.name)] : null) : null)
    : image.author ? h("div.viewer-credit", "Map by ",
      image.authorLink ? h("a", { href: image.authorLink, target: "_blank", rel: "noopener noreferrer" }, image.author) : image.author) : null;
  const box = h("div.viewer" + (popout ? ".tall" : ""), msg, picture, zones, questLayer, layer, editor, info,
    h("div.viewer-tools",
      button("", () => zoom(1.3), { iconName: "zoomin", title: "Zoom in" }),
      button("", () => zoom(1 / 1.3), { iconName: "zoomout", title: "Zoom out" }),
      button("", fit, { iconName: "expand", title: "Fit" }),
      h("a.btn", { href: given?.full || image.url, target: "_blank", rel: "noopener noreferrer",
        title: given?.full ? "Open tarkov.dev's interactive map" : "Open full size" }, icon("external", 16))),
    credit);
  function fit() {
    if (!loaded()) return;
    const [w, ht] = size();
    const r = box.getBoundingClientRect();
    scale = Math.min(r.width / w, r.height / ht);
    minScale = scale * 0.5;
    tx = (r.width - w * scale) / 2;
    ty = (r.height - ht * scale) / 2;
    apply();
  }
  function zoom(f, cx, cy) {
    const r = box.getBoundingClientRect();
    cx = cx ?? r.width / 2; cy = cy ?? r.height / 2;
    const ns = Math.max(minScale, Math.min(scale * f, 6));
    tx = cx - (cx - tx) * (ns / scale);
    ty = cy - (cy - ty) * (ns / scale);
    scale = ns;
    apply();
  }
  // Shown and sized once the picture's size is known and the viewer is on the page.
  let ready = false;
  const show = () => {
    if (ready || !loaded() || !box.isConnected || !box.clientWidth) return;
    ready = true;
    msg.remove();
    fit();
    drawQuests();
    pending?.();
    pending = null;
  };
  let pending = null;
  const inUi = (e) => e.target.closest(".viewer-tools, .viewer-credit, .marker-editor, .marker-pin, .quest-pin, .quest-info");
  if (!tiles) {
    picture.addEventListener("load", show);
    picture.addEventListener("error", () => {
      picture.classList.add("broken");
      mount(msg, h("span", "Couldn't load the map image. ", ext(given?.full || image.url, "Open it directly")));
    });
  }
  box.addEventListener("wheel", (e) => {
    if (e.target.closest(".marker-editor, .quest-info")) return;
    e.preventDefault();
    zoom(e.deltaY < 0 ? 1.15 : 1 / 1.15, ...local_(e));
  }, { passive: false });
  let drag = null;
  box.addEventListener("pointerdown", (e) => {
    if (inUi(e) || e.button !== 0) return;
    drag = { x: e.clientX, y: e.clientY, tx, ty, moved: false };
    box.setPointerCapture(e.pointerId);
    box.classList.add("dragging");
  });
  box.addEventListener("pointermove", (e) => {
    if (!drag) return;
    if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) > 4) drag.moved = true;
    tx = drag.tx + e.clientX - drag.x;
    ty = drag.ty + e.clientY - drag.y;
    apply();
  });
  const end = (e) => {
    const click = drag && !drag.moved;
    drag = null;
    box.classList.remove("dragging");
    if (click && e.type === "pointerup") {
      if (adding) addAt(...local_(e));
      else closeEditor();
    }
  };
  box.addEventListener("pointerup", end);
  box.addEventListener("pointercancel", end);
  box.addEventListener("contextmenu", (e) => {
    if (inUi(e)) return;
    e.preventDefault();
    addAt(...local_(e));
  });
  box.addEventListener("dblclick", (e) => { if (!inUi(e) && !adding) zoom(1.8, ...local_(e)); });
  new ResizeObserver(() => { if (!ready) show(); else if (loaded()) place(); }).observe(box);

  const redraw = () => { if (!box.isConnected) live.delete(redraw); else drawPins(); };
  live.add(redraw);
  drawPins();
  return Object.assign(api_, {
    box, controls: h("div.map-marker-tools", addBtn, labelBtn), focus,
    setQuests(list) { quests = list || []; drawQuests(); },
    focusQuest(id) { if (ready) focusQuest(id); else pending = () => focusQuest(id); },
  });
}

function markerList(image, view) {
  const el = h("div.marker-list");
  const draw = () => {
    if (!el.isConnected && el.dataset.drawn) { live.delete(draw); return; }
    el.dataset.drawn = "1";
    const markers = markersOn(image);
    mount(el,
      h("div.section-title", h("span", "Your markers", badge(String(markers.length), "accent")),
        markers.length ? button("Remove all", async () => {
          if (!confirm(`Remove all ${markers.length} markers from this map image?`)) return;
          await setMarkers({ op: "clear", image: image.key }).catch((e) => toast(e.message, { kind: "bad" }));
        }, { kind: "ghost small", iconName: "trash" }) : null),
      markers.length
        ? h("div.list", markers.map((mk) => h("div.list-row.marker-row",
          h("span.marker-dot.c-" + mk.color),
          h("button.marker-note", { type: "button", title: "Show on the map", onclick: () => view.focus(mk.id) },
            mk.note ? firstLine(mk.note) : h("span.muted", "No note")),
          button("", () => setMarkers({ op: "delete", image: image.key, id: mk.id }).catch((e) => toast(e.message, { kind: "bad" })),
            { kind: "ghost small", iconName: "trash", title: "Remove" }))))
        : h("div.muted.small", "Right-click the map, or press Add marker and click, to drop a marker with a note. Markers are saved on this PC and shared by PvP and PvE."));
  };
  live.add(draw);
  draw();
  return el;
}

function bosses(m) {
  const spawns = m.bosses || [];
  if (!spawns.length) return empty("No bosses on this map.");
  return h("div.grid.auto", spawns.map((b) => h("div.boss-card",
    h("div.portrait", img(b.boss?.imagePortraitLink, { alt: b.boss?.name })),
    h("div", { style: { flex: 1, minWidth: 0 } },
      h("div", { style: { display: "flex", justifyContent: "space-between", gap: "10px" } },
        h("a", { href: "#/bosses", style: { fontWeight: 600, color: "var(--text)" } }, b.boss?.name || "Unknown"),
        h("span.chance", fmt.pct(b.spawnChance))),
      b.spawnTrigger ? h("div.muted.small", `Trigger: ${b.spawnTrigger}`) : null,
      b.spawnTime > 0 ? h("div.muted.small", `Spawns ${b.spawnTimeRandom ? "around" : "at"} ${Math.round(b.spawnTime / 60)} min`) : null,
      (b.spawnLocations || []).length ? h("div.chips", { style: { marginTop: "6px" } },
        b.spawnLocations.map((l) => badge(`${l.name} ${fmt.pct(l.chance)}`, "muted"))) : null,
      (b.escorts || []).length ? h("div.muted.small", { style: { marginTop: "6px" } }, "Escorts: ",
        b.escorts.map((e) => `${e.boss?.name}${e.amount?.length ? ` ×${Math.max(...e.amount.map((a) => a.count))}` : ""}`).join(", ")) : null))));
}

function extracts(m) {
  const groups = { pmc: new Set(), scav: new Set(), shared: new Set() };
  for (const x of m.extracts || []) {
    if (!x.name) continue;
    const f = (x.faction || "").toLowerCase();
    (groups[f] || groups.shared).add(x.name);
  }
  const col = (title, set, kind) => h("div",
    h("div.section-title", title, badge(String(set.size), kind)),
    set.size ? h("ul.extract-list", [...set].sort().map((n) => h("li", n))) : h("div.muted.small", "None"));
  if (!groups.pmc.size && !groups.scav.size && !groups.shared.size) return empty("No extract data for this map.");
  return h("div.extract-cols",
    col("PMC", groups.pmc, "accent"), col("Scav", groups.scav, "info"), col("Shared", groups.shared, "good"));
}

function keys(m) {
  const locks = (m.locks || []).filter((l) => l.key);
  if (!locks.length) return empty("No locked doors listed for this map.");
  const done = new Set(store.progress?.tasks || []);
  const questKeys = new Map();
  for (const t of peek("tasks") || []) {
    if (done.has(t.id)) continue;
    for (const o of t.objectives || []) {
      for (const k of (o.requiredKeys || []).flat()) if (k) questKeys.set(k.id, t.name);
    }
  }
  const rows = [...new Map(locks.map((l) => [l.key.id + (l.lockType || ""), l])).values()];
  return h("section.card.flush", h("div.card-body", table({
    rows, sortKey: "price", sortDir: "desc",
    columns: [
      { key: "key", label: "Key", sort: (l) => l.key.name, render: (l) => itemChip(l.key, null) },
      { key: "type", label: "Lock", sort: (l) => l.lockType, render: (l) => h("span", (l.lockType || "door").replace(/^\w/, (c) => c.toUpperCase()),
        l.needsPower ? [" ", badge("Needs power", "warn")] : null) },
      { key: "quest", label: "Quests", render: (l) => questKeys.has(l.key.id) ? badge("Needed: " + questKeys.get(l.key.id), "info") : h("span.muted", "–") },
      { key: "price", label: "Price", num: true, sort: (l) => buyPrice(l.key.id)?.price ?? null,
        render: (l) => { const bp = buyPrice(l.key.id); return bp ? fmt.rub(bp.price) : "–"; } },
    ],
  })));
}

function more(m) {
  const transits = m.transits || [];
  const hazards = [...new Map((m.hazards || []).map((x) => [(x.hazardType || "") + (x.name || ""), x])).values()];
  return h("div.grid.cols-2",
    card("Transits", transits.length ? h("div.list", transits.map((t) => h("div.list-row",
      icon("exit", 16, "muted"), h("div.grow", h("div", t.description || `To ${t.map?.name}`), t.conditions ? h("div.muted.small", t.conditions) : null),
      t.map ? h("a", { href: `#/maps/${t.map.normalizedName || ""}` }, t.map.name) : null))) : empty("No transits.")),
    card("Hazards", hazards.length ? h("div.list", hazards.map((x) => h("div.list-row",
      icon("alert", 16, "muted"), h("div.grow", x.name || x.hazardType), badge(x.hazardType || "hazard", "warn")))) : empty("No hazards listed.")),
    m.enemies?.length ? card("Enemies", h("div.chips", m.enemies.map((e) => badge(e, "muted")))) : null);
}
