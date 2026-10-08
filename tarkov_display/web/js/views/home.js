import { itemCell, openItem, thumb, traderAvatar } from "../components.js";
import { badge, card, empty, ext, fmt, h, icon, loading, mount, progressBar } from "../lib.js";
import { dataset, fleaPrice, on, peek, perSlot, questContext, questState, store } from "../store.js";

const STATUS = {
  0: ["ok", "All systems normal"], 1: ["info", "Updating"], 2: ["warn", "Unstable"], 3: ["bad", "Down"],
};

export default {
  title: "Home",
  subtitle: "Escape from Tarkov at a glance",
  render(root) {
    const cards = {
      status: h("div"), traders: h("div"), goons: h("div"), progress: h("div"),
      display: h("div"), wipe: h("div"), scans: h("div"), value: h("div"),
    };
    mount(root,
      h("div.grid.cols-3",
        card("Game servers", cards.status, { actions: ext("https://status.escapefromtarkov.com/", "status page") }),
        card("Trader resets", cards.traders),
        card("Goons last seen", cards.goons, { sub: "reported by players" })),
      h("div.grid.cols-3",
        card("Your progress", cards.progress, { actions: h("a.btn.ghost.small", { href: "#/quests" }, "Quests") }),
        card("Display", cards.display, { actions: h("a.btn.ghost.small", { href: "#/display" }, "Settings") }),
        card("Wipe", cards.wipe)),
      h("div.grid.cols-2",
        card("Recent price checks", cards.scans, { sub: "Ctrl+Alt+P in game" }),
        card("Best value per slot", cards.value, { sub: "flea or trader, before fees", cls: "flush" })));

    const fill = (el, name, draw) => {
      mount(el, loading());
      dataset(name).then((data) => draw(el, data)).catch((e) => mount(el, h("div.muted", e.message)));
    };
    fill(cards.status, "status", drawStatus);
    fill(cards.traders, "traders", drawTraders);
    fill(cards.goons, "goons", drawGoons);
    fill(cards.wipe, "wipes", drawWipe);
    drawProgress(cards.progress);
    drawDisplay(cards.display);
    drawScans(cards.scans);
    drawValue(cards.value);

    const timer = setInterval(() => tickCountdowns(root), 1000);
    const off = on((kind, detail) => {
      if (kind === "state") drawDisplay(cards.display);
      if (kind === "scan") drawScans(cards.scans);
      if (kind === "items") drawValue(cards.value);
      if (kind === "progress" || (kind === "data" && (detail === "tasks" || detail === "hideout"))) drawProgress(cards.progress);
      if (kind === "data" && detail === "traders") fill(cards.traders, "traders", drawTraders);
      if (kind === "data" && detail === "status") fill(cards.status, "status", drawStatus);
      if (kind === "data" && detail === "goons") fill(cards.goons, "goons", drawGoons);
    });
    return () => { clearInterval(timer); off(); };
  },
};

function drawStatus(el, status) {
  const general = status.generalStatus || {};
  const [kind, fallback] = STATUS[general.status] || ["", "Unknown"];
  const open = (status.messages || []).filter((m) => !m.solveTime).slice(0, 2);
  mount(el,
    h("div.status-big", h("span.status-dot." + kind), h("div",
      h("div.status-title", general.message || fallback),
      h("div.muted.small", general.name || "Escape from Tarkov"))),
    h("div.svc-list", (status.currentStatuses || []).map((s) => {
      const [k] = STATUS[s.status] || [""];
      return h("div.svc", { title: s.message || "" }, h("span.status-dot." + k), s.name);
    })),
    open.map((m) => h("div.note.warn", { style: { marginTop: "12px" } }, icon("alert", 16),
      h("div", m.content, h("div.small.muted", fmt.ago(Date.parse(m.time)))))));
}

function drawTraders(el, traders) {
  const list = [...traders].filter((t) => t.resetTime).sort((a, b) => Date.parse(a.resetTime) - Date.parse(b.resetTime));
  if (!list.length) return mount(el, empty("No reset times right now."));
  mount(el, h("div.list", list.map((t) => h("div.list-row",
    traderAvatar(t, 30), h("div.grow", t.name),
    h("span.countdown", { dataset: { reset: Date.parse(t.resetTime) } }, fmt.countdown(Date.parse(t.resetTime) - Date.now()))))));
}

function tickCountdowns(root) {
  for (const el of root.querySelectorAll("[data-reset]")) {
    const left = Number(el.dataset.reset) - Date.now();
    el.textContent = left > 0 ? fmt.countdown(left) : "resetting…";
    el.classList.toggle("soon", left > 0 && left < 15 * 60 * 1000);
  }
}

function drawGoons(el, reports) {
  if (!reports.length) return mount(el, empty("No recent reports."));
  const [latest, ...older] = reports;
  mount(el,
    h("div.big-num", latest.map?.name || "Unknown"),
    h("div.big-sub", fmt.ago(Number(latest.timestamp)), " · ", h("a", { href: `#/maps/${latest.map?.normalizedName || ""}` }, "map info")),
    h("div.list", { style: { marginTop: "10px" } }, older.slice(0, 4).map((r) => h("div.list-row",
      icon("maps", 16, "muted"), h("div.grow", r.map?.name || "Unknown"), h("span.muted.small", fmt.ago(Number(r.timestamp)))))),
    h("div.muted.small", { style: { marginTop: "8px" } }, "Player reports via tarkov.dev; treat as a hint, not a guarantee."));
}

