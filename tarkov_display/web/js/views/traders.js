import { itemCell, openItem, traderAvatar } from "../components.js";
import { badge, card, errorBox, fmt, h, loading, mount, searchInput, table } from "../lib.js";
import { dataset, on } from "../store.js";

const state = { trader: null, q: "" };

export default {
  title: "Traders",
  subtitle: "Restock timers, loyalty levels and what each trader sells",
  async render(root) {
    mount(root, loading("Loading traders from tarkov.dev…"));
    let traders;
    try { traders = await dataset("traders"); } catch (e) {
      mount(root, errorBox(e.message, () => this.render(root)));
      return;
    }
    traders = traders.filter((t) => t.levels?.length).sort((a, b) => a.name.localeCompare(b.name));
    const offers = h("div");
    const drawOffers = async () => {
      const t = traders.find((x) => x.id === state.trader);
      if (!t) return mount(offers);
      mount(offers, loading(`Loading ${t.name}'s stock…`));
      let all;
      try { all = await dataset("cashoffers"); } catch (e) { return mount(offers, errorBox(e.message, drawOffers)); }
      const mine = (all.find((x) => x.id === t.id)?.cashOffers || []).filter((o) => o.item);
      const filtered = state.q ? mine.filter((o) => (o.item.name + " " + o.item.shortName).toLowerCase().includes(state.q.toLowerCase())) : mine;
      mount(offers, card(`${t.name} sells`, h("div",
        h("div.toolbar", { style: { padding: "12px 16px" } }, searchInput("Filter stock…", state.q, (v) => { state.q = v; drawOffers(); })),
        table({
          rows: filtered, sortKey: "level", sortDir: "asc", onRow: (o) => openItem(o.item.id, o.item),
          emptyText: "Nothing listed.",
          columns: [
            { key: "name", label: "Item", sort: (o) => o.item.name, render: (o) => itemCell(o.item) },
            { key: "level", label: "Level", num: true, sort: (o) => o.minTraderLevel || 1, render: (o) => `LL${o.minTraderLevel || 1}` },
            { key: "lock", label: "", render: (o) => [o.taskUnlock ? badge("Quest: " + o.taskUnlock.name, "warn") : null, o.buyLimit ? badge(`limit ${o.buyLimit}`, "muted") : null] },
            { key: "price", label: "Price", num: true, sort: (o) => o.priceRUB, render: (o) => h("div", fmt.rub(o.priceRUB),
              o.currency && o.currency !== "RUB" ? h("div.muted.small", `${o.currency === "USD" ? "$" : "€"}${fmt.num(o.price)}`) : null) },
          ],
        })), { cls: "flush" }));
    };
    const grid = h("div.grid.auto");
    const drawGrid = () => mount(grid, traders.map((t) => {
      const reset = t.resetTime ? Date.parse(t.resetTime) : null;
      return card(null, h("div.trader-card",
        h("div.trader-top",
          traderAvatar(t, 64),
          h("div", { style: { flex: 1 } },
            h("div.trader-name", t.name),
            reset ? h("div.muted.small", "Restock in ", h("span.countdown", { dataset: { reset } }, fmt.countdown(reset - Date.now()))) : null,
            t.currency ? h("div.muted.small", `Pays in ${t.currency.shortName || t.currency.name}`) : null),
          h("button.btn.small" + (state.trader === t.id ? ".primary" : ""), {
            type: "button", onclick: () => { state.trader = state.trader === t.id ? null : t.id; state.q = ""; drawGrid(); drawOffers(); },
          }, state.trader === t.id ? "Hide stock" : "Stock")),
        h("table.ll-table",
          h("thead", h("tr", h("th", "Level"), h("th", "Player"), h("th", "Rep"), h("th", "Spent"))),
          h("tbody", [...t.levels].sort((a, b) => a.level - b.level).map((l) => h("tr",
            h("td", `LL${l.level}`), h("td", l.requiredPlayerLevel || "–"), h("td", l.requiredReputation ?? "–"),
            h("td", l.requiredCommerce ? fmt.short(l.requiredCommerce) : "–")))))), { cls: "trader" });
    }));
    drawGrid();
    mount(root, grid, offers);
    drawOffers();
    const timer = setInterval(() => {
      for (const el of root.querySelectorAll("[data-reset]")) {
        const left = Number(el.dataset.reset) - Date.now();
        el.textContent = left > 0 ? fmt.countdown(left) : "now";
      }
    }, 1000);
    const off = on((kind, detail) => {
      if (kind === "data" && detail === "traders") dataset("traders").then((d) => { traders = d.filter((t) => t.levels?.length).sort((a, b) => a.name.localeCompare(b.name)); drawGrid(); }).catch(() => {});
    });
    return () => { clearInterval(timer); off(); };
  },
};
