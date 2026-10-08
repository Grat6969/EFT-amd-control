import { itemChip } from "../components.js";
import { badge, card, empty, errorBox, fmt, h, img, loading, mount, progressBar, searchInput } from "../lib.js";
import { dataset } from "../store.js";

const PARTS = { head: "Head", chest: "Thorax", thorax: "Thorax", stomach: "Stomach", leftArm: "Left arm", rightArm: "Right arm", leftLeg: "Left leg", rightLeg: "Right leg" };
const state = { q: "" };

export default {
  title: "Bosses",
  subtitle: "Where bosses spawn, how often, and how tough they are",
  async render(root) {
    mount(root, loading("Loading bosses from tarkov.dev…"));
    let bosses, maps;
    try {
      [bosses, maps] = await Promise.all([dataset("bosses"), dataset("maps").catch(() => [])]);
    } catch (e) {
      mount(root, errorBox(e.message, () => this.render(root)));
      return;
    }
    const where = new Map();
    for (const m of maps) {
      for (const b of m.bosses || []) {
        if (!b.boss) continue;
        const list = where.get(b.boss.id) || [];
        if (!list.some((x) => x.map.id === m.id)) list.push({ map: m, chance: b.spawnChance, escorts: b.escorts });
        where.set(b.boss.id, list);
      }
    }
    // Real bosses first: anything that spawns somewhere, by highest chance.
    const sorted = [...bosses].sort((a, b) => (where.has(b.id) - where.has(a.id)) || a.name.localeCompare(b.name));
    const grid = h("div.grid.cols-2");
    const draw = () => {
      const list = sorted.filter((b) => !state.q || b.name.toLowerCase().includes(state.q.toLowerCase()));
      mount(grid, list.length ? list.map((b) => bossCard(b, where.get(b.id) || [])) : empty("No bosses match."));
    };
    mount(root, h("div.toolbar", searchInput("Find a boss…", state.q, (v) => { state.q = v; draw(); })), grid);
    draw();
  },
};

function bossCard(b, spawns) {
  const health = b.health || [];
  const total = health.reduce((s, p) => s + p.max, 0);
  const maxPart = Math.max(1, ...health.map((p) => p.max));
  const gear = (b.equipment || []).filter((e) => e.item).slice(0, 14);
  return card(null, h("div",
    h("div.boss-big",
      h("div.portrait", img(b.imagePortraitLink, { alt: b.name })),
      h("div", { style: { flex: 1, minWidth: 0 } },
        h("div.trader-name", b.name),
        total ? h("div.muted.small", `${fmt.num(total)} HP total`) : null,
        h("div.chips", { style: { marginTop: "8px" } },
          spawns.length ? spawns.sort((x, y) => y.chance - x.chance).map((s) =>
            h("a.badge.accent", { href: `#/maps/${s.map.normalizedName}` }, `${s.map.name} ${fmt.pct(s.chance)}`)) : badge("No fixed spawn", "muted")))),
    health.length ? h("div.hp-bars", health.map((p) => [
      h("span", PARTS[p.bodyPart] || p.bodyPart), progressBar(p.max, maxPart), h("span", p.max)])) : null,
    gear.length ? h("div", { style: { marginTop: "12px" } },
      h("div.section-title", "Likely gear", h("span.small", "estimates")),
      h("div.chips", gear.map((e) => itemChip(e.item, e.count > 1 ? e.count : null, { compact: true })))) : null));
}
