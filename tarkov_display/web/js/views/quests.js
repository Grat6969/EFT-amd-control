import { itemChip, traderAvatar } from "../components.js";
import { badge, button, empty, errorBox, ext, fmt, h, icon, loading, local, mount, searchInput, segmented, select, stat, toast, toggle } from "../lib.js";
import { dataset, objectiveItems, on, prerequisites, questContext, questState, setProgress, store } from "../store.js";

const state = {
  q: "", status: local.get("quests.status", "available"), trader: null, map: "all",
  kappa: local.get("quests.kappa", false), lightkeeper: false, shown: 60,
};
const open = new Set();

export default {
  title: "Quests",
  subtitle: "Track your quests; finishing one also finishes everything before it",
  async render(root, { query }) {
    if (query.q) { state.q = query.q; state.status = "all"; }
    mount(root, loading("Loading quests from tarkov.dev…"));
    let tasks;
    try { tasks = await dataset("tasks"); } catch (e) {
      mount(root, errorBox(e.message, () => this.render(root, { query })));
      return;
    }
    const traders = [...new Map(tasks.map((t) => [t.trader?.id, t.trader])).values()].filter(Boolean)
      .sort((a, b) => a.name.localeCompare(b.name));
    const maps = [...new Map(tasks.filter((t) => t.map).map((t) => [t.map.id, t.map])).values()].sort((a, b) => a.name.localeCompare(b.name));
    const summary = h("div.q-summary");
    const list = h("div.q-list");
    const profile = h("div.toolbar");

    const draw = () => {
      local.set("quests.status", state.status); local.set("quests.kappa", state.kappa);
      const ctx = questContext(tasks);
      const mine = tasks.filter((t) => questState(t, ctx) !== "other");
      const count = (s) => mine.filter((t) => questState(t, ctx) === s).length;
      const kappa = mine.filter((t) => t.kappaRequired);
      mount(summary,
        stat("Available now", count("available"), { kind: "accent", sub: `at level ${ctx.level}` }),
        stat("Done", `${count("done")} / ${mine.length}`, { sub: fmt.pct(count("done") / Math.max(1, mine.length)) }),
        stat("Kappa", `${kappa.filter((t) => ctx.done.has(t.id)).length} / ${kappa.length}`, { sub: "quests needed for Kappa" }),
        stat("Locked", count("locked"), { sub: "level or earlier quests" }));
      drawProfile();

      let rows = mine.filter((t) => {
        const s = questState(t, ctx);
        if (state.status !== "all" && s !== state.status) return false;
        if (state.trader && t.trader?.id !== state.trader) return false;
        if (state.map !== "all" && t.map?.id !== state.map && !(t.objectives || []).some((o) => (o.maps || []).some((m) => m.id === state.map))) return false;
        if (state.kappa && !t.kappaRequired) return false;
        if (state.lightkeeper && !t.lightkeeperRequired) return false;
        if (state.q) {
          const q = state.q.toLowerCase();
          const hay = [t.name, t.trader?.name, t.map?.name, ...(t.objectives || []).map((o) => o.description)].join(" ").toLowerCase();
          if (!q.split(/\s+/).every((w) => hay.includes(w))) return false;
        }
        return true;
      });
      rows.sort((a, b) => (a.minPlayerLevel || 0) - (b.minPlayerLevel || 0) || a.trader?.name.localeCompare(b.trader?.name) || a.name.localeCompare(b.name));
      const total = rows.length;
      rows = rows.slice(0, state.shown);
      mount(list,
        rows.length ? rows.map((t) => questCard(t, ctx)) : empty("No quests match these filters."),
        total > rows.length ? h("div.tbl-more", button(`Show more (${total - rows.length} left)`, () => { state.shown += 60; draw(); }, { kind: "ghost" })) : null);
    };

    const drawProfile = () => {
      const p = store.progress;
      mount(profile,
        h("label.field", "Your level",
          h("input.num-input.small", { type: "number", min: 1, max: 79, value: p.player_level,
            onchange: (e) => setProgress({ op: "profile", player_level: Number(e.target.value) || 1 }) })),
        segmented([["USEC", "USEC"], ["BEAR", "BEAR"]], p.faction, (v) => setProgress({ op: "profile", faction: v })),
        h("span.spacer"),
        h("span.muted.small", "Progress is saved on this PC, separately for PvP and PvE."));
    };

    const filters = h("div.toolbar",
      searchInput("Search quests, objectives, maps…", state.q, (v) => { state.q = v; state.shown = 60; draw(); }),
      segmented([["available", "Available"], ["locked", "Locked"], ["done", "Done"], ["all", "All"]], state.status,
        (v) => { state.status = v; state.shown = 60; redrawFilters(); draw(); }),
      select([["all", "All maps"], ...maps.map((m) => [m.id, m.name])], state.map, (v) => { state.map = v; draw(); }),
      toggle("Kappa", state.kappa, (v) => { state.kappa = v; draw(); }, "Only quests needed for the Kappa container"),
      toggle("Lightkeeper", state.lightkeeper, (v) => { state.lightkeeper = v; draw(); }));
    const traderChips = h("div.filters");
    const redrawFilters = () => {
      const seg = filters.querySelector(".seg");
      if (seg) [...seg.children].forEach((b, i) => b.classList.toggle("on", ["available", "locked", "done", "all"][i] === state.status));
      mount(traderChips,
        h("button.fchip" + (!state.trader ? ".on" : ""), { type: "button", onclick: () => { state.trader = null; redrawFilters(); draw(); } }, "All traders"),
        traders.map((t) => h("button.fchip" + (state.trader === t.id ? ".on" : ""), {
          type: "button", onclick: () => { state.trader = state.trader === t.id ? null : t.id; redrawFilters(); draw(); },
        }, traderAvatar(t, 20), t.name)));
    };
    redrawFilters();
    mount(root, summary, profile, filters, traderChips, list);
    draw();
    return on((kind, detail) => {
      if (kind === "progress") draw();
      if (kind === "data" && detail === "tasks") dataset("tasks").then((t) => { tasks = t; draw(); }).catch(() => {});
    });
  },
};

