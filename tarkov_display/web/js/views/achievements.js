import { badge, card, empty, errorBox, fmt, h, img, loading, mount, searchInput, segmented, stat, toggle } from "../lib.js";
import { dataset, on, setProgress, store } from "../store.js";

const state = { q: "", rarity: "all", side: "all", hideHidden: false, hideDone: false };

export default {
  title: "Achievements",
  subtitle: "Every achievement, how rare it is, and which ones you have",
  async render(root) {
    mount(root, loading("Loading achievements from tarkov.dev…"));
    let list;
    try { list = await dataset("achievements"); } catch (e) {
      mount(root, errorBox(e.message, () => this.render(root)));
      return;
    }
    list = [...list].sort((a, b) => b.playersCompletedPercent - a.playersCompletedPercent);
    const summary = h("div.stat-grid");
    const grid = h("div.grid.auto");
    const draw = () => {
      const got = new Set(store.progress.achievements || []);
      const byRarity = (r) => list.filter((a) => (a.normalizedRarity || "").toLowerCase() === r);
      mount(summary,
        stat("Unlocked", `${list.filter((a) => got.has(a.id)).length} / ${list.length}`, { kind: "accent" }),
        stat("Common", `${byRarity("common").filter((a) => got.has(a.id)).length} / ${byRarity("common").length}`),
        stat("Rare", `${byRarity("rare").filter((a) => got.has(a.id)).length} / ${byRarity("rare").length}`),
        stat("Legendary", `${byRarity("legendary").filter((a) => got.has(a.id)).length} / ${byRarity("legendary").length}`));
      const rows = list.filter((a) =>
        (state.rarity === "all" || (a.normalizedRarity || "").toLowerCase() === state.rarity) &&
        (state.side === "all" || (a.normalizedSide || "").toLowerCase() === state.side) &&
        (!state.hideHidden || !a.hidden) && (!state.hideDone || !got.has(a.id)) &&
        (!state.q || (a.name + " " + (a.description || "")).toLowerCase().includes(state.q.toLowerCase())));
      mount(grid, rows.length ? rows.map((a) => {
        const have = got.has(a.id);
        const rarity = (a.normalizedRarity || "common").toLowerCase();
        return card(null, h("div.ach" + (have ? ".got" : ""),
          img(a.imageLink, { alt: "" }),
          h("div", { style: { flex: 1, minWidth: 0 } },
            h("div.ach-name", a.name),
            h("div.ach-desc", a.hidden && !have ? "Hidden achievement" : a.description || ""),
            h("div.chips",
              h("span.badge.muted.rarity-" + rarity, a.rarity || "Common"),
              a.side ? badge(a.side, "muted") : null,
              badge(`${fmt.num(a.adjustedPlayersCompletedPercent ?? a.playersCompletedPercent)}% of players`, "muted"))),
          toggle("", have, (v) => setProgress({ op: "achievements", ids: [a.id], done: v }), "I have this")));
      }) : empty("No achievements match."));
    };
    mount(root, summary,
      h("div.toolbar",
        searchInput("Search achievements…", state.q, (v) => { state.q = v; draw(); }),
        segmented([["all", "All"], ["common", "Common"], ["rare", "Rare"], ["legendary", "Legendary"]], state.rarity, (v) => { state.rarity = v; seg(0, v); draw(); }),
        segmented([["all", "Any side"], ["pmc", "PMC"], ["scavs", "Scav"]], state.side, (v) => { state.side = v; seg(1, v); draw(); }),
        toggle("Hide hidden", state.hideHidden, (v) => { state.hideHidden = v; draw(); }),
        toggle("Hide unlocked", state.hideDone, (v) => { state.hideDone = v; draw(); })),
      grid);
    function seg(i, v) {
      const s = root.querySelectorAll(".seg")[i];
      const keys = i === 0 ? ["all", "common", "rare", "legendary"] : ["all", "pmc", "scavs"];
      if (s) [...s.children].forEach((b, j) => b.classList.toggle("on", keys[j] === v));
    }
    draw();
    return on((kind) => { if (kind === "progress") draw(); });
  },
};
