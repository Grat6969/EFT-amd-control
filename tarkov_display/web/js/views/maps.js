import { itemChip } from "../components.js";
import { badge, button, card, empty, errorBox, ext, fmt, h, icon, img, loading, local, mount, segmented, select, stat, table, toast } from "../lib.js";
import { buyPrice, dataset, on, peek, setMarkers, store } from "../store.js";

// Markers you add are drawn by every map viewer on screen, and redrawn when
// they change here or in another window (a popped-out map).
const live = new Set();
const redrawAll = () => { for (const fn of [...live]) fn(); };
const COLORS = ["yellow", "red", "green", "blue", "purple", "white"];
const POPOUT_SIZE = "popup,width=980,height=820";

export default {
  title: "Maps",
  subtitle: "Map images, bosses, extracts, keys and your own markers",
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
    const off = on((kind) => { if (kind === "markers") redrawAll(); });
    const cleanup = () => { off(); live.clear(); };
    if (popout) {
      await drawPopout(root, maps, selected, query.image);
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
    if (selected) await drawMap(detail, selected);
    return cleanup;
  },
};

// The popped-out window: a map picker and the map, filling the window.
async function drawPopout(root, maps, m, imageKey) {
  if (!m) { mount(root, empty("No maps yet.")); return; }
  root.classList.add("popout-view");
  mount(root, loading());
  let images = null;
  try { images = await dataset("mapimages"); } catch { images = null; }
  const picker = select(maps.map((x) => [x.normalizedName, x.name]), m.normalizedName,
    (v) => { location.hash = `#/maps/${v}`; }, { title: "Map" });
  mount(root, mapImage(m, images, { popout: true, picker, imageKey }));
}

async function drawMap(root, m) {
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
      mount(body, mapImage(m, images));
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
  const key = all[n] ? n : Object.keys(all).find((k) => n.startsWith(k) || n.endsWith(k) || k.startsWith(n) || n.replace(/^night-/, "") === k || n.replace(/-21$/, "") === k);
  return key ? all[key] : null;
}

function variantLabel(key) {
  const parts = key.split("-");
  const i = parts.findIndex((p) => p === "2d" || p === "3d");
  if (i < 0) return key;
  return [parts[i].toUpperCase(), ...parts.slice(i + 1).map((p) => p[0].toUpperCase() + p.slice(1))].join(" ");
}

function mapImage(m, all, { popout = false, picker = null, imageKey } = {}) {
  const entry = imagesFor(m, all);
  const images = entry?.images || [];
  if (!images.length) {
    return h("div", picker ? h("div.toolbar.map-bar", picker) : null,
      empty("No map image for this map.", h("span", "Try the ", ext(`https://tarkov.dev/map/${m.normalizedName}`, "interactive map"), " on tarkov.dev.")));
  }
  let current = Math.max(0, images.findIndex((im) => im.key === (imageKey || local.get(`mapimage.${m.normalizedName}`))));
  const holder = h("div" + (popout ? ".popout-map" : ""));
  const draw = () => {
    const image = images[current];
    const view = viewer(image, { popout });
    const popOut = () => {
      const url = `/?popout=1#/maps/${m.normalizedName}?image=${encodeURIComponent(image.key)}`;
      if (!window.open(url, "raidready-map", POPOUT_SIZE)) toast("Couldn't open a new window.", { kind: "warn" });
    };
    mount(holder,
      h("div.toolbar.map-bar",
        picker,
        images.length > 1 ? segmented(images.map((im, i) => [String(i), variantLabel(im.key)]), String(current), (v) => {
          current = Number(v);
          local.set(`mapimage.${m.normalizedName}`, images[current].key);
          draw();
        }) : null,
        h("span.grow"),
        view.controls,
        popout ? null : button("Pop out", popOut, { iconName: "external", title: "Open this map in its own window" })),
      view.box,
      markerList(image, view));
  };
  draw();
  return holder;
}

const markersOn = (image) => store.markers?.[image.key] || [];
const firstLine = (note) => (note || "").split("\n")[0];

