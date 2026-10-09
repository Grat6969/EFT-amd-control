import { traderAvatar } from "../components.js";
import { badge, button, card, empty, errorBox, h, icon, loading, local, mount, stat, toast } from "../lib.js";
import { isInRaid, kitList, objectiveDone, objectiveView, onMap, raidKit } from "../questinfo.js";
import { dataset, on, prerequisites, questContext, questState, setProgress, store } from "../store.js";

const ALL = "all";

export default {
  title: "Raid plan",
  subtitle: "Your quests for this raid: what to bring, where to go, how",
  async render(root, { rest }) {
    mount(root, loading("Loading quests and maps…"));
    let tasks, maps;
    try {
      [tasks, maps] = await Promise.all([dataset("tasks"), dataset("maps").catch(() => [])]);
    } catch (e) {
      mount(root, errorBox(e.message, () => this.render(root, { rest })));
      return;
    }
    maps = maps.filter((m) => m.normalizedName).sort((a, b) => a.name.localeCompare(b.name));
    const byNorm = new Map(maps.map((m) => [m.normalizedName, m]));
    let mapNorm = rest[0] && byNorm.has(rest[0]) ? rest[0] : local.get("raid.map", ALL);
    if (mapNorm !== ALL && !byNorm.has(mapNorm)) mapNorm = ALL;

    const head = h("div");
    const body = h("div.stack");

    const draw = () => {
      local.set("raid.map", mapNorm);
      const map = byNorm.get(mapNorm) || null;
      const mapId = map?.id || null;
      const ctx = questContext(tasks);
      const pinnedIds = new Set(store.progress.pinned || []);
      const pinned = tasks.filter((t) => pinnedIds.has(t.id) && !ctx.done.has(t.id));
      // On a map: quests with an objective there (or on any map), and quests with nothing to do in raid.
      const relevant = (t, id) => !id || (t.objectives || []).some((o) => isInRaid(o) && onMap(o, id)) || !(t.objectives || []).some(isInRaid);
      const here = pinned.filter((t) => relevant(t, mapId));
      const counts = new Map(maps.map((m) => [m.id, pinned.filter((t) => relevant(t, m.id)).length]));

      mount(head,
        h("div.toolbar.raid-maps",
          h("span.muted.small", "Going to"),
          h("button.fchip" + (mapNorm === ALL ? ".on" : ""), { type: "button", onclick: () => { mapNorm = ALL; draw(); } },
            "All maps", pinned.length ? h("span.fchip-count", String(pinned.length)) : null),
          maps.map((m) => h("button.fchip" + (mapNorm === m.normalizedName ? ".on" : ""), {
            type: "button", onclick: () => { mapNorm = m.normalizedName; draw(); },
          }, m.name, counts.get(m.id) ? h("span.fchip-count", String(counts.get(m.id))) : null))));

      const left = here.flatMap((t) => (t.objectives || []).filter((o) => !o.optional && isInRaid(o) && onMap(o, mapId) && !objectiveDone(o)));
      const kit = raidKit(here, mapId);
      const keys = kit.bring.filter((e) => e.kind === "Key").length;
      const others = suggestions(tasks, ctx, pinnedIds, mapId);

      mount(body,
        h("div.stat-grid",
          stat("Pinned quests", map ? `${here.length} here` : String(pinned.length), { kind: "accent", sub: map ? `${pinned.length} pinned in all` : "for your next raid" }),
          stat("Objectives left", String(left.length), { sub: map ? `to do in raid on ${map.name}` : "to do in raid, all maps" }),
          stat("Keys to bring", String(keys), { sub: keys ? "see Take with you" : "none needed" }),
          stat("More quests here", String(others.length), { sub: map ? `available on ${map.name}` : "pick a map" })),
        pinned.length ? null : h("div.note", icon("info", 16),
          h("div", "Nothing pinned yet. Pin quests with ", icon("pin", 13), " on the ", h("a", { href: "#/quests" }, "Quests"),
            " page, or below once you pick a map. Finished quests drop off on their own.")),
        here.length ? h("div.grid.cols-2",
          card("Take with you", kitList(kit.bring, "Nothing special: no keys, markers or items to place."), { sub: "keys, markers, items to place or use" }),
          card("Look for in raid", kitList(kit.find, "Nothing to find for these quests."), { sub: "quest items and found-in-raid items" })) : null,
        here.length ? h("div.raid-quests", here.map((t) => questCard(t, mapId, ctx, tasks))) : null,
        map || others.length ? card(map ? `Also on ${map.name}` : "Other quests", suggestionList(others, map), { sub: "available now, not pinned", cls: "flush" }) : null);
    };

    mount(root, head, body);
    draw();
    return on((kind, detail) => {
      if (kind === "progress") draw();
      if (kind === "data" && (detail === "tasks" || detail === "maps")) {
        Promise.all([dataset("tasks"), dataset("maps").catch(() => maps)]).then(([t, m]) => {
          tasks = t;
          maps = m.filter((x) => x.normalizedName).sort((a, b) => a.name.localeCompare(b.name));
          draw();
        }).catch(() => {});
      }
    });
  },
};

