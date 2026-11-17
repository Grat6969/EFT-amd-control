// Ask Claude: export everything RaidReady knows to one file you drop into a
// Claude chat, which then suggests your next raid. No API key or credits.

import { api, badge, button, card, debounce, empty, ext, fmt, h, icon, loading, mount, segmented, stat, toast, toggle } from "../lib.js";
import { on, setProgress, store } from "../store.js";

const KITS = [["budget", "Budget"], ["mid", "Mid"], ["geared", "Geared"], ["meta", "Meta"]];
const KIT_HINTS = {
  "": "Pick what you usually take into raid.",
  budget: "Cheap gear you don't mind losing.",
  mid: "Class 3-4 armor, decent ammo.",
  geared: "Class 4-5 armor, good ammo, losses are OK.",
  meta: "Best gear and ammo; money isn't a problem.",
};
const GOALS = ["Kappa", "Lightkeeper", "Level up fast", "Make money", "Hideout upgrades", "Unlock traders", "Just have fun"];

function setting(title, desc, control) {
  return h("div.setting", h("div.setting-text", h("div.setting-title", title), desc ? h("div.setting-desc", desc) : null), control);
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Older WebView or no permission: the old way.
    const area = h("textarea", { style: { position: "fixed", opacity: "0" } }, text);
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

export default {
  title: "Ask Claude",
  subtitle: "Export your progress to a file, drop it into a Claude chat, and get a plan for your next raid",
  async render(root) {
    mount(root, loading("Working out your open quests…"));
    let state;
    try {
      state = await api("advisor");
    } catch (e) {
      mount(root, empty("Couldn't load your quests", e.message));
      return;
    }
    let onlyMissing = false;
    let last = null;  // the last export
    const summary = h("div.stat-grid");
    const kitBox = h("div");
    const keysBox = h("div");
    const exportBox = h("div");

    const saveSettings = (settings) => setProgress({ op: "advisor", settings }).catch((e) => toast(e.message, { kind: "bad" }));
    const saveText = debounce((settings) => saveSettings(settings), 600);

    const drawSummary = () => {
      const owned = store.progress.owned || {};
      const have = state.keys.filter((k) => owned[k.id]).length;
      const top = state.maps.find((m) => !["Ready to turn in", "Any map"].includes(m.name) && !m.name.startsWith("No raid"));
      const ready = state.maps.find((m) => m.name === "Ready to turn in");
      mount(summary,
        stat("Open quests", fmt.num(state.available), { kind: "accent", sub: `at level ${store.progress.player_level}` }),
        stat("Most quests on", top ? top.name : "–", { sub: top ? `${top.count} open quest${top.count === 1 ? "" : "s"}` : "no map quests" }),
        stat("Keys they use", state.keys.length ? `${have} / ${state.keys.length}` : "none", { sub: "ticked off below" }),
        stat("Ready to turn in", fmt.num(ready ? ready.count : 0), { sub: "all objectives ticked off" }));
    };

    const drawKit = () => {
      const s = store.progress.advisor || {};
      const goal = h("input", { type: "text", value: s.goal || "", placeholder: "e.g. Kappa, make money, level up", list: "adv-goals",
        maxlength: 200, style: { width: "280px" }, oninput: (e) => saveText({ goal: e.target.value }) });
      mount(kitBox,
        setting("What you usually take in", KIT_HINTS[s.kit || ""],
          segmented(KITS, s.kit || "", (v) => saveSettings({ kit: v }).then(drawKit))),
        setting("Roubles", "Roughly how much you have. Helps Claude keep gear advice in budget.",
          h("input.num-input", { type: "number", min: 0, step: 100000, value: s.roubles || "", placeholder: "0",
            onchange: (e) => saveSettings({ roubles: Math.max(0, Number(e.target.value) || 0) }) })),
        setting("Goal", "What you're working towards right now.",
          h("div", goal, h("datalist", { id: "adv-goals" }, GOALS.map((g) => h("option", { value: g }))))),
        setting("Anything else", "Playing with a friend, maps you hate, gear you have lots of…",
          h("textarea.adv-notes", { maxlength: 1000, rows: 2, placeholder: "Optional",
            oninput: (e) => saveText({ notes: e.target.value }) }, s.notes || "")));
    };

    const drawKeys = () => {
      const owned = store.progress.owned || {};
      if (!state.tasksLoaded) {
        mount(keysBox, empty("Quest data hasn't downloaded yet", "It comes from tarkov.dev and retries on its own."));
        return;
      }
      if (!state.keys.length) {
        mount(keysBox, empty("None of your open quests need a key"));
        return;
      }
      const keys = onlyMissing ? state.keys.filter((k) => !owned[k.id]) : state.keys;
      mount(keysBox,
        h("div.toolbar", toggle("Only ones I don't have", onlyMissing, (v) => { onlyMissing = v; drawKeys(); })),
        keys.length ? h("div.list", keys.map((k) => {
          const have = !!owned[k.id];
          return h("label.list-row.adv-key" + (have ? ".have" : ""),
            h("input", { type: "checkbox", checked: have,
              onchange: (e) => setProgress({ op: "owned", item: k.id, count: e.target.checked ? 1 : 0 }) }),
            k.icon ? h("img.adv-key-ic", { src: k.icon, alt: "", loading: "lazy", referrerpolicy: "no-referrer" }) : icon("key", 18),
            h("div.grow", h("div", k.name),
              h("div.muted.small", [k.maps.join(", "), `for ${k.quests.slice(0, 3).join(", ")}${k.quests.length > 3 ? ` +${k.quests.length - 3}` : ""}`].filter(Boolean).join(" · "))),
            have ? badge("Have it", "good") : badge("Don't have", "muted"));
        })) : h("div.muted", "You have every key on the list."));
    };

    const run = async (copy) => {
      try {
        last = await api("advisor/export", { method: "POST" });
      } catch (e) {
        toast("Export failed: " + e.message, { kind: "bad" });
        return;
      }
      if (copy) {
        const ok = await copyText(last.text);
        toast(ok ? "Copied. Paste it into a Claude chat." : "Couldn't copy; the file is saved though.", { kind: ok ? "good" : "warn" });
      } else {
        toast(`Saved ${last.name}`, { kind: "good", action: openFolder, actionLabel: "Show" });
      }
      drawExport();
    };
    const openFolder = () => api("advisor/open", { method: "POST" }).catch((e) => toast(e.message, { kind: "bad" }));

    const drawExport = () => {
      mount(exportBox,
        h("ol.adv-steps",
          h("li", "Save the export (or copy it)."),
          h("li", "Open ", ext("https://claude.ai/new", "a new Claude chat"), " and drag the file in, or paste."),
          h("li", "Optional: add one or two screenshots of your stash so Claude can see your gear."),
          h("li", "Send. Claude checks Reddit and the wiki and tells you which map to run and what to bring.")),
        h("div.toolbar",
          button("Save export file", () => run(false), { kind: "primary", iconName: "download" }),
          button("Copy to clipboard", () => run(true), { iconName: "check" }),
          button("Open folder", openFolder, { kind: "ghost", iconName: "external", title: state.folder })),
        last ? h("div.adv-last",
          h("div", icon("check", 14), " ", h("strong", last.name), h("span.muted", ` · ${fmt.num(Math.round(last.bytes / 1024) || 1)} KB · ${last.folder}`)),
          h("details.adv-preview", h("summary", "Preview"), h("pre", last.text))) : null,
        state.logs ? null : h("div.muted.small", { style: { marginTop: "10px" } },
          "Tarkov's log folder wasn't found, so the export won't include your recent raids. Set it in Settings → Game log reader."));
    };

    // -- or: Claude Desktop reads it directly ---------------------------------------
    const desktopBox = h("div");
    const drawDesktop = async () => {
      let st;
      try { st = await api("claude"); } catch (e) { mount(desktopBox, h("div.muted", e.message)); return; }
      mount(desktopBox,
        h("p.muted.small", { style: { margin: "0 0 10px" } },
          "Using the Claude Desktop app? RaidReady can plug into it, so you can just ask Claude \u201cwhat should I run next?\u201d ",
          "and it reads your quests, keys, story, raids and prices itself: no file to export. It only reads what RaidReady has saved on this PC, and works with the RaidReady window closed."),
        st.installed
          ? h("div.note", icon("check", 16), h("div", h("strong", "RaidReady is added to Claude Desktop. "),
            "Restart Claude Desktop if you just added it, then ask it about your raids. Its tools start with \u201craidready_\u201d."))
          : h("div.toolbar",
            button("Add RaidReady to Claude Desktop", async () => {
              if (!confirm("Add RaidReady to Claude Desktop's settings? The old settings file is kept as a .bak copy.")) return;
              try { await api("claude/install", { method: "POST", body: {} }); toast("Added. Restart Claude Desktop to use it.", { kind: "good", timeout: 10000 }); drawDesktop(); }
              catch (e) { toast(e.message, { kind: "bad", timeout: 10000 }); }
            }, { kind: "primary", iconName: "plus" }),
            st.claudeFound ? null : h("span.muted.small", "Claude Desktop doesn't seem to be installed yet; this still works once it is.")),
        h("div.muted.small", { style: { marginTop: "8px" } }, `Settings file: ${st.path}`));
    };

    mount(root, summary,
      card("1 · Your kit and goal", kitBox, { sub: "saved as you type" }),
      card("2 · Keys your open quests use", keysBox, { sub: "tick the ones in your stash" }),
      card("3 · Export", exportBox, { sub: "nothing is sent anywhere; you choose where the file goes" }),
      card("Or skip the file: Claude Desktop", desktopBox, { sub: "Claude reads your progress directly" }));
    drawSummary(); drawKit(); drawKeys(); drawExport(); drawDesktop();

    return on((kind) => {
      if (kind !== "progress") return;
      drawSummary(); drawKeys();
      // A level or quest change elsewhere changes which quests (and keys) count.
      api("advisor").then((s) => { state = s; drawSummary(); drawKeys(); }).catch(() => {});
    });
  },
};
