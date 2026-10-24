import { badge, button, card, debounce, fmt, h, icon, mount, progressBar, toast, toggle } from "../lib.js";
import { displayChange, on, store } from "../store.js";

const SLIDERS = [
  ["brightness", "Brightness", -100, 100, 1, (v) => (v > 0 ? "+" : "") + v],
  ["contrast", "Contrast", 0, 200, 1, (v) => v],
  ["saturation", "Saturation", 0, 200, 1, (v) => v, "Makes player gear stand out from grass and concrete"],
  ["gamma", "Gamma", 0.5, 2.5, 0.05, (v) => Number(v).toFixed(2), "Lifts shadows without washing out the sky"],
  ["temperature", "Colour temperature", 4000, 10000, 100, (v) => `${v} K`],
];
const AUTO = [
  ["gamma_boost", "Extra gamma when dark", 0, 1, 0.05, (v) => "+" + Number(v).toFixed(2)],
  ["brightness_boost", "Extra brightness when dark", 0, 50, 1, (v) => "+" + v],
  ["response_seconds", "Reaction time", 0.3, 5, 0.1, (v) => Number(v).toFixed(1) + " s"],
  ["dark_level", "Counts as fully dark below", 0, 0.5, 0.01, (v) => fmt.pct(v)],
  ["bright_level", "Counts as bright above", 0.05, 0.8, 0.01, (v) => fmt.pct(v)],
];
const DEFAULTS = { brightness: 0, contrast: 100, saturation: 100, temperature: 6500 };

function slider(label, value, [min, max, step], show, oninput, { disabled, hint } = {}) {
  const out = h("span.val", show(value));
  const input = h("input", { type: "range", min, max, step, value, disabled });
  const paint = () => input.style.setProperty("--fill", `${((input.value - min) / (max - min)) * 100}%`);
  input.addEventListener("input", () => { out.textContent = show(Number(input.value)); paint(); oninput(Number(input.value)); slider.touched = Date.now(); });
  paint();
  return h("div.slider-row", h("label", { title: hint || "" }, label, hint ? h("div.muted.small", hint) : null), input, out);
}