function questCard(t, mapId, ctx, tasks) {
  const objectives = t.objectives || [];
  const now = objectives.filter((o) => isInRaid(o) && onMap(o, mapId));
  const later = objectives.filter((o) => !now.includes(o));
  const doneCount = objectives.filter((o) => !o.optional && objectiveDone(o)).length;
  const required = objectives.filter((o) => !o.optional).length;
  const finish = () => {
    const before = prerequisites(t, ctx);
    const ids = [t.id, ...before];
    // Finishing unpins the quest, so Undo pins it again.
    const undo = () => setProgress({ op: "tasks", ids, done: false })
      .then(() => setProgress({ op: "pin", ids: [t.id], pinned: true }))
      .catch((e) => toast(e.message, { kind: "bad" }));
    setProgress({ op: "tasks", ids, done: true })
      .then(() => toast(`${t.name} done${before.length ? ` (and ${before.length} earlier quest${before.length > 1 ? "s" : ""})` : ""}.`,
        { kind: "good", actionLabel: "Undo", action: undo, timeout: 8000 }))
      .catch((e) => toast(e.message, { kind: "bad" }));
  };
  const locked = questState(t, ctx) === "locked";
  return h("section.card.raid-quest",
    h("header.card-head",
      traderAvatar(t.trader, 30),
      h("div.grow",
        h("h3", t.name, t.kappaRequired ? badge("Kappa", "accent") : null, locked ? badge("Locked", "muted", "Earlier quests or level needed") : null),
        h("div.muted.small", [t.trader?.name, t.map?.name, `${doneCount}/${required} objectives ticked`].filter(Boolean).join(" · "))),
      h("div.card-actions",
        button("Done", finish, { kind: "good small", iconName: "check", title: "Quest finished (also finishes the quests before it)" }),
        button("", () => setProgress({ op: "pin", ids: [t.id], pinned: false }), { kind: "ghost small", iconName: "x", title: "Unpin" }))),
    h("div.card-body",
      now.length ? h("ul.obj-list", now.map((o) => objectiveView(o, t, { track: true })))
        : h("div.muted.small", "Nothing to do in raid on this map for this quest."),
      later.length ? h("details.obj-later", h("summary", `${later.length} more objective${later.length > 1 ? "s" : ""} (other maps or outside the raid)`),
        h("ul.obj-list", later.map((o) => objectiveView(o, t, { track: true })))) : null,
      t.wikiLink ? h("div.small", { style: { marginTop: "10px" } }, h("a.ext", { href: t.wikiLink, target: "_blank", rel: "noopener noreferrer" }, "Wiki page", icon("external", 13))) : null));
}

// Available quests (not pinned) with something to do in raid on this map.
function suggestions(tasks, ctx, pinnedIds, mapId) {
  if (!mapId) return [];
  return tasks.filter((t) => !pinnedIds.has(t.id) && questState(t, ctx) === "available"
    && (t.objectives || []).some((o) => isInRaid(o) && onMap(o, mapId) && (o.maps?.length || o.zones?.length || o.possibleLocations?.length || t.map?.id === mapId)))
    .sort((a, b) => (b.kappaRequired - a.kappaRequired) || (a.minPlayerLevel || 0) - (b.minPlayerLevel || 0) || a.name.localeCompare(b.name));
}

function suggestionList(list, map) {
  if (!map) return h("div.card-body", h("div.muted.small", "Pick the map you're going to and quests you can do there show up here."));
  if (!list.length) return h("div.card-body", empty(`No other available quests on ${map.name}.`));
  return h("div.list", list.slice(0, 40).map((t) => h("div.list-row",
    traderAvatar(t.trader, 26),
    h("div.grow", h("div.sugg-name", t.name, t.kappaRequired ? badge("Kappa", "accent") : null),
      h("div.muted.small", (t.objectives || []).filter((o) => isInRaid(o) && onMap(o, map.id)).map((o) => o.description).slice(0, 2).join(" · "))),
    button("Pin", () => setProgress({ op: "pin", ids: [t.id], pinned: true }), { kind: "small", iconName: "pin" }))));
}
