import { api, badge, button, card, ext, fmt, h, icon, loading, mount, segmented, select, toast, toggle } from "../lib.js";
import { logsCard, trackerCard } from "../link.js";
import { on, setProgress, store } from "../store.js";

const NAMES = {
  prices: "Prices (flea + traders)", tasks: "Quests", hideout: "Hideout", barters: "Barters", crafts: "Crafts", ammo: "Ammo",
  maps: "Maps", traders: "Trader resets", cashoffers: "Trader stock", bosses: "Bosses", achievements: "Achievements",
  status: "Server status", goons: "Goon reports", flea: "Flea market rules", mapimages: "Map images (tarkov.dev site)",
  wipes: "Wipe dates (tarkov.dev site)",
};

function setting(title, desc, control) {
  return h("div.setting", h("div.setting-text", h("div.setting-title", title), desc ? h("div.setting-desc", desc) : null), control);
}

export default {
  title: "Settings",
  subtitle: "Game mode, your profile, data, updates and backups",
  render(root) {
    const updateBox = h("div");
    const dataBox = h("div");
    const profileBox = h("div");

    const drawProfile = () => {
      const p = store.progress, s = store.boot.settings;
      mount(profileBox,
        setting("Game mode", "PvP and PvE have separate prices and separate progress.",
          segmented([["regular", "PvP"], ["pve", "PvE"]], store.state.gameMode || s.gameMode, async (v) => {
            try {
              await api("settings", { method: "POST", body: { gameMode: v } });
              toast("Switching game mode…");
              setTimeout(() => location.reload(), 600);
            } catch (e) { toast(e.message, { kind: "bad" }); }
          })),
        setting("Your level", "Used to work out which quests are available.",
          h("input.num-input.small", { type: "number", min: 1, max: 79, value: p.player_level,
            onchange: (e) => setProgress({ op: "profile", player_level: Number(e.target.value) || 1 }) })),
        setting("Faction", "Some quests are USEC or BEAR only.",
          segmented([["USEC", "USEC"], ["BEAR", "BEAR"]], p.faction, (v) => setProgress({ op: "profile", faction: v }))),
        setting("Intelligence Center level", "Level 3 lowers flea market fees.",
          select([0, 1, 2, 3].map((n) => [String(n), n ? `Level ${n}` : "Not built"]), String(p.intel_center),
            (v) => setProgress({ op: "profile", intel_center: Number(v) }))),
        setting("Hideout Management skill", "Adds to the Intelligence Center fee discount.",
          h("input.num-input.small", { type: "number", min: 0, max: 51, value: p.hideout_management,
            onchange: (e) => setProgress({ op: "profile", hideout_management: Number(e.target.value) || 0 }) })),
        setting("Keep running after closing the window",
          "Hotkeys, display changes and price checks keep working. Start the app again to reopen the window.",
          toggle("", s.keepRunning, async (v) => {
            const b = await api("settings", { method: "POST", body: { keepRunning: v } });
            store.boot.settings = b.settings;
          })));
    };

    const drawUpdate = async (force = false) => {
      mount(updateBox, loading("Checking for updates…"));
      let u;
      try { u = await api("update" + (force ? "?force=1" : "")); } catch (e) {
        mount(updateBox, h("div.muted", "Couldn't check: " + e.message));
        return;
      }
      const busy = store.state.updating?.running;
      mount(updateBox,
        h("div.update-box",
          h("div", { style: { flex: 1 } },
            h("div.big-sub", "Installed"), h("div.big-num", `v${u.current}`)),
          h("div", { style: { flex: 1 } },
            h("div.big-sub", "Latest"), h("div.big-num" + (u.available ? ".up" : ""), u.latest ? `v${u.latest}` : "–")),
          h("div", { style: { display: "flex", flexDirection: "column", gap: "8px" } },
            u.available && u.can_update
              ? button(busy ? "Updating…" : `Update to v${u.latest} & restart`, startUpdate, { kind: "primary", iconName: "download", disabled: busy })
              : badge(u.available ? "Update available" : u.latest ? "You're up to date" : "Unknown", u.available ? "warn" : "good"),
            button("Check again", () => drawUpdate(true), { kind: "ghost small", iconName: "refresh" }))),
        u.error ? h("div.note.warn", { style: { marginTop: "12px" } }, icon("alert", 16), h("div", u.error)) : null,
        u.available && !u.can_update ? h("div.note.warn", { style: { marginTop: "12px" } }, icon("alert", 16), h("div", u.reason)) : null,
        h("div", { id: "update-progress" }),
        u.notes?.length ? h("div", { style: { marginTop: "14px" } }, h("div.section-title", "Recent changes"),
          h("ul.notes", u.notes.map((n) => h("li", h("time", fmt.date(n.date)), h("span", n.title))))) : null,
        h("div.muted.small", { style: { marginTop: "12px" } },
          `Checked ${fmt.ago(u.checked)}. Updates download from GitHub and keep your settings and progress.`));
      drawProgress(store.state.updating);
    };

    const drawProgress = (st) => {
      const el = updateBox.querySelector("#update-progress");
      if (!el || !st || (!st.running && !st.error && !st.done)) return;
      mount(el, h("div.note" + (st.error ? ".warn" : ""), { style: { marginTop: "12px" } },
        st.error ? icon("alert", 16) : h("span.spinner"),
        h("div", h("div", st.message), st.error ? h("div.small", st.error) : null)));
    };

    const startUpdate = async () => {
      try {
        await api("update", { method: "POST", body: {} });
        drawProgress({ running: true, message: "Starting update…" });
      } catch (e) { toast(e.message, { kind: "bad" }); }
    };

    const drawData = async () => {
      let st;
      try { st = await api("datastatus"); } catch (e) { mount(dataBox, h("div.muted", e.message)); return; }
      const rows = [{ name: "prices", updated: st.prices.updated, error: st.prices.error, loading: false }, ...st.datasets];
      mount(dataBox,
        h("table.tbl.compact", h("thead", h("tr", h("th", "Data"), h("th", "Updated"), h("th", "Status"), h("th", ""))),
          h("tbody", rows.map((d) => h("tr",
            h("td", NAMES[d.name] || d.name, d.error && !d.loading ? h("div.small.down", { style: { maxWidth: "360px" } }, d.error.slice(0, 220)) : null),
            h("td.muted", d.updated ? fmt.ago(d.updated) : "never"),
            h("td", d.loading ? badge("Updating", "info") : d.error ? badge("Failed", "bad", d.error) : d.updated ? badge("OK", "good") : badge("Not loaded", "muted")),
            h("td.num", button("", async () => {
              await api(`data/${d.name}/refresh`, { method: "POST", body: {} });
              toast(`Refreshing ${NAMES[d.name] || d.name}…`);
              setTimeout(drawData, 1500);
            }, { kind: "ghost small", iconName: "refresh", title: "Refresh now" })))))),
        h("div.toolbar", { style: { marginTop: "10px" } },
          button("Refresh everything", async () => {
            for (const d of rows) api(`data/${d.name}/refresh`, { method: "POST", body: {} }).catch(() => {});
            toast("Refreshing all data from tarkov.dev…");
            setTimeout(drawData, 2500);
          }, { iconName: "refresh" }),
          h("span.muted.small", "Data refreshes on its own: prices every 15 minutes, quests and hideout every 6 hours.")));
    };

    const backup = h("div",
      setting("Back up your progress", "Saves quests, hideout, collected items and achievements to a file.",
        button("Export", () => {
          const blob = new Blob([JSON.stringify(store.progress, null, 1)], { type: "application/json" });
          const a = h("a", { href: URL.createObjectURL(blob), download: `tarkov-progress-${store.state.gameMode}.json` });
          document.body.appendChild(a); a.click(); a.remove();
        }, { iconName: "download" })),
      setting("Restore from a backup", "Replaces your current progress for this game mode.",
        h("label.btn", icon("upload", 16), "Import",
          h("input", { type: "file", accept: ".json,application/json", style: { display: "none" }, onchange: async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            try {
              const data = JSON.parse(await file.text());
              if (!confirm("Replace your current progress with this backup?")) return;
              await setProgress({ op: "import", data });
              toast("Progress restored.", { kind: "good" });
            } catch (err) { toast("Couldn't import: " + err.message, { kind: "bad" }); }
          } }))));

    const reset = (what, label) => button(label, () => {
      if (confirm(`Reset ${label.toLowerCase()}? This can't be undone (export a backup first if unsure).`)) {
        setProgress({ op: "reset", what }).then(() => toast("Reset.", { kind: "good" }));
      }
    }, { kind: "danger small" });

    mount(root,
      h("div.grid.cols-2",
        card("You", profileBox),
        card("Updates", updateBox)),
      h("div.grid.cols-2",
        card("Game log reader", logsCard(), { sub: "off until you turn it on" }),
        card("TarkovTracker", trackerCard(), { sub: "import your progress" })),
      h("div.grid.cols-2",
        card("Data from tarkov.dev", dataBox, { cls: "" }),
        h("div.grid", { style: { alignContent: "start" } },
          card("Backup", backup),
          card("Reset progress", h("div.toolbar",
            reset("tasks", "Quests"), reset("hideout", "Hideout"), reset("owned", "Collected items"),
            reset("achievements", "Achievements"), reset("all", "Everything")), { cls: "danger-zone" }))),
      card("About", h("div",
        h("p", `${store.boot.appName} ${store.boot.version}. Game data, prices and quest information come from `,
          ext("https://tarkov.dev", "tarkov.dev"), ", a free, open-source community project. Map images are made by the artists credited on each map and hosted by tarkov.dev. The flea market fee formula is from tarkov.dev (MIT licence)."),
        h("p.muted.small", "Not affiliated with Battlestate Games. The app never touches the game's memory or changes its files: display changes go through your AMD driver and Windows, price checks read the screen only when you press the hotkey, and the optional log reader only reads Tarkov's log files."),
        h("div.toolbar", button("Quit the app", () => {
          if (confirm("Quit Tarkov Companion? Display settings go back to normal.")) api("quit", { method: "POST", body: {} });
        }, { kind: "ghost", iconName: "power" })))));
    drawProfile();
    drawUpdate();
    drawData();
    return on((kind, detail) => {
      if (kind === "progress") drawProfile();
      if (kind === "update") drawProgress(detail);
      if (kind === "data") drawData();
    });
  },
};
