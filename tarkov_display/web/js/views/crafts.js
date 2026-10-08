import { itemChip } from "../components.js";
import { badge, errorBox, fmt, h, loading, local, mount, searchInput, table, toggle } from "../lib.js";
import { dataset, on, store } from "../store.js";
import { profitCell, tradeCost, tradeValue } from "./barters.js";

const state = { q: "", station: null, profitable: local.get("crafts.profit", false), mine: false, sort: "perHour", dir: "desc" };

export default {
  title: "Crafts",
  subtitle: "Hideout crafts ranked by profit per hour",
  async render(root) {
    mount(root, loading("Loading crafts from tarkov.dev…"));
    let crafts;
    try { crafts = await dataset("crafts"); } catch (e) {
      mount(root, errorBox(e.message, () => this.render(root)));
      return;
    }
    dataset("cashoffers").catch(() => {});
    const stations = [...new Map(crafts.map((c) => [c.station?.id, c.station])).values()].filter(Boolean).sort((a, b) => a.name.localeCompare(b.name));
    const chips = h("div.filters");
    const body = h("div");
    const draw = () => {
      local.set("crafts.profit", state.profitable);
      const built = store.progress.hideout || {};
      let rows = crafts.map((c) => {
        const cost = tradeCost(c.requiredItems), value = tradeValue(c.rewardItems);
        const profit = value.value - cost.cost;
        return { ...c, cost: cost.cost, value: value.value, profit, missing: cost.missing + value.missing,
          perHour: c.duration ? profit / (c.duration / 3600) : null };
      });
      if (state.station) rows = rows.filter((r) => r.station?.id === state.station);
      if (state.mine) rows = rows.filter((r) => (built[r.station?.id] || 0) >= r.level);
      if (state.profitable) rows = rows.filter((r) => !r.missing && r.profit > 0);
      if (state.q) {
        const q = state.q.toLowerCase();
        rows = rows.filter((r) => [...r.requiredItems, ...r.rewardItems].some((x) => (x.item?.name || "").toLowerCase().includes(q)));
      }
      mount(body, h("section.card.flush", h("div.card-body", table({
        rows, sortKey: state.sort, sortDir: state.dir, onSort: (k, d) => { state.sort = k; state.dir = d; draw(); },
        emptyText: "No crafts match.",
        columns: [
          { key: "station", label: "Station", sort: (r) => r.station?.name + r.level, render: (r) => h("div",
            h("div", r.station?.name), h("div.muted.small", `Level ${r.level} · ${fmt.duration(r.duration)}`)) },
          { key: "in", label: "Uses", render: (r) => h("div.chips", r.requiredItems.map((x) => {
            const tool = (x.attributes || []).some((a) => a.type === "tool");
            return itemChip(x.item, tool ? null : x.count, { compact: true, title: tool ? `${x.item?.name} (tool, not used up)` : undefined });
          })) },
          { key: "out", label: "Makes", render: (r) => h("div.chips", r.rewardItems.map((x) => itemChip(x.item, x.count, { compact: true })),
            r.taskUnlock ? badge("Quest", "warn", "Unlocked by " + r.taskUnlock.name) : null) },
          { key: "cost", label: "Cost", num: true, sort: (r) => r.cost, render: (r) => fmt.rub(r.cost) },
          { key: "value", label: "Value", num: true, sort: (r) => r.value, render: (r) => fmt.rub(r.value) },
          { key: "profit", label: "Profit", num: true, sort: (r) => (r.missing ? null : r.profit), render: profitCell },
          { key: "perHour", label: "Per hour", num: true, sort: (r) => (r.missing ? null : r.perHour),
            render: (r) => r.missing || r.perHour === null ? "–" : h("span." + (r.perHour >= 0 ? "profit-pos" : "profit-neg"), fmt.signedRub(r.perHour)) },
        ],
      }))));
    };
    const drawChips = () => mount(chips,
      h("button.fchip" + (!state.station ? ".on" : ""), { type: "button", onclick: () => { state.station = null; drawChips(); draw(); } }, "All stations"),
      stations.map((s) => h("button.fchip" + (state.station === s.id ? ".on" : ""), {
        type: "button", onclick: () => { state.station = state.station === s.id ? null : s.id; drawChips(); draw(); },
      }, s.name)));
    drawChips();
    mount(root,
      h("div.toolbar",
        searchInput("Find crafts by item…", state.q, (v) => { state.q = v; draw(); }),
        toggle("Profitable only", state.profitable, (v) => { state.profitable = v; draw(); }),
        toggle("Only stations I've built", state.mine, (v) => { state.mine = v; draw(); }, "Uses the levels you set on the Hideout page")),
      chips,
      h("div.note", "Fuel and skill bonuses aren't included. Tools (like a toolset) are shown without a count and aren't counted as a cost."),
      body);
    draw();
    return on((kind, detail) => { if (kind === "items" || kind === "progress" || (kind === "data" && ["cashoffers", "flea"].includes(detail))) draw(); });
  },
};