function questCard(t, ctx) {
  const s = questState(t, ctx);
  const el = h("article.quest." + s + (open.has(t.id) ? ".open" : ""));
  const toggleOpen = () => {
    if (open.has(t.id)) open.delete(t.id); else open.add(t.id);
    el.classList.toggle("open");
  };
  const done = s === "done";
  const action = done
    ? button("Undo", (e) => { e.stopPropagation(); finish(t, ctx, false); }, { kind: "ghost small", iconName: "x" })
    : button("Done", (e) => { e.stopPropagation(); finish(t, ctx, true); }, { kind: "good small", iconName: "check" });
  el.append(
    h("div.q-row", { onclick: toggleOpen },
      traderAvatar(t.trader, 34),
      h("div.q-main",
        h("div.q-name", t.name,
          t.kappaRequired ? badge("Kappa", "accent") : null,
          t.lightkeeperRequired ? badge("Lightkeeper", "info") : null,
          t.factionName && t.factionName !== "Any" ? badge(t.factionName, "muted") : null),
        h("div.q-meta",
          h("span", t.trader?.name || ""),
          t.minPlayerLevel ? h("span", `Level ${t.minPlayerLevel}+`) : null,
          t.map ? h("span", t.map.name) : null,
          t.experience ? h("span", `${fmt.num(t.experience)} XP`) : null)),
      h("span.state-pill." + s, s === "available" ? "Available" : s === "done" ? "Done" : "Locked"),
      action,
      icon("chevron", 18, "q-chev")),
    h("div.q-body", details(t, ctx)));
  return el;

  function finish(task, c, value) {
    if (!value) {
      setProgress({ op: "tasks", ids: [task.id], done: false });
      return;
    }
    const before = prerequisites(task, c);
    const ids = [task.id, ...before];
    setProgress({ op: "tasks", ids, done: true }).then(() => {
      if (before.length) {
        toast(`Also marked ${before.length} earlier quest${before.length > 1 ? "s" : ""} as done.`, {
          kind: "good", actionLabel: "Undo", action: () => setProgress({ op: "tasks", ids: before, done: false }),
        });
      }
    }).catch((e) => toast(e.message, { kind: "bad" }));
  }
}

