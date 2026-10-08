import { itemChip } from "../components.js";
import { badge, errorBox, fmt, h, img, loading, local, mount, stat, stepper, toggle } from "../lib.js";
import { buyPrice, dataset, on, setProgress, store } from "../store.js";

const state = { allLevels: local.get("hideout.all", false) };

export default {
  title: "Hideout",
  subtitle: "Set the level of each station; see what the next upgrade needs",
  async render(root) {
    mount(root, loading("Loading hideout from tarkov.dev…"));
    let stations;
    try { stations = await dataset("hideout"); } catch (e) {
      mount(root, errorBox(e.message, () => this.render(root)));
      return;
    }
    dataset("cashoffers").catch(() => {});
    const summary = h("div.stat-grid");
    const grid = h("div.grid.auto");
    const draw = () => {
      local.set("hideout.all", state.allLevels);
      const p = store.progress;
      let built = 0, total = 0, remaining = 0, unknown = 0;
      for (const s of stations) {
        const lv = p.hideout[s.id] || 0;
        total += s.levels.length;
        built += Math.min(lv, s.levels.length);
        for (const l of s.levels) {
          if (l.level <= lv) continue;
          for (const r of l.itemRequirements || []) {
            const bp = r.item ? buyPrice(r.item.id) : null;
            if (bp) remaining += bp.price * (r.count || 1); else unknown++;
          }
        }
      }
      mount(summary,
        stat("Levels built", `${built} / ${total}`, { kind: "accent" }),
        stat("Stations maxed", `${stations.filter((s) => (p.hideout[s.id] || 0) >= s.levels.length).length} / ${stations.length}`),
        stat("Cost to finish", fmt.rub(remaining), { sub: unknown ? `${unknown} items without a price` : "buying everything" }));
      const sorted = [...stations].sort((a, b) => a.name.localeCompare(b.name));
      mount(grid, sorted.map((s) => stationCard(s, p.hideout[s.id] || 0)));
    };
    mount(root, summary,
      h("div.toolbar", toggle("Show every remaining level", state.allLevels, (v) => { state.allLevels = v; draw(); }),
        h("span.spacer"), h("span.muted.small", "Item counts are what each upgrade asks for; tick items off on the Needed items page.")),
      grid);
    draw();
    return on((kind, detail) => {
      if (kind === "progress" || kind === "items" || (kind === "data" && detail === "cashoffers")) draw();
      if (kind === "data" && detail === "hideout") dataset("hideout").then((d) => { stations = d; draw(); }).catch(() => {});
    });
  },
};

function stationCard(s, level) {
  const max = s.levels.length;
  const levels = [...s.levels].sort((a, b) => a.level - b.level);
  const upcoming = levels.filter((l) => l.level > level);
  const show = state.allLevels ? upcoming : upcoming.slice(0, 1);
  return h("section.card.station" + (level >= max ? ".maxed" : ""),
    h("div.station-head",
      img(s.imageLink, { size: 42 }),
      h("div", { style: { flex: 1, minWidth: 0 } },
        h("div.station-name", s.name),
        h("div.lvl-dots", levels.map((l) => h("span.lvl-dot" + (l.level <= level ? ".on" : ""), { title: `Level ${l.level}` })))),
      stepper(level, 0, max, (v) => setProgress({ op: "hideout", station: s.id, level: v }))),
    h("div.station-body",
      level >= max ? h("div.muted", "Fully upgraded.") : show.map((l) => levelReqs(l))));
}

function levelReqs(l) {
  const items = l.itemRequirements || [];
  const owned = store.progress.owned || {};
  const others = [
    ...(l.stationLevelRequirements || []).map((r) => badge(`${r.station?.name} ${r.level}`, "muted")),
    ...(l.traderRequirements || []).map((r) => badge(`${r.trader?.name} ${r.requirementType === "level" || !r.requirementType ? "LL" : ""}${r.value}`, "info")),
    ...(l.skillRequirements || []).map((r) => badge(`${r.name} ${r.level}`, "violet")),
  ];
  return h("div",
    h("div.section-title", `Level ${l.level}`, l.constructionTime ? h("span", fmt.duration(l.constructionTime)) : null),
    items.length ? h("div.chips", items.map((r) => {
      const have = owned[r.item?.id] || 0;
      const fir = (r.attributes || []).some((a) => a.type === "foundInRaid" && a.value === "true");
      return itemChip(r.item, r.count, { compact: true, fir, title: `${r.item?.name}: have ${have} / ${r.count}` });
    })) : h("div.muted.small", "No items needed."),
    others.length ? h("div.req-line", { style: { marginTop: "8px" } }, others) : null);
}
