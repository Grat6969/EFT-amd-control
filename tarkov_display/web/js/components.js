// Shared pieces that know about items and progress.

import { badge, fmt, h, icon, img, stepper } from "./lib.js";
import { item, setProgress, store } from "./store.js";

export function thumb(src, size = 40, cls = "") {
  return h("span.thumb" + (cls ? "." + cls : ""), { style: { width: size + "px", height: size + "px" } },
    img(src, { size }));
}

// Item reference: icon + name (+ count); click opens the item panel.
export function itemChip(ref, count, { fir, compact, title } = {}) {
  const id = typeof ref === "string" ? ref : ref?.id;
  const known = item(id);
  const name = known?.short || ref?.shortName || known?.name || ref?.name || "Unknown item";
  const full = known?.name || ref?.name || name;
  const src = known?.icon || ref?.iconLink;
  return h("button.chip" + (compact ? ".compact" : ""), {
    type: "button", title: title || full,
    onclick: (e) => { e.stopPropagation(); openItem(id, ref); },
  },
  thumb(src, compact ? 22 : 28),
  h("span.chip-name", name),
  count !== undefined && count !== null ? h("span.chip-count", "×" + fmt.num(count)) : null,
  fir ? h("span.fir", { title: "Found in raid" }, "FiR") : null);
}

export function itemCell(it, { sub } = {}) {
  return h("div.item-cell", thumb(it.icon || it.iconLink, 36),
    h("div.item-cell-text", h("div.item-name", it.name), h("div.item-sub", sub ?? (it.short || it.shortName || ""))));
}

export function traderAvatar(trader, size = 30) {
  if (!trader) return null;
  return h("span.avatar", { title: trader.name, style: { width: size + "px", height: size + "px" } },
    img(trader.imageLink, { size }), h("span.avatar-fallback", (trader.name || "?")[0]));
}

export function ownedStepper(id, need) {
  const have = (store.progress?.owned || {})[id] || 0;
  const wrap = h("div.owned", { onclick: (e) => e.stopPropagation() },
    stepper(have, 0, 99999, (v) => setProgress({ op: "owned", item: id, count: v })),
    need ? h("span.owned-need", `/ ${fmt.num(need)}`) : null);
  return wrap;
}

export function needBadges(entry) {
  if (!entry) return null;
  return h("span.need-badges",
    entry.quest ? badge(`Q ${entry.quest}`, entry.questFir ? "warn" : "info", entry.questFir ? `${entry.questFir} found in raid` : "For quests") : null,
    entry.hideout ? badge(`H ${entry.hideout}`, "accent", "For hideout") : null);
}

export function changeTag(pct) {
  if (pct === null || pct === undefined) return h("span.muted", "–");
  return h("span." + (pct > 0 ? "up" : pct < 0 ? "down" : "muted"), fmt.signedPct(pct));
}

let opener = null;
export function setItemOpener(fn) { opener = fn; }
export function openItem(id, ref) { if (opener && id) opener(id, ref); }

export function sectionTitle(text, extra) {
  return h("div.section-title", h("span", text), extra || null);
}

export function iconTitle(name, text) {
  return h("span.icon-title", icon(name, 16), text);
}
