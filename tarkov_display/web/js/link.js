// Game log reader and TarkovTracker: settings cards, event list, notifications.

import { api, badge, button, ext, fmt, h, icon, mount, segmented, toast, toggle } from "./lib.js";
import { emit, store } from "./store.js";

const MODE = { regular: "PvP", pve: "PvE", seasonal: "Seasonal" };

// -- events from the game logs -------------------------------------------------------

export function describeEvent(e) {
  switch (e.kind) {
    case "quest":
      return {
        icon: "quests",
        text: `${e.status === "finished" ? "Finished" : e.status === "failed" ? "Failed" : "Started"} ${e.name || "a quest"}`,
        sub: [e.trader, e.added > 1 ? `+${e.added - 1} earlier quest${e.added > 2 ? "s" : ""} marked done` : null].filter(Boolean).join(" · "),
        kind: e.status === "finished" ? "good" : e.status === "failed" ? "bad" : "",
      };
    case "raid":
      return { icon: "maps", text: `Loading into ${e.name || e.map || "a raid"}`, sub: e.online === false ? "offline raid" : "" };
    case "raid_end":
      return { icon: "exit", text: `Left the raid${e.name ? ` on ${e.name}` : ""}`, sub: "" };
    case "flea":
      return {
        icon: "items", kind: "good",
        text: `Sold ${e.count > 1 ? `${e.count}× ` : ""}${e.name || "an item"} on the flea`,
        sub: [e.buyer ? `to ${e.buyer}` : null, e.roubles ? fmt.rub(e.roubles) : null].filter(Boolean).join(" · "),
      };
    case "mode":
      return { icon: "settings", text: `Tarkov switched to ${MODE[e.gameMode] || e.gameMode}`, sub: "" };
    case "tracker":
      return { icon: "download", kind: "good", text: "Imported from TarkovTracker", sub: importText(e) };
    case "tracker_error":
      return { icon: "alert", kind: "bad", text: "TarkovTracker update failed", sub: e.message };
    default:
      return { icon: "info", text: e.kind, sub: "" };
  }
}

function importText(s) {
  const parts = [];
  parts.push(`${s.tasks} new quest${s.tasks === 1 ? "" : "s"} done`);
  if (s.hideout) parts.push(`${s.hideout} hideout station${s.hideout === 1 ? "" : "s"} raised`);
  if (s.level) parts.push(`level ${s.level}`);
  if (s.faction) parts.push(s.faction);
  return parts.join(" · ");
}

// Called for every "gamelog" event from the app.
export function onGameEvent(e) {
  store.gameEvents = [e, ...(store.gameEvents || [])].slice(0, 40);
  emit("gamelog", e);
  const d = describeEvent(e);
  if (e.kind === "quest" && e.status === "started") return;  // too chatty
  if (e.kind === "raid_end") return;
  if (e.kind === "mode") {
    if ((e.gameMode === "regular" || e.gameMode === "pve") && e.gameMode !== store.state.gameMode) {
      toast(`Tarkov is in ${MODE[e.gameMode]} mode, but the app is showing ${MODE[store.state.gameMode] || "another mode"}.`, {
        kind: "warn", timeout: 12000, actionLabel: `Switch to ${MODE[e.gameMode]}`,
        action: () => api("settings", { method: "POST", body: { gameMode: e.gameMode } }).then(() => location.reload()),
      });
    }
    return;
  }
  if (e.kind === "raid") {
    if (e.autoMap && e.normalizedName) location.hash = `#/maps/${e.normalizedName}`;
    toast(d.text, e.normalizedName && !e.autoMap ? { action: () => { location.hash = `#/maps/${e.normalizedName}`; }, actionLabel: "Map" } : {});
    return;
  }
  toast(d.sub ? `${d.text} (${d.sub})` : d.text, { kind: d.kind || "" });
}

