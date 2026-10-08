import { changeTag, itemCell, needBadges, openItem } from "../components.js";
import { badge, fmt, h, loading, local, mount, searchInput, segmented, table, toggle } from "../lib.js";
import { dataset, fleaPrice, neededItems, on, peek, perSlot, searchItems, store } from "../store.js";

const CATEGORIES = [
  ["all", "All"], ["barter", "Barter"], ["keys", "Keys"], ["meds", "Meds"], ["provisions", "Food"],
  ["ammo", "Ammo"], ["gun", "Weapons"], ["mods", "Mods"], ["armor", "Armor"], ["rig", "Rigs"],
  ["backpack", "Backpacks"], ["container", "Containers"], ["wearable", "Gear"], ["grenade", "Grenades"],
];

const state = {
  q: "", cat: local.get("items.cat", "all"), sort: local.get("items.sort", "slot"), dir: "desc",
  hideBanned: local.get("items.hideBanned", false), neededOnly: false,
};

export default {
  title: "Prices",
  subtitle: "Live flea market and trader prices from tarkov.dev",
  render(root, { query }) {
    if (query.q) state.q = query.q;
    const results = h("div");
    const info = h("span.muted.small");
    const draw = () => {
      if (!store.items.length) {
        mount(results, store.itemsError ? h("div.note.warn", "Couldn't download prices: " + store.itemsError) : loading("Loading prices…"));
        return;
      }
      local.set("items.cat", state.cat); local.set("items.sort", state.sort); local.set("items.hideBanned", state.hideBanned);
      let list = state.q ? searchItems(state.q, 1000) : store.items.filter((it) => !it.tags?.includes("preset"));
      if (state.cat !== "all") list = list.filter((it) => it.tags?.includes(state.cat));
      if (state.hideBanned) list = list.filter((it) => !it.banned);
      const needs = needMap();
      if (state.neededOnly) list = list.filter((it) => needs.has(it.id));
      info.textContent = `${fmt.num(list.length)} items · prices ${fmt.ago(store.itemsUpdated)}`;
      mount(results, h("section.card.flush", h("div.card-body", table({
        rows: list,
        sortKey: state.q && state.sort === "relevance" ? null : state.sort,
        sortDir: state.dir,
        onSort: (key, dir) => { state.sort = key; state.dir = dir; draw(); },
        onRow: (it) => openItem(it.id),
        emptyText: state.q ? `No items match “${state.q}”.` : "No items in this category.",
        columns: [
          { key: "name", label: "Item", sort: (it) => it.name.toLowerCase(), render: (it) => itemCell(it) },
          { key: "flea", label: "Flea 24h avg", num: true, sort: (it) => fleaPrice(it) || 0,
            render: (it) => it.banned ? badge("No flea", "muted") : fmt.rub(it.avg) },
          { key: "low", label: "Lowest", num: true, sort: (it) => (it.banned ? 0 : it.low || 0), render: (it) => it.banned ? "–" : fmt.rub(it.low) },
          { key: "change", label: "48h", num: true, sort: (it) => it.change ?? null, render: (it) => changeTag(it.change) },
          { key: "trader", label: "Best trader", num: true, sort: (it) => it.traderPrice || 0,
            render: (it) => it.trader ? h("div", h("div", fmt.rub(it.traderPrice)), h("div.muted.small", it.trader)) : "–" },
          { key: "slot", label: "Per slot", num: true, sort: (it) => perSlot(it),
            render: (it) => h("div", h("div", fmt.rub(perSlot(it))), h("div.muted.small", `${it.slots} slot${it.slots > 1 ? "s" : ""}`)) },
          { key: "best", label: "Sell to", render: (it) => {
            const flea = fleaPrice(it) || 0;
            if (!flea && !it.traderPrice) return "–";
            return flea > (it.traderPrice || 0) ? badge("Flea", "accent") : badge(it.trader, "good");
          } },
          { key: "need", label: "Needed", sort: (it) => { const n = needs.get(it.id); return n ? n.quest + n.hideout : 0; },
            render: (it) => needBadges(needs.get(it.id)) },
        ],
      }))));
    };

    mount(root,
      h("div.toolbar",
        searchInput("Search by name or short name…", state.q, (v) => { state.q = v; draw(); }, { autofocus: true }),
        segmented([["slot", "Per slot"], ["flea", "Flea price"], ["change", "48h change"]],
          ["slot", "flea", "change"].includes(state.sort) ? state.sort : null,
          (v) => { state.sort = v; state.dir = "desc"; draw(); rebuildBar(); }),
        toggle("Hide flea-banned", state.hideBanned, (v) => { state.hideBanned = v; draw(); }),
        toggle("Needed only", state.neededOnly, (v) => { state.neededOnly = v; draw(); }, "Items your open quests or hideout still need"),
        h("span.spacer"), info),
      h("div.filters", CATEGORIES.map(([v, label]) => h("button.fchip" + (state.cat === v ? ".on" : ""), {
        type: "button", onclick: (e) => {
          state.cat = v;
          for (const b of e.target.parentElement.children) b.classList.toggle("on", b === e.target);
          draw();
        },
      }, label))),
      results);

    function rebuildBar() {
      const seg = root.querySelector(".seg");
      if (!seg) return;
      [...seg.children].forEach((b, i) => b.classList.toggle("on", ["slot", "flea", "change"][i] === state.sort));
    }

    ["tasks", "hideout"].forEach((n) => dataset(n).then(draw).catch(() => {}));
    draw();
    return on((kind) => { if (kind === "items" || kind === "progress") draw(); });
  },
};

function needMap() {
  const tasks = peek("tasks"), stations = peek("hideout");
  if (!tasks && !stations) return new Map();
  return new Map(neededItems({ tasks, stations }).items.map((e) => [e.id, e]));
}
