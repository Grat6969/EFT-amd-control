// Slide-out panel with everything about one item.

import { priceChart } from "./charts.js";
import { itemChip, ownedStepper, sectionTitle, thumb } from "./components.js";
import { api, badge, errorBox, ext, fmt, h, icon, loading, mount } from "./lib.js";
import { fleaFee, item as itemInfo, needsFor, store } from "./store.js";

let drawer, backdrop, body, currentId = null, last = null;

function ensure() {
  if (drawer) return;
  backdrop = document.body.appendChild(h("div.backdrop", { onclick: close }));
  drawer = document.body.appendChild(h("aside.drawer", { role: "dialog", "aria-label": "Item details" },
    h("button.drawer-x", { type: "button", onclick: close, title: "Close (Esc)" }, icon("x", 18)),
    body = h("div.drawer-body")));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
}

export function close() {
  if (!drawer) return;
  drawer.classList.remove("open");
  backdrop.classList.remove("open");
  currentId = null;
}

export async function openItemPanel(id, ref) {
  ensure();
  currentId = id;
  drawer.classList.add("open");
  backdrop.classList.add("open");
  const quick = itemInfo(id) || {};
  mount(body, header(quick, ref), loading("Loading details from tarkov.dev…"));
  let res;
  try {
    res = await api("item/" + encodeURIComponent(id));
  } catch (e) {
    res = { error: e.message };
  }
  if (currentId !== id) return;
  last = { id, ref, res };
  if (!res.item) {
    mount(body, header(quick, ref), quickPrices(quick), needsSection(id),
      errorBox(res.error || "tarkov.dev has no details for this item.", () => openItemPanel(id, ref)));
    return;
  }
  render(id, res.item, res.history || []);
}

// Redraw after progress changes, without downloading again.
export function refreshPanel() {
  if (!last || last.id !== currentId || !drawer?.classList.contains("open")) return;
  const { id, ref, res } = last;
  const scroll = body.scrollTop;
  if (res.item) render(id, res.item, res.history || []);
  else mount(body, header(itemInfo(id) || {}, ref), quickPrices(itemInfo(id) || {}), needsSection(id));
  body.scrollTop = scroll;
}

function header(it, ref) {
  const name = it.name || ref?.name || "Item";
  return h("div.drawer-head",
    thumb(it.image512pxLink || it.gridImageLink || it.icon || it.iconLink || ref?.iconLink, 96, "big"),
    h("div",
      h("h2", name),
      h("div.drawer-meta",
        it.short || it.shortName ? badge(it.short || it.shortName, "muted") : null,
        it.width ? badge(`${it.width}×${it.height}`, "muted", "Size in slots") : it.slots > 1 ? badge(`${it.slots} slots`, "muted") : null,
        it.weight ? badge(`${it.weight} kg`, "muted") : null,
        it.category?.name ? badge(it.category.name, "muted") : null,
        (it.types || it.tags || []).includes("noFlea") || it.banned ? badge("Can't be sold on flea", "bad") : null),
      h("div.drawer-links",
        it.link ? ext(it.link, "tarkov.dev") : null,
        it.wikiLink || it.wiki ? ext(it.wikiLink || it.wiki, "Wiki") : null)));
}

function quickPrices(it) {
  if (!it.id) return null;
  return h("div.stat-grid",
    tile("Flea 24h avg", it.banned ? "Banned" : fmt.rub(it.avg)),
    tile("Lowest now", fmt.rub(it.low)),
    tile("Best trader", it.trader ? fmt.rub(it.traderPrice) : "–", it.trader || ""));
}

function tile(label, value, sub, kind = "") {
  return h("div.stat" + (kind ? "." + kind : ""), h("div.stat-label", label), h("div.stat-value", value),
    sub ? h("div.stat-sub", sub) : null);
}

function render(id, it, history) {
  const flea = it.avg24hPrice || it.lastLowPrice;
  const sell = (it.sellFor || []).filter((o) => o.priceRUB).sort((a, b) => b.priceRUB - a.priceRUB);
  const buy = (it.buyFor || []).filter((o) => o.priceRUB).sort((a, b) => a.priceRUB - b.priceRUB);
  const banned = (it.types || []).includes("noFlea");
  const change = it.changeLast48hPercent;

  mount(body,
    header(it),
    h("div.stat-grid",
      tile("Flea 24h avg", banned ? "Banned" : fmt.rub(it.avg24hPrice), it.lastOfferCount ? `${fmt.num(it.lastOfferCount)} offers` : ""),
      tile("Lowest now", fmt.rub(it.lastLowPrice), it.low24hPrice ? `24h ${fmt.short(it.low24hPrice)}–${fmt.short(it.high24hPrice)}` : ""),
      tile("48h change", change === null || change === undefined ? "–" : fmt.signedPct(change), "", change > 0 ? "up" : change < 0 ? "down" : ""),
      tile("Per slot", flea ? fmt.rub(Math.floor(Math.max(flea, sell[0]?.priceRUB || 0) / Math.max(1, it.width * it.height))) : "–")),
    history.length > 1 ? h("div.drawer-section", sectionTitle("Last 7 days"),
      priceChart(history.map((p) => ({ t: Number(p.timestamp), v: p.price, min: p.priceMin })))) : null,
    needsSection(id),
    sell.length ? h("div.drawer-section", sectionTitle("Sell to"), offerTable(sell, true)) : null,
    buy.length ? h("div.drawer-section", sectionTitle("Buy from"), offerTable(buy, false)) : null,
    !banned ? feeCalc(it) : null,
    tradeList("Barters that give this", it.bartersFor, "barter"),
    tradeList("Barters that use this", it.bartersUsing, "barter"),
    tradeList("Crafts that make this", it.craftsFor, "craft"),
    tradeList("Crafts that use this", it.craftsUsing, "craft"),
    taskList("Quests that need this", it.usedInTasks),
    taskList("Quest rewards", it.receivedFromTasks),
    it.description ? h("div.drawer-section", sectionTitle("Description"), h("p.desc", it.description)) : null);
}