export function eventList(events, { limit = 8 } = {}) {
  return h("div.list", events.slice(0, limit).map((e) => {
    const d = describeEvent(e);
    return h("div.list-row",
      h("span.ev-ic" + (d.kind ? "." + d.kind : ""), icon(d.icon, 16)),
      h("div.grow", h("div", d.text), d.sub ? h("div.muted.small", d.sub) : null),
      h("span.muted.small", (e.time || "").slice(11, 16)));
  }));
}

// -- settings cards ---------------------------------------------------------------------

function row(title, desc, control) {
  return h("div.setting", h("div.setting-text", h("div.setting-title", title), desc ? h("div.setting-desc", desc) : null), control);
}

export function logsCard() {
  const box = h("div");
  let scan = null;
  const draw = async () => {
    let st;
    try { st = await api("gamelog"); } catch (e) { mount(box, h("div.muted", e.message)); return; }
    const pathInput = h("input", { type: "text", placeholder: st.detected || "Folder not found automatically", value: st.path, spellcheck: "false", style: { width: "100%" } });
    const status = !st.enabled
      ? badge("Off", "muted")
      : st.folder ? badge(st.running ? "Reading" : "Found", "good") : badge("Logs folder not found", "bad");
    mount(box,
      row("Read Tarkov's log files", "Marks quests done as you finish them, opens the map when a raid loads, and shows flea sales.",
        toggle("", st.enabled, async (v) => { await api("gamelog", { method: "POST", body: { enabled: v } }); draw(); })),
      st.enabled ? h("div.note" + (st.folder ? "" : ".warn"), { style: { margin: "4px 0 6px" } }, icon(st.folder ? "info" : "alert", 16),
        h("div", status, " ",
          st.folder ? h("span", h("code", st.folder), st.session ? h("div.small.muted", `Session ${st.session}${st.gameMode ? ` · Tarkov in ${MODE[st.gameMode] || st.gameMode} mode` : ""}${st.historyQuests ? ` · ${st.historyQuests} quests picked up from this session` : ""}`) : null)
            : "Set the folder below (it's the Logs folder inside your Escape from Tarkov install).",
          st.error ? h("div.small", st.error) : null)) : null,
      row("Logs folder", "Leave empty to find it automatically (launcher or Steam install).",
        h("div", { style: { display: "flex", gap: "6px", minWidth: "340px" } }, pathInput,
          button("Save", async () => {
            try { await api("gamelog", { method: "POST", body: { path: pathInput.value } }); toast("Logs folder saved.", { kind: "good" }); draw(); }
            catch (e) { toast(e.message, { kind: "bad" }); }
          }, { kind: "small" }))),
      row("Show the map when you load into a raid", "Switches this window to the map you're loading into.",
        toggle("", st.autoMap, (v) => api("gamelog", { method: "POST", body: { autoMap: v } }))),
      row("Quests from old logs", "Tarkov keeps logs of earlier sessions. Finds quests you finished in them (and every quest before those).",
        button("Scan old logs", async () => {
          try { scan = await api("gamelog/scan", { method: "POST", body: {} }); drawScan(); }
          catch (e) { toast(e.message, { kind: "bad" }); }
        }, { iconName: "search" })),
      h("div", { id: "scan-result" }),
      h("div.muted.small", { style: { marginTop: "8px" } },
        "Read-only: the app only opens Tarkov's log files to read them; it never touches the game itself."));
    drawScan();
  };
  const drawScan = () => {
    const el = box.querySelector("#scan-result");
    if (!el || !scan) return;
    const modes = Object.entries(scan.modes || {});
    const totalNew = modes.reduce((s, [, m]) => s + m.new, 0);
    mount(el, h("div.note", { style: { marginTop: "6px" } }, icon("info", 16), h("div",
      h("div", `Read ${scan.sessions} session${scan.sessions === 1 ? "" : "s"}${scan.first ? ` (${scan.first.replace(/^log_/, "").slice(0, 10)} to ${scan.last.replace(/^log_/, "").slice(0, 10)})` : ""}.`),
      modes.length ? modes.map(([m, r]) => h("div.small", `${MODE[m] || m}: ${r.finished} finished quests found, ${r.new} not marked done yet (including earlier quests).`))
        : h("div.small", "No finished quests in these logs."),
      totalNew ? h("div", { style: { marginTop: "8px" } }, button(`Mark ${totalNew} quests done`, async () => {
        const res = await api("gamelog/apply", { method: "POST", body: {} });
        const n = Object.values(res.added).reduce((a, b) => a + b, 0);
        toast(`Marked ${n} quests done.`, { kind: "good" });
        scan = null;
        mount(el);
      }, { kind: "primary small", iconName: "check" })) : null)));
  };
  draw();
  return box;
}