function details(t, ctx) {
  const objectives = (t.objectives || []).map((o) => {
    const items = objectiveItems(o);
    const keys = (o.requiredKeys || []).flat().filter(Boolean);
    return h("li.obj" + (o.optional ? ".optional" : ""),
      h("span.obj-dot"),
      h("div",
        h("div.obj-text", o.description, o.optional ? h("span.muted", " (optional)") : null,
          o.foundInRaid ? h("span.fir", "FiR") : null),
        items.length ? h("div.obj-items", items.slice(0, 8).map((it) => itemChip(it, o.count > 1 ? o.count : null, { compact: true }))) : null,
        keys.length ? h("div.obj-items", h("span.muted.small", "Keys:"), keys.map((k) => itemChip(k, null, { compact: true }))) : null));
  });
  const reqs = (t.taskRequirements || []).filter((r) => r.task);
  const rw = t.finishRewards || {};
  return h("div.q-cols",
    h("div",
      h("div.section-title", "Objectives"),
      h("ul.obj-list", objectives),
      reqs.length ? h("div", { style: { marginTop: "14px" } }, h("div.section-title", "Comes after"),
        h("div.tag-list", reqs.map((r) => h("a.tag" + (ctx.done.has(r.task.id) ? ".done" : ""),
          { href: `#/quests?q=${encodeURIComponent(r.task.name)}` },
          ctx.done.has(r.task.id) ? icon("check", 13) : null, r.task.name,
          !(r.status || []).includes("complete") ? h("span.muted", ` (${r.status.join("/")})`) : null)))) : null),
    h("div",
      h("div.section-title", "Rewards"),
      h("div.chips",
        t.experience ? badge(`${fmt.num(t.experience)} XP`, "accent") : null,
        (rw.traderStanding || []).map((s) => badge(`${s.trader?.name} ${s.standing > 0 ? "+" : ""}${s.standing}`, s.standing >= 0 ? "good" : "bad")),
        (rw.skillLevelReward || []).map((s) => badge(`${s.name} +${s.level}`, "info"))),
      (rw.items || []).length ? h("div.obj-items", { style: { marginTop: "8px" } }, rw.items.map((r) => itemChip(r.item, r.count, { compact: true }))) : null,
      (rw.offerUnlock || []).length ? h("div", { style: { marginTop: "10px" } }, h("div.section-title", "Unlocks purchase"),
        h("div.obj-items", rw.offerUnlock.map((u) => itemChip(u.item, null, { compact: true, title: `${u.trader?.name} level ${u.level}` })))) : null,
      (rw.craftUnlock || []).length ? h("div", { style: { marginTop: "10px" } }, h("div.section-title", "Unlocks craft"),
        h("div.obj-items", rw.craftUnlock.flatMap((c) => (c.rewardItems || []).map((r) => itemChip(r.item, r.count, { compact: true, title: `${c.station?.name} ${c.level}` }))))) : null,
      (rw.traderUnlock || []).length ? h("div.chips", { style: { marginTop: "8px" } }, rw.traderUnlock.map((tr) => badge(`Unlocks ${tr.name}`, "good"))) : null,
      t.wikiLink ? h("div", { style: { marginTop: "12px" } }, ext(t.wikiLink, "Open on the wiki")) : null));
}
