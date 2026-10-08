// App shell: sidebar, header, routing, live updates from the app.

import { openItem, setItemOpener, thumb } from "./components.js";
import { close as closeItem, openItemPanel, refreshPanel } from "./item.js";
import { fmt, h, icon, mount, toast, TOKEN } from "./lib.js";
import { dataset, emit, invalidate, loadBoot, loadItems, on, peek, searchItems, store } from "./store.js";

const NAV = [
  ["Overview", [["home", "Home", "home"]]],
  ["Market", [["items", "Prices", "items"], ["barters", "Barters", "barters"], ["crafts", "Crafts", "crafts"], ["ammo", "Ammo", "ammo"]]],
  ["Progress", [["quests", "Quests", "quests"], ["hideout", "Hideout", "hideout"], ["needed", "Needed items", "needed"], ["achievements", "Achievements", "achievements"]]],
  ["World", [["maps", "Maps", "maps"], ["bosses", "Bosses", "bosses"], ["traders", "Traders", "traders"]]],
  ["App", [["display", "Display", "display"], ["settings", "Settings", "settings"]]],
];
const VIEW_NAMES = new Set(NAV.flatMap(([, items]) => items.map((i) => i[0])));

let content, titleEl, subEl, navEl, statusEl, footEl;
let current = { name: null, cleanup: null };

function logo() {
  return h("div.logo",
    h("svg", { viewBox: "0 0 32 32", width: 30, height: 30, "aria-hidden": "true" },
      h("polygon", { points: "16,2 28,9 28,23 16,30 4,23 4,9", fill: "none", stroke: "var(--accent)", "stroke-width": 2 }),
      h("circle", { cx: 16, cy: 16, r: 5, fill: "none", stroke: "var(--accent)", "stroke-width": 2 }),
      h("path", { d: "M16 7v5M16 20v5M7 16h5M20 16h5", stroke: "var(--accent)", "stroke-width": 2, "stroke-linecap": "round" })),
    h("div.logo-text", h("div.logo-name", "TARKOV"), h("div.logo-sub", "COMPANION")));
}

function shell() {
  const app = document.getElementById("app");
  navEl = h("nav.nav");
  footEl = h("div.side-foot");
  titleEl = h("h1");
  subEl = h("div.page-sub");
  statusEl = h("div.status-chips");
  content = h("main.content");
  mount(app,
    h("aside.sidebar", logo(), navEl, footEl),
    h("div.main",
      h("header.topbar", h("div.titles", titleEl, subEl), globalSearch(), statusEl),
      content));
  drawNav();
}

function drawNav() {
  mount(navEl, NAV.map(([group, items]) => h("div.nav-group",
    h("div.nav-label", group),
    items.map(([name, label, ic]) => h("a.nav-link" + (current.name === name ? ".active" : ""), { href: "#/" + name },
      icon(ic, 18), h("span", label))))));
}

function drawFoot() {
  const st = store.state || {};
  const upd = st.update || {};
  mount(footEl,
    h("a.mode-pill." + (st.gameMode === "pve" ? "pve" : "pvp"), { href: "#/settings", title: "Change game mode in Settings" },
      st.gameMode === "pve" ? "PvE" : "PvP"),
    upd.available
      ? h("a.update-pill", { href: "#/settings?update=1", title: "A new version is available" }, icon("download", 14), `Update to ${upd.latest}`)
      : h("span.version", `v${store.boot?.version || ""}`));
}

function drawStatus() {
  const st = store.state || {};
  const watcher = st.watcher || "";
  const active = watcher.includes("applied");
  const pricesAge = st.prices?.updated ? fmt.ago(st.prices.updated) : "never";
  mount(statusEl,
    h("a.chip-status" + (active ? ".on" : ""), { href: "#/display", title: watcher },
      h("span.dot"), active ? `Display: ${st.profile}` : st.paused ? "Display paused" : "Game not focused"),
    h("span.chip-status" + (st.prices?.error && !st.prices?.count ? ".bad" : ""), { title: st.prices?.error || "Flea and trader prices" },
      icon("clock", 14), `Prices ${pricesAge}`));
}

// -- global search ----------------------------------------------------------------

function globalSearch() {
  const results = h("div.gs-results");
  const input = h("input", { type: "search", placeholder: "Search items, quests, maps…  (Ctrl+K)", spellcheck: "false" });
  let sel = 0, entries = [];
  const choose = (e) => { results.classList.remove("open"); input.value = ""; e.go(); };
  const draw = () => {
    const q = input.value.trim();
    if (!q) { results.classList.remove("open"); return; }
    const items = searchItems(q, 6).map((it) => ({ kind: "Item", label: it.name, sub: it.short, icon: it.icon, go: () => openItem(it.id) }));
    const ql = q.toLowerCase();
    const quests = (peek("tasks") || []).filter((t) => t.name.toLowerCase().includes(ql)).slice(0, 4)
      .map((t) => ({ kind: "Quest", label: t.name, sub: t.trader?.name, go: () => { location.hash = `#/quests?q=${encodeURIComponent(t.name)}`; } }));
    const maps = (peek("maps") || []).filter((m) => m.name.toLowerCase().includes(ql)).slice(0, 3)
      .map((m) => ({ kind: "Map", label: m.name, sub: m.players ? `${m.players} players` : "", go: () => { location.hash = `#/maps/${m.normalizedName}`; } }));
    entries = [...items, ...quests, ...maps];
    if (!entries.length) entries = [{ kind: "", label: `No matches for “${q}”`, go: () => {} }];
    sel = Math.min(sel, entries.length - 1);
    mount(results, entries.map((e, i) => h("button.gs-row" + (i === sel ? ".sel" : ""), { type: "button", onmousedown: (ev) => { ev.preventDefault(); choose(e); } },
      e.icon !== undefined ? thumb(e.icon, 28) : h("span.gs-kind-ic", icon(e.kind === "Quest" ? "quests" : e.kind === "Map" ? "maps" : "search", 16)),
      h("span.gs-label", e.label), e.sub ? h("span.gs-sub", e.sub) : null, e.kind ? h("span.gs-kind", e.kind) : null)));
    results.classList.add("open");
  };
  input.addEventListener("input", () => { sel = 0; draw(); });
  input.addEventListener("focus", () => { dataset("tasks").catch(() => {}); dataset("maps").catch(() => {}); draw(); });
  input.addEventListener("blur", () => setTimeout(() => results.classList.remove("open"), 120));
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { sel = Math.min(sel + 1, entries.length - 1); draw(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { sel = Math.max(sel - 1, 0); draw(); e.preventDefault(); }
    else if (e.key === "Enter" && entries[sel]) { choose(entries[sel]); input.blur(); }
    else if (e.key === "Escape") { input.value = ""; draw(); input.blur(); }
  });
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); input.focus(); input.select(); }
  });
  return h("div.gsearch", icon("search", 16), input, results);
}