// Pan and zoom a map image; right-click (or "Add marker" then click) to drop
// a marker, click a marker to edit its note, drag it to move it.
function viewer(image, { popout = false } = {}) {
  let scale = 1, tx = 0, ty = 0, minScale = 0.05;
  let adding = false, editing = null;
  let labels = local.get("map.labels", true);
  const picture = h("img", { src: image.url, alt: image.key, draggable: "false", referrerpolicy: "no-referrer" });
  const msg = h("div.viewer-msg", h("span", h("span.spinner"), " Loading map image…"));
  const layer = h("div.marker-layer");
  const editor = h("div.marker-editor", { hidden: true });
  const loaded = () => picture.naturalWidth > 0;
  // image fraction <-> position in the viewer
  const toScreen = (x, y) => [tx + x * picture.naturalWidth * scale, ty + y * picture.naturalHeight * scale];
  const toImage = (cx, cy) => [(cx - tx) / (picture.naturalWidth * scale), (cy - ty) / (picture.naturalHeight * scale)];
  const local_ = (e) => { const r = box.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };

  const place = () => {
    for (const pin of layer.children) {
      const [x, y] = toScreen(Number(pin.dataset.x), Number(pin.dataset.y));
      pin.style.transform = `translate(${x}px, ${y}px)`;
    }
    placeEditor();
  };
  const apply = () => { picture.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`; place(); };

  const addBtn = button("Add marker", () => setAdding(!adding), { iconName: "plus", title: "Then click the map. Or right-click the map at any time." });
  const labelBtn = button("Labels", () => { labels = !labels; local.set("map.labels", labels); drawPins(); labelBtn.classList.toggle("on", labels); },
    { iconName: "eye", title: "Show notes next to markers" });
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
    const r = box.getBoundingClientRect();
    if (scale < minScale * 3) scale = Math.min(6, minScale * 4);
    tx = r.width / 2 - mk.x * picture.naturalWidth * scale;
    ty = r.height / 2 - mk.y * picture.naturalHeight * scale;
    apply();
    openEditor(id);
  }

  const box = h("div.viewer" + (popout ? ".tall" : ""), msg, picture, layer, editor,
    h("div.viewer-tools",
      button("", () => zoom(1.3), { iconName: "zoomin", title: "Zoom in" }),
      button("", () => zoom(1 / 1.3), { iconName: "zoomout", title: "Zoom out" }),
      button("", fit, { iconName: "expand", title: "Fit" }),
      h("a.btn", { href: image.url, target: "_blank", rel: "noopener noreferrer", title: "Open full size" }, icon("external", 16))),
    image.author ? h("div.viewer-credit", "Map by ",
      image.authorLink ? h("a", { href: image.authorLink, target: "_blank", rel: "noopener noreferrer" }, image.author) : image.author) : null);
  function fit() {
    if (!loaded()) return;
    const r = box.getBoundingClientRect();
    scale = Math.min(r.width / picture.naturalWidth, r.height / picture.naturalHeight);
    minScale = scale * 0.5;
    tx = (r.width - picture.naturalWidth * scale) / 2;
    ty = (r.height - picture.naturalHeight * scale) / 2;
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
  const inUi = (e) => e.target.closest(".viewer-tools, .viewer-credit, .marker-editor, .marker-pin");
  picture.addEventListener("load", () => { msg.remove(); fit(); });
  picture.addEventListener("error", () => {
    picture.classList.add("broken");
    mount(msg, h("span", "Couldn't load the map image. ", ext(image.url, "Open it directly")));
  });
  box.addEventListener("wheel", (e) => {
    if (e.target.closest(".marker-editor")) return;
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
  new ResizeObserver(() => { if (loaded()) place(); }).observe(box);

  const redraw = () => { if (!box.isConnected) live.delete(redraw); else drawPins(); };
  live.add(redraw);
  drawPins();
  return { box, controls: h("div.map-marker-tools", addBtn, labelBtn), focus };
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
