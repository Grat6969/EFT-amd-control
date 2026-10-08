import { itemCell, itemChip, openItem, ownedStepper } from "../components.js";
import { badge, card, errorBox, fmt, h, loading, local, mount, searchInput, segmented, stat, table, toggle } from "../lib.js";
import { buyPrice, dataset, neededItems, on, store } from "../store.js";

const state = {
  source: local.get("needed.source", "all"), kappa: false, firOnly: false,
  hideDone: local.get("needed.hideDone", true), q: "", sort: "cost", dir: "desc",
};

export default {
  title: "Needed items",
  subtitle: "Everything your unfinished quests and hideout upgrades still need",
  async render(root) {
    mount(root, loading("Loading quests and hideout…"));
    let tasks, stations;
    try {
      [tasks, stations] = await Promise.all([dataset("tasks"), dataset("hideout")]);
    } catch (e) {
      mount(root, errorBox(e.message, () => this.render(root)));
      return;
    }
    dataset("cashoffers").catch(() => {});
    const summary = h("div.stat-grid");
    const body = h("div");
    const draw = () => {
      local.set("needed.source", state.source); local.set("needed.hideDone", state.hideDone);
      const owned = store.progress.owned || {};
      const { items, anyOf } = neededItems({ tasks, stations, kappaOnly: state.kappa, source: state.source });
      let rows = items.map((e) => {
        const need = e.quest + e.hideout;
        const have = Math.min(owned[e.id] || 0, need);
        const left = need - have;
        const bp = buyPrice(e.id);
        return { ...e, need, have, left, unit: bp?.price ?? null, unitSrc: bp?.source, cost: bp ? bp.price * left : null };
      });
      if (state.firOnly) rows = rows.filter((r) => r.questFir > 0);
      const totalLeft = rows.reduce((s, r) => s + r.left, 0);
      const totalCost = rows.reduce((s, r) => s + (r.cost || 0), 0);
      mount(summary,
        stat("Different items", fmt.num(rows.filter((r) => r.left > 0).length)),
        stat("Pieces still needed", fmt.num(totalLeft), { kind: "accent" }),
        stat("Found in raid", fmt.num(rows.reduce((s, r) => s + (r.questFir ? Math.max(0, r.questFir - r.have) : 0), 0)), { sub: "quest items that must be FiR" }),
        stat("Cost to buy the rest", fmt.rub(totalCost), { sub: "cheapest of flea or traders" }));
      if (state.hideDone) rows = rows.filter((r) => r.left > 0);
      if (state.q) {
        const q = state.q.toLowerCase();
        rows = rows.filter((r) => (r.item.name + " " + (r.item.shortName || "")).toLowerCase().includes(q));
      }
      mount(body,
        h("section.card.flush", h("div.card-body", table({
          rows, sortKey: state.sort, sortDir: state.dir,
          onSort: (k, d) => { state.sort = k; state.dir = d; draw(); },
          onRow: (r) => openItem(r.id, r.item),
          rowClass: (r) => (r.left === 0 ? "done" : null),
          emptyText: "Nothing left to collect. Nice.",
          columns: [
            { key: "name", label: "Item", sort: (r) => r.item.name, render: (r) => itemCell({ ...r.item, icon: store.itemsById.get(r.id)?.icon || r.item.iconLink }) },
            { key: "for", label: "For", render: (r) => h("div.chips",
              r.quest ? badge(`Quests ${r.quest}`, "info", r.refs.filter((x) => x.kind === "quest").map((x) => x.name).join(", ")) : null,
              r.questFir ? badge(`FiR ${r.questFir}`, "warn") : null,
              r.hideout ? badge(`Hideout ${r.hideout}`, "accent", r.refs.filter((x) => x.kind === "hideout").map((x) => x.name).join(", ")) : null) },
            { key: "have", label: "Have", sort: (r) => r.have, render: (r) => ownedStepper(r.id, r.need) },
            { key: "left", label: "Still need", num: true, sort: (r) => r.left, render: (r) => r.left ? h("strong", fmt.num(r.left)) : badge("Done", "good") },
            { key: "unit", label: "Price each", num: true, sort: (r) => r.unit, render: (r) => r.unit ? h("div", fmt.rub(r.unit), h("div.muted.small", r.unitSrc)) : "–" },
            { key: "cost", label: "Cost", num: true, sort: (r) => r.cost, render: (r) => r.cost ? fmt.rub(r.cost) : "–" },
          ],
        }))),
        anyOf.length && state.source !== "hideout" ? card("Quests that take any one of several items", h("div.list",
          anyOf.map((a) => h("div.list-row",
            h("div", { style: { minWidth: "220px" } }, h("div", a.name), h("div.muted.small", `${a.trader || ""} · ×${a.count}${a.fir ? " · FiR" : ""}`)),
            h("div.chips.grow", a.items.slice(0, 10).map((it) => itemChip(it, null, { compact: true })),
              a.items.length > 10 ? h("span.muted.small", `+${a.items.length - 10} more`) : null)))), { sub: "pick whichever is cheapest" }) : null);
    };
    mount(root, summary,
      h("div.toolbar",
        searchInput("Filter items…", state.q, (v) => { state.q = v; draw(); }),
        segmented([["all", "Quests + hideout"], ["quests", "Quests"], ["hideout", "Hideout"]], state.source, (v) => { state.source = v; draw(); rebuild(); }),
        toggle("Kappa quests only", state.kappa, (v) => { state.kappa = v; draw(); }),
        toggle("Found in raid only", state.firOnly, (v) => { state.firOnly = v; draw(); }),
        toggle("Hide collected", state.hideDone, (v) => { state.hideDone = v; draw(); })),
      body);
    function rebuild() {
      const seg = root.querySelector(".seg");
      if (seg) [...seg.children].forEach((b, i) => b.classList.toggle("on", ["all", "quests", "hideout"][i] === state.source));
    }
    draw();
    return on((kind, detail) => {
      if (kind === "progress" || kind === "items" || (kind === "data" && detail === "cashoffers")) draw();
    });
  },
};
