import { itemChip, traderAvatar } from "../components.js";
import { badge, button, empty, errorBox, ext, fmt, h, icon, loading, local, mount, searchInput, segmented, select, stat, toast, toggle } from "../lib.js";
import { failView, neededKeysView, objectiveView, taskMapIds } from "../questinfo.js";
import { dataset, on, prerequisites, questContext, questState, setProgress, store } from "../store.js";

const state = {
  q: "", status: local.get("quests.status", "available"), trader: null, map: "all",
  kappa: local.get("quests.kappa", false), lightkeeper: false, pinned: false, shown: 60,
};
const open = new Set();

export default {
  title: "Quests",
  subtitle: "Track your quests; finishing one also finishes everything before it",
  async render(root, { query }) {
    if (query.q) { state.q = query.q; state.status = "all"; }
    mount(root, loading("Loading quests from tarkov.dev…"));
    let tasks, allMaps;
    try { [tasks, allMaps] = await Promise.all([dataset("tasks"), dataset("maps").catch(() => [])]); } catch (e) {
      mount(root, errorBox(e.message, () => this.render(root, { query })));
      return;
    }
    const traders = [...new Map(tasks.map((t) => [t.trader?.id, t.trader])).values()].filter(Boolean)
      .sort((a, b) => a.name.localeCompare(b.name));
    // Every map a quest or one of its objectives is on.
    const mapNames = new Map(allMaps.map((m) => [m.id, m.name]));
    for (const t of tasks) {
      for (const m of [t.map, ...(t.objectives || []).flatMap((o) => o.maps || [])]) if (m?.id && m.name && !mapNames.has(m.id)) mapNames.set(m.id, m.name);
    }
    const maps = [...new Set(tasks.flatMap(taskMapIds))].filter((id) => mapNames.has(id))
      .map((id) => ({ id, name: mapNames.get(id) })).sort((a, b) => a.name.localeCompare(b.name));
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
        if (state.map !== "all" && !taskMapIds(t).includes(state.map)) return false;
        if (state.kappa && !t.kappaRequired) return false;
        if (state.lightkeeper && !t.lightkeeperRequired) return false;
        if (state.pinned && !(store.progress.pinned || []).includes(t.id)) return false;
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
      toggle("Lightkeeper", state.lightkeeper, (v) => { state.lightkeeper = v; draw(); }),
      toggle("Pinned", state.pinned, (v) => { state.pinned = v; draw(); }, "Only quests pinned for your next raid"),
      h("a.btn.ghost.small", { href: "#/raid" }, icon("raid", 15), h("span", "Raid plan")));
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
  const pinned = (store.progress.pinned || []).includes(t.id);
  const pin = done ? null : h("button.pin-btn" + (pinned ? ".on" : ""), {
    type: "button", title: pinned ? "Unpin from the raid plan" : "Pin for your next raid",
    onclick: (e) => { e.stopPropagation(); setProgress({ op: "pin", ids: [t.id], pinned: !pinned }); },
  }, icon("pin", 16));
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
      pin,
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
  const objectives = (t.objectives || []).map((o) => objectiveView(o, t));
  const reqs = (t.taskRequirements || []).filter((r) => r.task);
  const rw = t.finishRewards || {};
  return h("div.q-cols",
    h("div",
      h("div.section-title", "Objectives"),
      h("ul.obj-list", objectives),
      neededKeysView(t),
      failView(t),
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