// -- routing ---------------------------------------------------------------------------

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, query] = raw.split("?");
  const [name, ...rest] = path.split("/").filter(Boolean);
  return { name: VIEW_NAMES.has(name) ? name : "home", rest: rest.map(decodeURIComponent), query: Object.fromEntries(new URLSearchParams(query || "")) };
}

async function route() {
  const { name, rest, query } = parseHash();
  closeItem();
  if (current.cleanup) { try { current.cleanup(); } catch (e) { console.error(e); } }
  current = { name, cleanup: null };
  drawNav();
  const mod = await import(`./views/${name}.js`);
  if (current.name !== name) return;
  const view = mod.default;
  titleEl.textContent = view.title;
  subEl.textContent = view.subtitle || "";
  document.title = `${view.title} · Tarkov Companion`;
  const root = h("div.view.view-" + name);
  mount(content, root);
  content.scrollTop = 0;
  try {
    current.cleanup = (await view.render(root, { rest, query })) || null;
  } catch (e) {
    console.error(e);
    mount(root, h("div.error-box", icon("alert", 20), h("div", h("strong", "Something went wrong on this page"), h("div.muted", String(e.message || e)))));
  }
}

// -- live updates -------------------------------------------------------------------------

let reconnecting = false;
function connect() {
  const es = new EventSource(`/api/events?token=${encodeURIComponent(TOKEN)}`);
  const json = (fn) => (e) => { try { fn(JSON.parse(e.data)); } catch (err) { console.error(err); } };
  es.addEventListener("state", json((s) => {
    const prevPrices = store.state?.prices?.updated;
    store.state = s;
    drawStatus(); drawFoot();
    if (s.prices?.updated && s.prices.updated !== prevPrices && prevPrices !== undefined) loadItems().catch(() => {});
    emit("state");
  }));
  es.addEventListener("data", json((d) => { invalidate(d.name); emit("data", d.name); }));
  es.addEventListener("progress", json((p) => { store.progress = p; emit("progress"); }));
  es.addEventListener("display", json((d) => { store.display = d; emit("display"); }));
  es.addEventListener("scan", json((s) => {
    store.scans.unshift(s);
    emit("scan", s);
    if (s.item) toast(`Price check: ${s.item.name}`, { action: () => openItem(s.item.id), actionLabel: "Details" });
    else toast(s.error ? `Price check failed: ${s.error}` : "Price check: couldn't identify the item", { kind: "warn" });
  }));
  es.addEventListener("update", json((u) => { store.state.updating = u; emit("update", u); }));
  es.addEventListener("restarting", () => overlay("Restarting with the new version…"));
  es.addEventListener("reload", () => location.reload());
  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED || !reconnecting) waitForServer(es);
  };
}

function overlay(text) {
  if (document.querySelector(".overlay")) return;
  document.body.appendChild(h("div.overlay", h("div.overlay-box", h("span.spinner"), text)));
}

async function waitForServer(es) {
  if (reconnecting) return;
  reconnecting = true;
  setTimeout(() => { if (reconnecting) overlay("Reconnecting to the app…"); }, 2500);
  for (let i = 0; i < 600; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    try {
      const res = await fetch("/api/hello", { cache: "no-store" });
      if (!res.ok) continue;
      const ok = await fetch("/api/state", { headers: { "X-Token": TOKEN }, cache: "no-store" });
      if (ok.status === 403 || es.readyState === EventSource.CLOSED) { location.reload(); return; }
      if (ok.ok) { reconnecting = false; document.querySelector(".overlay")?.remove(); return; }
    } catch { /* still down */ }
  }
}

// -- boot ------------------------------------------------------------------------------------

async function boot() {
  try {
    await loadBoot();
  } catch (e) {
    mount(document.getElementById("app"), h("div.boot", h("div", "Couldn't start: " + e.message)));
    return;
  }
  shell();
  drawFoot();
  drawStatus();
  setItemOpener(openItemPanel);
  loadItems().catch((e) => toast("Couldn't load prices: " + e.message, { kind: "bad" }));
  ["cashoffers", "flea", "tasks", "hideout"].forEach((n) => dataset(n).catch(() => {}));
  on((kind) => { if (kind === "progress" || kind === "items") refreshPanel(); });
  window.addEventListener("hashchange", route);
  setInterval(drawStatus, 30000);
  connect();
  await route();
}

boot();
