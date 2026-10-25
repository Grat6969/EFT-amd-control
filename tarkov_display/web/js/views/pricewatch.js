import { itemCell, needBadges, openItem } from "../components.js";
import { badge, button, card, empty, fmt, h, icon, loading, mount, select, table, toast, toggle } from "../lib.js";
import { dataset, fleaFee, loadPricewatch, neededItems, on, peek, pricewatchChange, pricewatchCheck, store } from "../store.js";

const THRESHOLDS = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8];
const MIN_PRICES = [0, 5000, 10000, 25000, 50000, 100000];
const NEW_FOR = 30 * 60; // seconds an item counts as new on a list

const sorting = { cheap: ["pct", "desc"], high: ["pct", "desc"] };

export default {
  title: "Price watch",
  subtitle: "Items far below or above their 7-day average price",
  render(root) {
    let poll = null;
    const draw = () => {
      const w = store.pricewatch;
      if (!w) { mount(root, loading("Loading the price watch…")); return; }
      // The result comes as an event; ask as well in case the event is missed.
      if (w.running && !poll) poll = setTimeout(() => { poll = null; loadPricewatch().catch(() => {}); }, 4000);
      const s = w.settings;
      const pct = fmt.pct(s.threshold);
      const needs = needMap();
      mount(root,
        h("div.toolbar",
          h("label.field", "At least",
            select(options(THRESHOLDS, s.threshold, (t) => fmt.pct(t)), String(s.threshold),
              (v) => change({ threshold: Number(v) }), { title: "How far from its 7-day average an item's lowest offer must be" }),
            "from the 7-day average"),
          h("label.field", "Worth at least",
            select(options(MIN_PRICES, s.minPrice, (v) => (v ? fmt.rub(v) : "any price")), String(s.minPrice),
              (v) => change({ minPrice: Number(v) }), { title: "Leave out items whose weekly average is below this" })),
          toggle("Watch in the background", s.enabled, (v) => change({ enabled: v }),
            "Check after every price update (every 15 minutes, and when a raid ends) and pop up a note in this window when an item joins a list"),
          h("span.spacer"),
          h("span.muted.small", { title: "Items whose 7-day average is known, compared with their lowest offer at every price update" }, summary(w)),
          button(w.running ? "Checking…" : "Check now", check, { iconName: "refresh", disabled: w.running,
            title: "Look up more price histories now" })),
        w.error ? h("div.note.warn", icon("alert", 16), h("div", w.error, " The app tries again at the next price update.")) : null,
        !store.items.length && !w.checked ? h("div.note.warn", icon("alert", 16), h("div", "Prices haven't been downloaded yet.")) : null,
        card("Cheap now", list(w, "cheap", needs, pct, draw), {
          cls: "flush", sub: `Lowest offer ${pct} or more below its 7-day average: worth buying` }),
        card("Selling high", list(w, "high", needs, pct, draw), {
          cls: "flush", sub: `Lowest offer and 24h average ${pct} or more above their 7-day averages: worth selling` }),
        h("div.note", icon("info", 16), h("div",
          "After every price update (every 15 minutes, and when a raid ends with the game log reader on), RaidReady ",
          "looks for items whose price moved a lot and compares each one's lowest flea offer with the average lowest offer ",
          "over the last 7 days, from tarkov.dev's price history. Items that usually have fewer than 3 offers are left out: ",
          "their price is often just one odd listing. Click an item for its price chart. Cheap offers sell fast: one may be ",
          "gone by the time you reach the flea market.")));
    };

    async function change(body) {
      try { await pricewatchChange(body); } catch (e) { toast("Couldn't change the price watch: " + e.message, { kind: "bad" }); }
    }
    async function check() {
      try { await pricewatchCheck(); } catch (e) { toast(e.message, { kind: "warn" }); }
    }

    ["tasks", "hideout"].forEach((n) => dataset(n).then(draw).catch(() => {}));
    loadPricewatch().catch((e) => toast("Couldn't load the price watch: " + e.message, { kind: "bad" }));
    draw();
    const timer = setInterval(draw, 60000); // "New" badges and "x min ago"
    const off = on((kind) => { if (kind === "pricewatch" || kind === "progress" || kind === "items") draw(); });
    return () => { clearInterval(timer); clearTimeout(poll); off(); };
  },
};

function options(values, current, label) {
  const all = values.includes(current) ? values : [...values, current].sort((a, b) => a - b);
  return all.map((v) => [String(v), label(v)]);
}