function drawProgress(el) {
  const tasks = peek("tasks"), stations = peek("hideout");
  if (!tasks) {
    mount(el, loading("Loading quests…"));
    dataset("tasks").then(() => drawProgress(el)).catch((e) => mount(el, h("div.muted", e.message)));
    return;
  }
  const ctx = questContext(tasks);
  const mine = tasks.filter((t) => questState(t, ctx) !== "other");
  const done = mine.filter((t) => ctx.done.has(t.id)).length;
  const available = mine.filter((t) => questState(t, ctx) === "available").length;
  const kappa = mine.filter((t) => t.kappaRequired);
  const kappaDone = kappa.filter((t) => ctx.done.has(t.id)).length;
  const p = store.progress;
  let hideoutBuilt = 0, hideoutTotal = 0;
  for (const s of stations || []) {
    hideoutTotal += (s.levels || []).length;
    hideoutBuilt += Math.min(p.hideout[s.id] || 0, (s.levels || []).length);
  }
  const row = (label, a, b, kind) => h("div", { style: { marginBottom: "12px" } },
    h("div.meter-label", h("span", label), h("span", `${a} / ${b}`)), progressBar(a, b, kind));
  mount(el,
    h("div", { style: { display: "flex", gap: "18px", marginBottom: "14px" } },
      h("div", h("div.big-num", available), h("div.big-sub", "quests available")),
      h("div", h("div.big-num", `L${p.player_level}`), h("div.big-sub", p.faction))),
    row("Quests done", done, mine.length),
    row("Kappa quests", kappaDone, kappa.length, "good"),
    stations ? row("Hideout levels", hideoutBuilt, hideoutTotal, "info") : null);
}

function drawDisplay(el) {
  const st = store.state || {};
  const active = (st.watcher || "").includes("applied");
  mount(el,
    h("div.status-big", h("span.status-dot." + (active ? "ok" : "")), h("div",
      h("div.status-title", active ? `Profile “${st.profile}” on` : st.paused ? "Paused" : "Waiting for the game"),
      h("div.muted.small", st.watcher || ""))),
    h("dl.kv", { style: { marginTop: "14px" } },
      h("dt", "Profile"), h("dd", st.profile || "–"),
      h("dt", "Auto-boost"), h("dd", st.auto?.enabled
        ? (st.auto.scene !== null && st.auto.scene !== undefined ? `on · scene ${fmt.pct(st.auto.scene)} · boost ${fmt.pct(st.auto.boost)}` : "on")
        : "off"),
      h("dt", "Hotkeys"), h("dd", h("kbd", "Ctrl+Alt+1–9"), " profiles  ", h("kbd", "Ctrl+Alt+P"), " price check")));
}

function drawWipe(el, wipes) {
  const sorted = [...wipes].sort((a, b) => Date.parse(b.start) - Date.parse(a.start));
  const cur = sorted[0];
  if (!cur) return mount(el, empty("No wipe data."));
  const days = Math.floor((Date.now() - Date.parse(cur.start)) / 86400000);
  const prev = sorted[1];
  const lastLen = prev ? Math.round((Date.parse(cur.start) - Date.parse(prev.start)) / 86400000) : null;
  mount(el,
    h("div.big-num", `Day ${days + 1}`),
    h("div.big-sub", `Patch ${cur.name} · started ${fmt.date(cur.start)}`),
    lastLen ? h("div.muted.small", { style: { marginTop: "10px" } }, `The previous wipe lasted ${lastLen} days.`) : null);
}

function drawScans(el) {
  const scans = store.scans;
  if (!scans.length) {
    return mount(el, empty("No price checks yet.", "In game, hover over an item until its name shows, then press Ctrl+Alt+P."));
  }
  mount(el, h("div.list", scans.slice(0, 6).map((s) => {
    const it = s.item ? store.itemsById.get(s.item.id) : null;
    return h("div.list-row", { style: { cursor: it ? "pointer" : "default" }, onclick: it ? () => openItem(it.id) : null },
      it ? thumb(it.icon, 34) : h("span.thumb", { style: { width: "34px", height: "34px" } }, icon("search", 16, "muted")),
      h("div.grow", h("div", s.item ? s.item.name : "Not identified"), h("div.muted.small", fmt.ago(s.time))),
      it ? h("span.val", fmt.rub(fleaPrice(it) || it.traderPrice)) : badge(s.error ? "error" : "no match", "warn"));
  })));
}

function drawValue(el) {
  if (!store.items.length) return mount(el, loading("Loading prices…"));
  const best = store.items.filter((it) => !it.tags?.includes("preset") && (fleaPrice(it) || it.traderPrice))
    .map((it) => [perSlot(it), it]).sort((a, b) => b[0] - a[0]).slice(0, 8);
  mount(el, h("table.tbl", h("tbody", best.map(([v, it]) => h("tr.click", { onclick: () => openItem(it.id) },
    h("td", itemCell(it, { sub: `${it.short} · ${it.slots} slot${it.slots > 1 ? "s" : ""}` })),
    h("td.num", h("div", fmt.rub(v)), h("div.muted.small", "per slot")))))));
}

