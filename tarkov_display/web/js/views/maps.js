import { itemChip } from "../components.js";
import { badge, button, card, empty, errorBox, ext, fmt, h, icon, img, loading, mount, segmented, stat, table } from "../lib.js";
import { buyPrice, dataset, peek, store } from "../store.js";

export default {
  title: "Maps",
  subtitle: "Map images, bosses, extracts and keys",
  async render(root, { rest }) {
    mount(root, loading("Loading maps from tarkov.dev…"));
    let maps;
    try { maps = await dataset("maps"); } catch (e) {
      mount(root, errorBox(e.message, () => this.render(root, { rest })));
      return;
    }
    dataset("mapimages").catch(() => {});
    dataset("tasks").catch(() => {});
    maps = maps.filter((m) => m.normalizedName).sort((a, b) => a.name.localeCompare(b.name));
    const selected = maps.find((m) => m.normalizedName === rest[0]) || maps.find((m) => m.normalizedName === "customs") || maps[0];
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
  },
};

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

function mapImage(m, all) {
  const entry = imagesFor(m, all);
  const images = entry?.images || [];
  if (!images.length) {
    return empty("No map image for this map.", h("span", "Try the ", ext(`https://tarkov.dev/map/${m.normalizedName}`, "interactive map"), " on tarkov.dev."));
  }
  let current = 0;
  const holder = h("div");
  const draw = () => mount(holder,
    images.length > 1 ? h("div.toolbar", { style: { marginBottom: "10px" } },
      segmented(images.map((im, i) => [String(i), variantLabel(im.key)]), String(current), (v) => { current = Number(v); draw(); })) : null,
    viewer(images[current]));
  draw();
  return holder;
}

function viewer(image) {
  let scale = 1, tx = 0, ty = 0, minScale = 0.05;
  const picture = h("img", { src: image.url, alt: image.key, draggable: "false", referrerpolicy: "no-referrer" });
  const msg = h("div.viewer-msg", h("span", h("span.spinner"), " Loading map image…"));
  const apply = () => { picture.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`; };
  const box = h("div.viewer", msg, picture,
    h("div.viewer-tools",
      button("", () => zoom(1.3), { iconName: "zoomin", title: "Zoom in" }),
      button("", () => zoom(1 / 1.3), { iconName: "zoomout", title: "Zoom out" }),
      button("", fit, { iconName: "expand", title: "Fit" }),
      h("a.btn", { href: image.url, target: "_blank", rel: "noopener noreferrer", title: "Open full size" }, icon("external", 16))),
    image.author ? h("div.viewer-credit", "Map by ",
      image.authorLink ? h("a", { href: image.authorLink, target: "_blank", rel: "noopener noreferrer" }, image.author) : image.author) : null);
  function fit() {
    if (!picture.naturalWidth) return;
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
  picture.addEventListener("load", () => { msg.remove(); fit(); });
  picture.addEventListener("error", () => {
    picture.classList.add("broken");
    mount(msg, h("span", "Couldn't load the map image. ", ext(image.url, "Open it directly")));
  });
  box.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = box.getBoundingClientRect();
    zoom(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });
  let drag = null;
  box.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".viewer-tools, .viewer-credit")) return;
    drag = { x: e.clientX, y: e.clientY, tx, ty };
    box.setPointerCapture(e.pointerId);
    box.classList.add("dragging");
  });
  box.addEventListener("pointermove", (e) => {
    if (!drag) return;
    tx = drag.tx + e.clientX - drag.x;
    ty = drag.ty + e.clientY - drag.y;
    apply();
  });
  const end = () => { drag = null; box.classList.remove("dragging"); };
  box.addEventListener("pointerup", end);
  box.addEventListener("pointercancel", end);
  box.addEventListener("dblclick", (e) => { const r = box.getBoundingClientRect(); zoom(1.8, e.clientX - r.left, e.clientY - r.top); });
  return box;
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