function summary(w) {
  if (w.running && !w.checked) return "Looking up price histories…";
  const parts = [];
  if (w.checked) parts.push(`${fmt.num(w.compared)} items checked`);
  if (w.waiting) parts.push(`${fmt.num(w.waiting)} more to look up`);
  parts.push(`prices ${fmt.ago(w.pricesUpdated)}`);
  return parts.join(" · ");
}

function list(w, kind, needs, pct, redraw) {
  const rows = w[kind] || [];
  if (!rows.length) {
    if (w.running && !w.checked) return loading("Looking up price histories…");
    const what = kind === "cheap" ? "below" : "above";
    return empty(`Nothing is ${pct} or more ${what} its weekly average right now.`,
      w.waiting ? `Still looking up ${fmt.num(w.waiting)} items whose price moved: this fills in over the next few price updates.`
        : "Prices move all the time: the app looks again after every price update.");
  }
  const now = Date.now() / 1000;
  const [sortKey, sortDir] = sorting[kind];
  const columns = [
    { key: "name", label: "Item", sort: (e) => e.name.toLowerCase(),
      render: (e) => itemCell(e, { sub: h("span", e.short, now - e.since < NEW_FOR ? badge("New", "accent", "Joined this list in the last half hour") : null) }) },
    { key: "low", label: "Lowest offer", num: true, sort: (e) => e.low,
      render: (e) => h("div", h("div", fmt.rub(e.low)),
        e.offers ? h("div.muted.small", { title: "How many offers it usually has on the flea" }, `~${fmt.num(e.offers)} offers`) : null) },
    { key: "avg7", label: "7-day avg", num: true, sort: (e) => e.avg7,
      render: (e) => h("div", { title: `The lowest offer's average over the last ${e.days} days (${fmt.num(e.points)} prices). `
          + `Average offer: ${fmt.rub(e.avg7All)} over 7 days, ${fmt.rub(e.avg24)} over 24 hours.` },
        h("div", fmt.rub(e.avg7)), h("div.muted.small", `24h avg ${fmt.rub(e.avg24)}`)) },
    { key: "pct", label: kind === "cheap" ? "Below avg" : "Above avg", num: true, sort: (e) => Math.abs(e.diff),
      render: (e) => badge(`${e.diff > 0 ? "+" : "−"}${fmt.pct(Math.abs(e.diff))}`, "good", kind === "high"
        ? `Lowest offer ${fmt.signedPct(e.lowDiff * 100)}, 24h average ${fmt.signedPct((e.avgDiff ?? 0) * 100)} over their 7-day averages (the smaller is shown)`
        : undefined) },
  ];
  if (kind === "cheap") {
    columns.push(
      { key: "save", label: "You save", num: true, sort: (e) => e.avg7 - e.low,
        render: (e) => h("div", { title: "Compared with paying the 7-day average" }, fmt.rub(e.avg7 - e.low)) },
      { key: "trader", label: "Best trader", num: true, sort: (e) => e.traderPrice || 0, render: (e) => {
        if (!e.trader) return "–";
        const more = e.traderPrice > e.low;
        return h("div", h("div" + (more ? ".up" : ""), fmt.rub(e.traderPrice)),
          more ? badge(`${e.trader} pays more`, "accent", "This trader buys it for more than the lowest offer")
            : h("div.muted.small", e.trader));
      } });
  } else {
    columns.push(
      { key: "net", label: "After flea fee", num: true, sort: (e) => e.low - fleaFee(e.base, e.low), render: (e) => {
        const net = e.low - fleaFee(e.base, e.low);
        return h("div", { title: "Listed at the lowest offer, after the flea market fee" }, h("div", fmt.rub(net)),
          h("div.muted.small", `${fmt.signedRub(net - e.avg7)} vs avg`));
      } });
  }
  columns.push({ key: "need", label: "Needed", sort: (e) => { const n = needs.get(e.id); return n ? n.quest + n.hideout : 0; },
    render: (e) => needBadges(needs.get(e.id)) });
  return table({
    rows, columns, sortKey, sortDir, limit: 50,
    onSort: (key, dir) => { sorting[kind] = [key, dir]; redraw(); },
    onRow: (e) => openItem(e.id),
  });
}

function needMap() {
  const tasks = peek("tasks"), stations = peek("hideout");
  if (!tasks && !stations) return new Map();
  return new Map(neededItems({ tasks, stations }).items.map((e) => [e.id, e]));
}