function offerTable(offers, sell) {
  return h("table.tbl.compact", h("tbody", offers.map((o, i) => {
    const v = o.vendor || {};
    const level = !sell && v.minTraderLevel ? ` LL${v.minTraderLevel}` : "";
    const lock = v.taskUnlock ? badge("Quest: " + v.taskUnlock.name, "warn") : null;
    const limit = v.buyLimit ? badge(`limit ${v.buyLimit}`, "muted") : null;
    const native = o.currency && o.currency !== "RUB" ? h("span.muted.small", ` (${o.currency === "USD" ? "$" : "€"}${fmt.num(o.price)})`) : null;
    return h("tr" + (i === 0 ? ".best" : ""),
      h("td", v.name + level, " ", lock, limit),
      h("td.num", fmt.rub(o.priceRUB), native),
      h("td.num", i === 0 ? badge(sell ? "Best" : "Cheapest", "good") : null));
  })));
}

function feeCalc(it) {
  const base = it.basePrice;
  let price = it.lastLowPrice || it.avg24hPrice || base;
  let count = 1;
  const out = h("div.fee-out");
  const bestTrader = (it.sellFor || []).filter((o) => o.vendor?.normalizedName !== "flea-market")
    .reduce((m, o) => Math.max(m, o.priceRUB || 0), 0);
  const update = () => {
    const fee = fleaFee(base, price, count);
    const net = price * count - fee;
    mount(out,
      h("div.fee-row", h("span", "Listing fee"), h("strong.down", fmt.rub(fee))),
      h("div.fee-row", h("span", "You get"), h("strong", fmt.rub(net))),
      bestTrader ? h("div.fee-row", h("span", "vs best trader"),
        h("strong." + (net - bestTrader * count >= 0 ? "up" : "down"), fmt.signedRub(net - bestTrader * count))) : null);
  };
  const priceInput = h("input.num-input", { type: "number", min: 1, value: price, oninput: (e) => { price = Math.max(1, Number(e.target.value) || 1); update(); } });
  const countInput = h("input.num-input.small", { type: "number", min: 1, max: 999, value: 1, oninput: (e) => { count = Math.max(1, Number(e.target.value) || 1); update(); } });
  update();
  const p = store.progress || {};
  return h("div.drawer-section", sectionTitle("Flea market fee", h("span.muted.small",
    p.intel_center >= 3 ? `Intel Center 3 discount on` : "Set Intel Center level in Settings for the discount")),
  h("div.fee", h("label", "Price each", priceInput), h("label", "Count", countInput), out));
}

function needsSection(id) {
  const needs = needsFor(id);
  if (!needs) return null;
  const { entry, alternatives } = needs;
  if (!entry && !alternatives.length) {
    return h("div.drawer-section", sectionTitle("Needed for"),
      h("div.muted", "Not needed for any of your unfinished quests or hideout upgrades."));
  }
  const total = entry ? entry.quest + entry.hideout : 0;
  return h("div.drawer-section.needed-box",
    sectionTitle("Needed for", entry ? h("span.small", "You have ", ownedStepper(id, total)) : null),
    h("ul.need-list",
      (entry?.refs || []).map((r) => h("li",
        badge(r.kind === "quest" ? "Quest" : "Hideout", r.kind === "quest" ? "info" : "accent"),
        h("span", r.name), r.trader ? h("span.muted", ` · ${r.trader}`) : null,
        h("span.need-count", `×${r.count}`), r.fir ? h("span.fir", "FiR") : null)),
      alternatives.map((a) => h("li", badge("Quest", "info"), h("span", a.name),
        h("span.muted", ` · any of ${a.items.length} items`), h("span.need-count", `×${a.count}`)))));
}

function tradeList(title, list, kind) {
  if (!list || !list.length) return null;
  return h("div.drawer-section", sectionTitle(title),
    h("div.trade-list", list.slice(0, 12).map((t) => h("div.trade",
      h("div.trade-src", kind === "barter" ? `${t.trader?.name} ${t.level}` : `${t.station?.name} ${t.level}`,
        kind === "craft" ? h("span.muted", " · " + fmt.duration(t.duration)) : null,
        t.taskUnlock ? badge("Quest", "warn", t.taskUnlock.name) : null),
      h("div.trade-flow",
        h("div.trade-in", (t.requiredItems || []).map((r) => itemChip(r.item, r.count, { compact: true }))),
        icon("chevron", 16, "muted"),
        h("div.trade-out", (t.rewardItems || []).map((r) => itemChip(r.item, r.count, { compact: true }))))))),
    list.length > 12 ? h("div.muted.small", `+${list.length - 12} more`) : null);
}

function taskList(title, tasks) {
  if (!tasks || !tasks.length) return null;
  const done = new Set(store.progress?.tasks || []);
  return h("div.drawer-section", sectionTitle(title),
    h("div.tag-list", tasks.map((t) => h("a.tag" + (done.has(t.id) ? ".done" : ""),
      { href: `#/quests?q=${encodeURIComponent(t.name)}`, onclick: close },
      done.has(t.id) ? icon("check", 13) : null, t.name, h("span.muted", ` · ${t.trader?.name || ""}`)))));
}