export function trackerCard() {
  const box = h("div");
  const draw = async () => {
    let st;
    try { st = await api("tracker"); } catch (e) { mount(box, h("div.muted", e.message)); return; }
    const site = `https://${st.domain}`;
    const tokenRow = (mode) => {
      const saved = st.tokens[mode];
      const status = st.status?.[mode];
      const last = st.last?.[mode];
      const input = h("input", { type: "password", placeholder: st.domain === "tarkovtracker.org" ? `${mode === "pve" ? "PVE" : "PVP"}_…` : "API token", autocomplete: "off", spellcheck: "false", style: { width: "220px" } });
      return h("div.setting",
        h("div.setting-text",
          h("div.setting-title", `${MODE[mode]} token`),
          h("div.setting-desc", saved ? h("span", "Saved: ", h("code", saved)) : "Not set"),
          status ? h("div.small" + (status.ok ? ".up" : ".down"), status.message) : null,
          last ? h("div.small.muted", `Last import ${fmt.ago(last.time)}: ${importText(last.summary)}`) : null),
        h("div", { style: { display: "flex", flexDirection: "column", gap: "6px", alignItems: "flex-end" } },
          h("div", { style: { display: "flex", gap: "6px" } }, input,
            button("Save", async () => {
              try { await api("tracker", { method: "POST", body: { token: { mode, value: input.value } } }); toast("Token saved.", { kind: "good" }); draw(); }
              catch (e) { toast(e.message, { kind: "bad" }); }
            }, { kind: "small" })),
          saved ? h("div", { style: { display: "flex", gap: "6px" } },
            button("Test", async () => {
              try { await api("tracker/test", { method: "POST", body: { mode } }); } catch (e) { toast(e.message, { kind: "bad" }); }
              draw();
            }, { kind: "ghost small" }),
            button("Import now", async (ev) => {
              ev.target.closest("button").disabled = true;
              try {
                const s = await api("tracker/import", { method: "POST", body: { mode } });
                toast(`Imported from TarkovTracker: ${importText(s)}`, { kind: "good" });
              } catch (e) { toast(e.message, { kind: "bad" }); }
              draw();
            }, { kind: "primary small", iconName: "download" }),
            button("Remove", async () => { await api("tracker", { method: "POST", body: { token: { mode, value: "" } } }); draw(); }, { kind: "ghost small" })) : null));
    };
    mount(box,
      row("Site", "Which TarkovTracker you use. Changing it removes saved tokens.",
        segmented(st.domains.map((d) => [d, d]), st.domain, async (d) => { await api("tracker", { method: "POST", body: { domain: d } }); draw(); })),
      tokenRow("regular"),
      tokenRow("pve"),
      row("Import when the app starts", "Adds new progress from TarkovTracker every time the app opens. Never removes anything.",
        toggle("", st.autoImport, (v) => api("tracker", { method: "POST", body: { autoImport: v } }))),
      row("Send quests finished in game to TarkovTracker", "Uses the game log reader. The token needs permission to write progress.",
        toggle("", st.push, (v) => api("tracker", { method: "POST", body: { push: v } }))),
      h("div.muted.small", { style: { marginTop: "8px" } }, "Create a token on ", ext(site, st.domain),
        " (your account settings → API tokens). Give it permission to read progress, and to write progress if you want quests sent back. The token is stored encrypted for your Windows account."));
  };
  draw();
  return box;
}