export default {
  title: "Display",
  subtitle: "Automatic AMD display settings while Tarkov is focused",
  render(root) {
    const status = h("div");
    const profiles = h("div");
    const auto = h("div");
    const readout = h("div.readout");
    let editing = null;
    let lastEdit = 0; // don't redraw sliders while they're being dragged

    const save = debounce((name, values) => {
      displayChange({ op: "save_profile", name, profile: values }).catch((e) => toast(e.message, { kind: "bad" }));
    }, 250);
    const saveAuto = debounce((settings) => {
      displayChange({ op: "auto", settings }).catch((e) => toast(e.message, { kind: "bad" }));
    }, 250);

    const drawStatus = () => {
      const d = store.display, st = store.state;
      const active = (st.watcher || "").includes("applied");
      mount(status,
        h("div.status-big", h("span.status-dot." + (active ? "ok" : "")), h("div",
          h("div.status-title", active ? `“${st.profile}” is on` : st.paused ? "Paused" : "Waiting for Tarkov to be focused"),
          h("div.muted.small", st.watcher))),
        h("div.chips", { style: { marginTop: "12px" } },
          d.amd ? badge("AMD driver connected", "good") : badge("No AMD driver: gamma only", "warn"),
          d.gamma ? badge("Windows gamma OK", "good") : badge("Gamma unavailable", "bad"),
          ...(d.displays || []).map((n) => badge(n, "muted"))),
        h("div.toolbar", { style: { marginTop: "14px" } },
          toggle("Preview on the desktop now", d.preview, (v) => displayChange({ op: "preview", on: v })),
          toggle("Only while Tarkov is focused", d.foregroundOnly, (v) => displayChange({ op: "foreground_only", on: v }), "Normal colours when you alt-tab"),
          toggle("Pause", d.paused, (v) => displayChange({ op: "pause", on: v }))));
    };

    let shown = "";
    const drawProfiles = () => {
      const d = store.display;
      const name = d.active;
      shown = name + "|" + Object.keys(d.profiles).join(",");
      const p = d.profiles[name] || {};
      editing = { ...p };
      mount(profiles,
        h("div.profile-pills", Object.entries(d.profiles).map(([n, v], i) => h("button.profile-pill" + (n === name ? ".on" : ""), {
          type: "button", onclick: () => displayChange({ op: "select", name: n }),
          title: `Ctrl+Alt+${i + 1} in game`,
        }, n, h("small", `Sat ${v.saturation ?? 100} · Gamma ${Number(v.gamma).toFixed(2)}${i < 9 ? ` · Ctrl+Alt+${i + 1}` : ""}`)))),
        h("div", { style: { marginTop: "16px" } }, SLIDERS.map(([key, label, min, max, step, show, hint]) => {
          if (key === "temperature") {
            const isDefault = p.temperature === null || p.temperature === undefined;
            const row = slider(label, isDefault ? 6500 : p.temperature, [min, max, step], show, (v) => { editing.temperature = v; save(name, editing); }, { disabled: isDefault });
            row.append(h("div.extra", toggle("Use the driver's default", isDefault, (v) => {
              editing.temperature = v ? null : 6500; save(name, editing);
              row.querySelector("input[type=range]").disabled = v;
            })));
            return row;
          }
          const value = p[key] ?? DEFAULTS[key] ?? 1;
          return slider(label, value, [min, max, step], show, (v) => { editing[key] = v; save(name, editing); }, { hint });
        })),
        h("div.toolbar", { style: { marginTop: "12px" } },
          button("New profile", () => {
            const n = prompt("Name for the new profile (copies the current one):");
            if (n) displayChange({ op: "new_profile", name: n.trim(), copy_of: name }).catch((e) => toast(e.message, { kind: "bad" }));
          }, { iconName: "plus" }),
          d.builtin.includes(name) ? button("Reset to built-in", () => displayChange({ op: "reset_profile", name }), { kind: "ghost", iconName: "refresh" }) : null,
          Object.keys(d.profiles).length > 1 ? button("Delete", () => {
            if (confirm(`Delete the profile “${name}”?`)) displayChange({ op: "delete_profile", name }).catch((e) => toast(e.message, { kind: "bad" }));
          }, { kind: "danger", iconName: "trash" }) : null));
    };

    const drawAuto = () => {
      const a = store.display.auto;
      const values = { ...a };
      mount(auto,
        toggle("Boost gamma and brightness in dark areas", a.enabled, (v) => displayChange({ op: "auto", settings: { enabled: v } })),
        h("div.muted.small", { style: { margin: "6px 0 10px" } },
          "Reads 5 small patches of the Tarkov window 4 times a second and eases in extra gamma and brightness when the scene is dark. Use Borderless window mode."),
        readout,
        h("div", { style: { marginTop: "8px" } }, AUTO.map(([key, label, min, max, step, show]) =>
          slider(label, a[key], [min, max, step], show, (v) => { values[key] = v; saveAuto({ [key]: v }); }))));
      drawReadout();
    };

    const drawReadout = () => {
      const st = store.state.auto || {};
      mount(readout,
        h("div.meter", h("div.meter-label", h("span", "Scene brightness"), h("span", st.scene === null || st.scene === undefined ? "–" : fmt.pct(st.scene))),
          progressBar(st.scene || 0, 1, "info")),
        h("div.meter", h("div.meter-label", h("span", "Boost"), h("span", st.enabled ? fmt.pct(st.boost || 0) : "off")),
          progressBar(st.boost || 0, 1)));
    };

    // Price check card: redrawn when its settings change elsewhere (Ctrl+Alt+H
    // in game), not while a slider is being dragged.
    const scan = h("div");
    const hoverStatus = h("div.hover-status");
    let scanShown = "";
    const drawHoverStatus = () => {
      const hv = store.state.hover || {};
      const st = hv.status || "off";
      if (!hv.enabled) return mount(hoverStatus);
      const kind = st === "on" ? "ok" : st.startsWith("can't") || st.startsWith("unavailable") ? "bad" : "";
      const text = st === "on" ? "On: rest the mouse on an item in Tarkov" : st.charAt(0).toUpperCase() + st.slice(1);
      mount(hoverStatus, h("span.status-dot." + (kind || "idle")), h("span", text));
    };
    const drawScan = () => {
      const s = store.display.scan, engine = store.display.ocr, taken = store.display.hotkeysTaken || [];
      scanShown = JSON.stringify([s.hover, s.debug, engine, taken, store.display.hotkeys]);
      mount(scan,
        h("div.chips", { style: { marginBottom: "10px" } },
          engine ? badge(`Reads text with ${engine}`, "good") : badge("No OCR engine", "bad"),
          store.display.hotkeys ? null : badge("Hotkeys are off", "warn"),
          ...["Ctrl+Alt+P", "Ctrl+Alt+H"].filter((k) => taken.includes(k)).map((k) => badge(`${k} is taken`, "bad"))),
        engine ? null : h("div.note.warn", { style: { marginBottom: "10px" } }, icon("alert", 16),
          h("div", "Run ", h("code", "install.bat"), " from the app folder (it adds the text reader built into Windows), then restart the app.")),
        toggle("Show the price when I rest the mouse on an item", s.hover,
          (v) => displayChange({ op: "scan", settings: { hover: v } }).catch((e) => toast(e.message, { kind: "bad" })),
          "Hover price check. Ctrl+Alt+H turns it on and off in game."),
        h("div.muted.small", { style: { margin: "6px 0 8px" } },
          "No key needed: while Tarkov is focused and the mouse pointer is showing (menus, stash, inventory), the price pops up "
          + "when the mouse stops on an item and its name tooltip shows, and goes away when you move on. Ctrl+Alt+H turns it on and off in game. "
          + "It takes a screenshot around the mouse each time it stops, so leave it off if you don't use it."),
        hoverStatus,
        s.hover ? slider("Wait before checking", s.hover_delay, [0.15, 1, 0.05], (v) => `${Number(v).toFixed(2)} s`,
          debounce((v) => displayChange({ op: "scan", settings: { hover_delay: v } }), 300),
          { hint: "How long the mouse has to stay still on an item" }) : null,
        slider("Ctrl+Alt+P popup stays for", s.popup_seconds, [2, 30, 1], (v) => `${v} s`,
          debounce((v) => displayChange({ op: "scan", settings: { popup_seconds: v } }), 300)),
        h("div", { style: { marginTop: "8px" } }, toggle("Save each capture for troubleshooting", s.debug,
          (v) => displayChange({ op: "scan", settings: { debug: v } }), "Saves what was captured and read to %APPDATA%\\TarkovDisplay\\scans")),
        h("div.muted.small", { style: { marginTop: "10px" } },
          "Or hover over an item until its name shows and press Ctrl+Alt+P. Without hover price check, the screen is only read when you press it. "
          + "Use Borderless window mode in Tarkov: in exclusive fullscreen the screenshot comes out black and the popup can't show."));
      drawHoverStatus();
    };

    mount(root,
      h("div.grid.cols-2",
        card("Status", status),
        card("Hotkeys", h("div.hotkeys",
          h("kbd", "Ctrl+Alt+1…9"), h("span", "Switch display profile"),
          h("kbd", "Ctrl+Alt+0"), h("span", "Turn display changes off / on"),
          h("kbd", "Ctrl+Alt+A"), h("span", "Turn auto-boost off / on"),
          h("kbd", "Ctrl+Alt+P"), h("span", "Price-check the item under the mouse"),
          h("kbd", "Ctrl+Alt+H"), h("span", "Turn hover price check on / off"),
          (store.display.hotkeysTaken || []).length ? h("div.note.warn", { style: { gridColumn: "1 / -1", marginTop: "6px" } }, icon("alert", 16),
            h("div", `Another program already uses ${store.display.hotkeysTaken.join(", ")}, so ${store.display.hotkeysTaken.length > 1 ? "they don't" : "it doesn't"} work here. `
              + "Change or turn off that shortcut in the other program (often an overlay like Discord, Steam, AMD or NVIDIA), then restart this app.")) : null),
        { sub: "work while Tarkov is focused" })),
      card("Profiles", profiles, { sub: "AMD Display Color + Windows gamma" }),
      h("div.grid.cols-2",
        card("Auto-boost in dark areas", auto),
        card("Price check", scan)),
      h("div.note", icon("info", 16), h("div", "If high gamma values are refused, run ", h("code", "enable_full_gamma_range.reg"),
        " from the app folder once and reboot. If something looks wrong, AMD Software → Display → Display Color → Reset.")));
    drawStatus(); drawProfiles(); drawAuto(); drawScan();
    return on((kind) => {
      if (kind === "state") { drawStatus(); drawReadout(); drawHoverStatus(); }
      if (kind === "display") {
        drawStatus();
        const d = store.display;
        if (scanShown !== JSON.stringify([d.scan.hover, d.scan.debug, d.ocr, d.hotkeysTaken || [], d.hotkeys])) drawScan();
        lastEdit = Math.max(lastEdit, slider.touched || 0);
        const changed = shown !== store.display.active + "|" + Object.keys(store.display.profiles).join(",");
        if (changed || Date.now() - lastEdit > 1500) { drawProfiles(); drawAuto(); }
      }
    });
  },
};
