import { itemChip, traderAvatar } from "../components.js";
import { badge, errorBox, fmt, h, loading, local, mount, searchInput, segmented, table, toggle } from "../lib.js";
import { buyPrice, dataset, on, sellValue } from "../store.js";

const state = { q: "", trader: null, level: "all", profitable: local.get("barters.profit", false), sort: "profit", dir: "desc" };

export function tradeCost(required) {
  let cost = 0, missing = 0;
  for (const r of required || []) {
    if (!r.item) continue;
    if ((r.attributes || []).some((a) => a.type === "tool")) continue; // tools aren't used up
    const bp = buyPrice(r.item.id);
    if (bp) cost += bp.price * (r.count || 1); else missing++;
  }
  return { cost, missing };
}

export function tradeValue(rewards) {
  let value = 0, missing = 0;
  for (const r of rewards || []) {
    if (!r.item) continue;
    const sv = sellValue(r.item.id);
    if (sv) value += sv.value * (r.count || 1); else missing++;
  }
  return { value, missing };
}

export function profitCell(row) {
  if (row.missing) return h("span.muted", { title: "Some items have no price" }, "?");
  return h("span." + (row.profit >= 0 ? "profit-pos" : "profit-neg"), fmt.signedRub(row.profit));
}

export default {
  title: "Barters",
  subtitle: "Every trader barter with today's cost, value and profit",
  async render(root) {
    mount(root, loading("Loading barters from tarkov.dev…"));
    let barters;
    try { barters = await dataset("barters"); } catch (e) {
      mount(root, errorBox(e.message, () => this.render(root)));
      return;
    }
    dataset("cashoffers").catch(() => {});
    const traders = [...new Map(barters.map((b) => [b.trader?.id, b.trader])).values()].filter(Boolean).sort((a, b) => a.name.localeCompare(b.name));
    const chips = h("div.filters");
    const body = h("div");
    const draw = () => {
      local.set("barters.profit", state.profitable);
      let rows = barters.map((b) => {
        const c = tradeCost(b.requiredItems), v = tradeValue(b.rewardItems);
        return { ...b, cost: c.cost, value: v.value, profit: v.value - c.cost, missing: c.missing + v.missing };
      });
      if (state.trader) rows = rows.filter((r) => r.trader?.id === state.trader);
      if (state.level !== "all") rows = rows.filter((r) => r.level <= Number(state.level));
      if (state.profitable) rows = rows.filter((r) => !r.missing && r.profit > 0);
      if (state.q) {
        const q = state.q.toLowerCase();
        rows = rows.filter((r) => [...r.requiredItems, ...r.rewardItems].some((x) => (x.item?.name || "").toLowerCase().includes(q) || (x.item?.shortName || "").toLowerCase().includes(q)));
      }
      mount(body, h("section.card.flush", h("div.card-body", table({
        rows, sortKey: state.sort, sortDir: state.dir, onSort: (k, d) => { state.sort = k; state.dir = d; draw(); },
        emptyText: "No barters match.",
        columns: [
          { key: "trader", label: "Trader", sort: (r) => r.trader?.name + r.level, render: (r) => h("div.item-cell", traderAvatar(r.trader, 30),
            h("div", h("div", r.trader?.name), h("div.muted.small", `Level ${r.level}`))) },
          { key: "give", label: "You give", render: (r) => h("div.chips", r.requiredItems.map((x) => itemChip(x.item, x.count, { compact: true }))) },
          { key: "get", label: "You get", render: (r) => h("div.chips", r.rewardItems.map((x) => itemChip(x.item, x.count, { compact: true })),
            r.taskUnlock ? badge("Quest", "warn", "Unlocked by " + r.taskUnlock.name) : null,
            r.buyLimit ? badge(`limit ${r.buyLimit}`, "muted") : null) },
          { key: "cost", label: "Cost", num: true, sort: (r) => r.cost, render: (r) => fmt.rub(r.cost) },
          { key: "value", label: "Value", num: true, sort: (r) => r.value, render: (r) => fmt.rub(r.value) },
          { key: "profit", label: "Profit", num: true, sort: (r) => (r.missing ? null : r.profit), render: profitCell },
        ],
      }))));
    };
    const drawChips = () => mount(chips,
      h("button.fchip" + (!state.trader ? ".on" : ""), { type: "button", onclick: () => { state.trader = null; drawChips(); draw(); } }, "All traders"),
      traders.map((t) => h("button.fchip" + (state.trader === t.id ? ".on" : ""), {
        type: "button", onclick: () => { state.trader = state.trader === t.id ? null : t.id; drawChips(); draw(); },
      }, traderAvatar(t, 20), t.name)));
    drawChips();
    mount(root,
      h("div.toolbar",
        searchInput("Find barters by item…", state.q, (v) => { state.q = v; draw(); }),
        h("span.muted.small", "Trader level up to"),
        segmented([["all", "Any"], ["1", "1"], ["2", "2"], ["3", "3"], ["4", "4"]], state.level, (v) => { state.level = v; draw(); seg(); }),
        toggle("Profitable only", state.profitable, (v) => { state.profitable = v; draw(); })),
      chips,
      h("div.note", "Cost uses the cheapest way to buy each item (flea lowest or a trader). Value is the best of selling on flea after the fee or to a trader."),
      body);
    function seg() {
      const s = root.querySelector(".seg");
      if (s) [...s.children].forEach((b, i) => b.classList.toggle("on", ["all", "1", "2", "3", "4"][i] === state.level));
    }
    draw();
    return on((kind, detail) => { if (kind === "items" || kind === "progress" || (kind === "data" && ["cashoffers", "flea"].includes(detail))) draw(); });
  },
};
