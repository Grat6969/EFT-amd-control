import { scatter } from "../charts.js";
import { itemCell, openItem } from "../components.js";
import { card, errorBox, fmt, h, loading, local, mount, searchInput, table, toggle } from "../lib.js";
import { buyPrice, caliberName, dataset, on } from "../store.js";

const COLORS = ["#c9b27c", "#66abd8", "#7dc480", "#e3675e", "#a98bd8", "#e3aa52", "#5fc7b8", "#d87fb4"];
const state = { calibers: local.get("ammo.calibers", null), q: "", tracers: true, sort: "pen", dir: "desc" };

// Rough guide only: penetration compared with 10 x armor class.
function armorTier(pen, cls) {
  const d = pen - cls * 10;
  return d >= 10 ? 3 : d >= 0 ? 2 : d >= -10 ? 1 : 0;
}
const TIER_TEXT = ["Bounces", "Weak", "Good", "Great"];
const TIER_MARK = ["–", "+", "++", "+++"];

export default {
  title: "Ammo",
  subtitle: "Damage and penetration for every round, with a rough armor guide",
  async render(root) {
    mount(root, loading("Loading ammo from tarkov.dev…"));
    let ammo;
    try { ammo = await dataset("ammo"); } catch (e) {
      mount(root, errorBox(e.message, () => this.render(root)));
      return;
    }
    ammo = ammo.filter((a) => a.item && a.caliber && a.damage > 0 && a.ammoType !== "grenade");
    const calibers = [...new Set(ammo.map((a) => a.caliber))]
      .sort((a, b) => ammo.filter((x) => x.caliber === b).length - ammo.filter((x) => x.caliber === a).length);
    if (!state.calibers || !state.calibers.some((c) => calibers.includes(c))) {
      state.calibers = calibers.includes("Caliber545x39") ? ["Caliber545x39"] : calibers.slice(0, 1);
    }
    const chips = h("div.filters.cal-chips");
    const chart = h("div");
    const body = h("div");
    const color = (c) => COLORS[state.calibers.indexOf(c) % COLORS.length];

    const draw = () => {
      local.set("ammo.calibers", state.calibers);
      let rows = ammo.filter((a) => state.calibers.includes(a.caliber));
      if (!state.tracers) rows = rows.filter((a) => !a.tracer);
      if (state.q) rows = rows.filter((a) => (a.item.name + " " + a.item.shortName).toLowerCase().includes(state.q.toLowerCase()));
      mount(chart, scatter(rows.map((a) => ({
        x: a.damage * (a.projectileCount || 1), y: a.penetrationPower, label: a.item.shortName, color: color(a.caliber),
        title: `${a.item.name}\nDamage ${a.damage}${a.projectileCount > 1 ? ` x${a.projectileCount}` : ""} · Penetration ${a.penetrationPower}`,
        id: a.item.id,
      })), {
        xLabel: "DAMAGE", yLabel: "PENETRATION", onClick: (p) => openItem(p.id),
        bands: [1, 2, 3, 4, 5, 6].map((c) => ({ from: c * 10, to: c * 10 + 10, label: `CLASS ${c}`, cls: c % 2 ? "" : "alt" })),
      }));
      mount(body, h("section.card.flush", h("div.card-body", table({
        rows, sortKey: state.sort, sortDir: state.dir, onSort: (k, d) => { state.sort = k; state.dir = d; draw(); },
        onRow: (a) => openItem(a.item.id, a.item), limit: 150,
        columns: [
          { key: "name", label: "Round", sort: (a) => a.item.name, render: (a) => itemCell(a.item, { sub: caliberName(a.caliber) + (a.tracer ? " · tracer" : "") }) },
          { key: "dmg", label: "Damage", num: true, sort: (a) => a.damage * (a.projectileCount || 1),
            render: (a) => a.projectileCount > 1 ? `${a.damage} ×${a.projectileCount}` : a.damage },
          { key: "pen", label: "Pen", num: true, sort: (a) => a.penetrationPower, render: (a) => h("strong", a.penetrationPower) },
          { key: "armor", label: "Armor dmg", num: true, sort: (a) => a.armorDamage, render: (a) => `${a.armorDamage}%` },
          { key: "frag", label: "Frag", num: true, sort: (a) => a.fragmentationChance, render: (a) => fmt.pct(a.fragmentationChance) },
          { key: "speed", label: "Speed", num: true, sort: (a) => a.initialSpeed, render: (a) => a.initialSpeed ? `${Math.round(a.initialSpeed)} m/s` : "–" },
          ...[1, 2, 3, 4, 5, 6].map((c) => ({
            key: "c" + c, label: `C${c}`, num: true, sort: (a) => a.penetrationPower,
            render: (a) => { const t = armorTier(a.penetrationPower, c); return h("span.armor-cell.ac-" + t, { title: `Class ${c}: ${TIER_TEXT[t]}` }, TIER_MARK[t]); },
          })),
          { key: "price", label: "Price", num: true, sort: (a) => buyPrice(a.item.id)?.price ?? null,
            render: (a) => { const bp = buyPrice(a.item.id); return bp ? h("div", fmt.rub(bp.price), h("div.muted.small", bp.source)) : "–"; } },
        ],
      }))));
    };
    const drawChips = () => mount(chips, calibers.map((c) => h("button.fchip" + (state.calibers.includes(c) ? ".on" : ""), {
      type: "button",
      onclick: (e) => {
        if (e.ctrlKey || e.shiftKey) {
          state.calibers = state.calibers.includes(c) ? state.calibers.filter((x) => x !== c) : [...state.calibers, c];
          if (!state.calibers.length) state.calibers = [c];
        } else state.calibers = [c];
        drawChips(); draw();
      },
    }, state.calibers.includes(c) ? h("span", { style: { width: "8px", height: "8px", borderRadius: "50%", background: color(c), display: "inline-block" } }) : null,
    caliberName(c))));
    drawChips();
    mount(root,
      h("div.toolbar",
        searchInput("Filter rounds…", state.q, (v) => { state.q = v; draw(); }),
        toggle("Show tracers", state.tracers, (v) => { state.tracers = v; draw(); }),
        h("span.spacer"), h("span.muted.small", "Click a caliber; Ctrl+click to compare several.")),
      chips,
      card("Damage vs penetration", chart, { sub: "click a dot for prices" }),
      h("div.note", "C1–C6 columns are a rough guide from penetration alone (about 10 penetration per armor class). Real results also depend on armor material and durability."),
      body);
    draw();
    return on((kind, detail) => { if (kind === "items" || (kind === "data" && detail === "cashoffers")) draw(); });
  },
};
