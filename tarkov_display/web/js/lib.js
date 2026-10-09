// Small UI toolkit: DOM building, formatting, API calls, icons, tables.

export const TOKEN = document.querySelector('meta[name="token"]').content;

export async function api(path, { method = "GET", body } = {}) {
  const res = await fetch("/api/" + path, {
    method,
    headers: { "X-Token": TOKEN, ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  let data = {};
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}

const SVG_TAGS = new Set(["svg", "path", "circle", "line", "polyline", "polygon", "rect", "g", "text", "defs",
  "linearGradient", "stop", "title"]);

// h("div.card.big", {onclick, title}, child, [children], "text")
export function h(tag, props, ...children) {
  const [name, ...classes] = tag.split(".");
  const el = SVG_TAGS.has(name)
    ? document.createElementNS("http://www.w3.org/2000/svg", name)
    : document.createElement(name || "div");
  if (classes.length) el.setAttribute("class", classes.join(" "));
  if (props !== null && props !== undefined && (typeof props !== "object" || props instanceof Node || Array.isArray(props))) {
    children.unshift(props);
    props = null;
  }
  for (const [k, v] of Object.entries(props || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "class") el.setAttribute("class", [el.getAttribute("class"), v].filter(Boolean).join(" "));
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k === "value" && "value" in el) el.value = v;
    else if (k === "checked") el.checked = !!v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    if (Array.isArray(c)) append(el, c);
    else el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export function mount(el, ...children) {
  el.replaceChildren();
  append(el, children);
  return el;
}

// -- formatting --------------------------------------------------------------

const nf = new Intl.NumberFormat("en-US");
export const fmt = {
  num: (n) => (n === null || n === undefined || Number.isNaN(n) ? "–" : nf.format(Math.round(n)).replace(/,/g, " ")),
  rub: (n) => (n === null || n === undefined || Number.isNaN(n) ? "–" : fmt.num(n) + " ₽"),
  signedRub: (n) => (n === null || n === undefined || Number.isNaN(n) ? "–" : (n > 0 ? "+" : n < 0 ? "−" : "") + fmt.rub(Math.abs(n))),
  short: (n) => {
    if (n === null || n === undefined) return "–";
    const a = Math.abs(n);
    if (a >= 999500) return parseFloat((n / 1e6).toFixed(a >= 9995000 ? 1 : 2)) + "M"; // not "1000k"
    if (a >= 1e3) return Math.round(n / 1e3) + "k";
    return String(Math.round(n));
  },
  pct: (n, digits = 0) => (n === null || n === undefined ? "–" : `${(n * 100).toFixed(digits)}%`),
  signedPct: (n) => (n === null || n === undefined ? "–" : `${n > 0 ? "+" : ""}${n.toFixed(1)}%`),
  ago: (t) => {
    if (!t) return "never";
    const s = Math.max(0, Date.now() / 1000 - (t > 1e12 ? t / 1000 : t));
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.floor(s / 60)} min ago`;
    if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
    return `${Math.floor(s / 86400)} d ago`;
  },
  countdown: (ms) => {
    if (ms <= 0) return "now";
    const s = Math.floor(ms / 1000);
    const hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
    return (hh ? `${hh}:${String(mm).padStart(2, "0")}` : `${mm}`) + `:${String(ss).padStart(2, "0")}`;
  },
  duration: (sec) => {
    if (!sec) return "–";
    if (sec < 60) return `${Math.round(sec)}s`;
    const total = Math.round(sec / 60), h = Math.floor(total / 60), m = total % 60; // never "1h 60m"
    return h ? `${h}h${m ? ` ${m}m` : ""}` : `${m}m`;
  },
  date: (iso) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  },
};

export function norm(text) {
  return (text || "").toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, " ").trim();
}

export function matches(query, ...fields) {
  const q = norm(query);
  if (!q) return true;
  const hay = norm(fields.filter(Boolean).join(" "));
  return q.split(" ").every((t) => hay.includes(t));
}

export function debounce(fn, ms = 150) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

export const local = {
  get(key, fallback) {
    try {
      const v = localStorage.getItem("tc." + key);
      return v === null ? fallback : JSON.parse(v);
    } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem("tc." + key, JSON.stringify(value)); } catch { /* private mode */ }
  },
};

// -- icons -------------------------------------------------------------------

const ICONS = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z",
  items: "M12 2 3 7v10l9 5 9-5V7zM3 7l9 5 9-5M12 12v10",
  quests: "M8 3h9a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M5 6a3 3 0 0 1 3-3M9 8h6M9 12h6M9 16h4",
  hideout: "M3 21V9l9-6 9 6v12M8 21v-7h8v7M3 21h18",
  needed: "M9 6h11M9 12h11M9 18h11M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2",
  barters: "M4 7h13l-3-3M20 17H7l3 3",
  crafts: "M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4a2 2 0 0 0 1.8-3l-5-9V3M7 15h10",
  ammo: "M8 22h8M9 22V9l3-6 3 6v13M9 12h6",
  maps: "M9 4 3 6v14l6-2 6 2 6-2V4l-6 2zM9 4v14M15 6v14",
  bosses: "M12 2a8 8 0 0 0-8 8c0 3 1.6 5 3 6v3h10v-3c1.4-1 3-3 3-6a8 8 0 0 0-8-8zM9 11h.01M15 11h.01M10 19v2M14 19v2",
  traders: "M16 20v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM22 20v-1a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8",
  achievements: "M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0zM7 6H4a3 3 0 0 0 3 4M17 6h3a3 3 0 0 1-3 4",
  display: "M3 4h18v12H3zM8 21h8M12 16v5",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3",
  refresh: "M21 12a9 9 0 1 1-2.6-6.4M21 3v6h-6",
  external: "M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
  check: "M4 12.5 9 17.5 20 6.5",
  x: "M6 6l12 12M18 6 6 18",
  chevron: "M9 6l6 6-6 6",
  down: "M6 9l6 6 6-6",
  download: "M12 3v12M7 10l5 5 5-5M4 21h16",
  upload: "M12 21V9M7 14l5-5 5 5M4 3h16",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
  alert: "M12 3 2 21h20zM12 10v4M12 17.5v.01",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v6M12 7.5v.01",
  star: "M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z",
  key: "M15 7a4 4 0 1 1-3.5 6L3 21.5V18h3v-3h3l2.5-2.5A4 4 0 0 1 15 7zM16 8h.01",
  power: "M12 3v9M6.3 6.3a8 8 0 1 0 11.4 0",
  eye: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  plus: "M12 5v14M5 12h14",
  minus: "M5 12h14",
  trash: "M4 7h16M10 11v6M14 11v6M5 7l1 13h12l1-13M9 7V4h6v3",
  zoomin: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3M11 8v6M8 11h6",
  zoomout: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3M8 11h6",
  expand: "M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5",
  signal: "M2 20h.01M7 20v-4M12 20v-8M17 20V8M22 4v16",
  skull: "M12 2a8 8 0 0 0-8 8c0 3 1.6 5 3 6v3h10v-3c1.4-1 3-3 3-6a8 8 0 0 0-8-8z",
  bolt: "M13 2 4 14h7l-1 8 9-12h-7z",
  lock: "M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4",
  exit: "M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4M10 17l5-5-5-5M15 12H3",
  pin: "M12 17v5M9 3h6l-1 6 4 4v2H6v-2l4-4z",
  raid: "M12 22s7-6.3 7-12a7 7 0 0 0-14 0c0 5.7 7 12 7 12zM12 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z",
};

export function icon(name, size = 18, cls = "") {
  return h("svg", {
    class: "ic " + cls, width: size, height: size, viewBox: "0 0 24 24", fill: "none",
    stroke: "currentColor", "stroke-width": 1.8, "stroke-linecap": "round", "stroke-linejoin": "round",
    "aria-hidden": "true",
  }, h("path", { d: ICONS[name] || ICONS.info }));
}

// -- small widgets -------------------------------------------------------------

export function badge(text, kind = "muted", title) {
  return h("span.badge." + kind, { title }, text);
}

export function button(label, onclick, { kind = "", iconName, title, disabled } = {}) {
  return h("button.btn" + (kind ? "." + kind : ""), { onclick, title, disabled, type: "button" },
    iconName ? icon(iconName, 16) : null, label ? h("span", label) : null);
}

export function segmented(options, value, onchange) {
  return h("div.seg", options.map(([v, label]) =>
    h("button" + (v === value ? ".on" : ""), { type: "button", onclick: () => onchange(v) }, label)));
}

export function toggle(label, checked, onchange, hint) {
  return h("label.toggle", { title: hint },
    h("input", { type: "checkbox", checked, onchange: (e) => onchange(e.target.checked) }),
    h("span.track", h("span.knob")), h("span.toggle-label", label));
}

export function stepper(value, min, max, onchange, { width } = {}) {
  const set = (v) => onchange(Math.max(min, Math.min(max, v)));
  return h("div.stepper", { style: width ? { width } : null },
    h("button", { type: "button", onclick: () => set(value - 1), disabled: value <= min, title: "Less" }, icon("minus", 14)),
    h("span", String(value)),
    h("button", { type: "button", onclick: () => set(value + 1), disabled: value >= max, title: "More" }, icon("plus", 14)));
}

export function searchInput(placeholder, value, oninput, { autofocus } = {}) {
  const input = h("input", {
    type: "search", placeholder, value, autofocus, spellcheck: "false",
    oninput: debounce((e) => oninput(e.target.value), 120),
  });
  return h("div.search", icon("search", 16), input);
}

export function select(options, value, onchange, { title } = {}) {
  return h("select", { onchange: (e) => onchange(e.target.value), title },
    options.map(([v, label]) => h("option", { value: v, selected: v === value }, label)));
}

export function card(title, body, { actions, cls = "", sub } = {}) {
  return h("section.card" + (cls ? "." + cls : ""),
    title ? h("header.card-head", h("h3", title), sub ? h("span.card-sub", sub) : null,
      actions ? h("div.card-actions", actions) : null) : null,
    h("div.card-body", body));
}

export function stat(label, value, { sub, kind = "" } = {}) {
  return h("div.stat" + (kind ? "." + kind : ""), h("div.stat-label", label), h("div.stat-value", value),
    sub ? h("div.stat-sub", sub) : null);
}

export function progressBar(done, total, kind = "") {
  const pct = total ? Math.min(100, (done / total) * 100) : 0;
  return h("div.bar" + (kind ? "." + kind : ""), h("div.bar-fill", { style: { width: pct + "%" } }));
}

export function loading(text = "Loading…") {
  return h("div.loading", h("span.spinner"), text);
}

export function empty(text, sub) {
  return h("div.empty", icon("info", 22), h("div", text), sub ? h("div.empty-sub", sub) : null);
}

export function errorBox(message, retry) {
  return h("div.error-box", icon("alert", 20),
    h("div", h("strong", "Couldn't load this from tarkov.dev"), h("div.muted", message),
      h("div.muted.small", "tarkov.dev may be busy. The app keeps the last data it downloaded and retries on its own.")),
    retry ? button("Try again", retry, { iconName: "refresh" }) : null);
}

export function img(src, { cls = "", alt = "", size } = {}) {
  const el = h("img" + (cls ? "." + cls : ""), {
    src: src || "", alt, loading: "lazy", decoding: "async", referrerpolicy: "no-referrer",
    width: size, height: size,
  });
  el.addEventListener("error", () => el.classList.add("broken"), { once: true });
  if (!src) el.classList.add("broken");
  return el;
}

export function ext(href, text, cls = "") {
  return h("a.ext" + (cls ? "." + cls : ""), { href, target: "_blank", rel: "noopener noreferrer" }, text, icon("external", 13));
}

// -- toasts ----------------------------------------------------------------------

export function toast(message, { kind = "", action, actionLabel, timeout = 5000 } = {}) {
  let box = document.querySelector(".toasts");
  if (!box) box = document.body.appendChild(h("div.toasts"));
  const t = h("div.toast" + (kind ? "." + kind : ""),
    h("div.toast-msg", message),
    action ? h("button.toast-act", { type: "button", onclick: () => { action(); t.remove(); } }, actionLabel || "Open") : null,
    h("button.toast-x", { type: "button", onclick: () => t.remove(), title: "Dismiss" }, icon("x", 14)));
  box.appendChild(t);
  if (timeout) setTimeout(() => t.classList.add("bye"), timeout);
  if (timeout) setTimeout(() => t.remove(), timeout + 400);
  return t;
}

// -- tables --------------------------------------------------------------------------

// columns: [{key, label, num, sort: (row) => value, render: (row) => node, width, cls}]
export function table({ columns, rows, sortKey, sortDir = "desc", onSort, onRow, limit = 100, emptyText = "Nothing here.", rowClass }) {
  let shown = limit;
  const sorted = [...rows];
  const col = columns.find((c) => c.key === sortKey);
  if (col && col.sort) {
    const dir = sortDir === "asc" ? 1 : -1;
    sorted.sort((a, b) => {
      const va = col.sort(a), vb = col.sort(b);
      if (va === vb) return 0;
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * dir;
    });
  }
  const tbody = h("tbody");
  const wrap = h("div.tbl-wrap");
  const more = h("div.tbl-more");
  const fill = () => {
    tbody.replaceChildren(...sorted.slice(0, shown).map((row) =>
      h("tr" + (onRow ? ".click" : ""), { onclick: onRow ? () => onRow(row) : null, class: rowClass ? rowClass(row) : null },
        columns.map((c) => h("td" + (c.num ? ".num" : "") + (c.cls ? "." + c.cls : ""), c.render ? c.render(row) : row[c.key])))));
    mount(more, sorted.length > shown
      ? button(`Show more (${fmt.num(sorted.length - shown)} left)`, () => { shown += limit; fill(); }, { kind: "ghost" })
      : null);
  };
  const head = h("thead", h("tr", columns.map((c) => {
    const active = c.key === sortKey;
    return h("th" + (c.num ? ".num" : "") + (c.sort ? ".sortable" : "") + (active ? ".active" : ""), {
      style: c.width ? { width: c.width } : null,
      onclick: c.sort && onSort ? () => onSort(c.key, active && sortDir === "desc" ? "asc" : "desc") : null,
    }, c.label, active ? h("span.sort-dir", sortDir === "asc" ? "▲" : "▼") : null);
  })));
  if (!sorted.length) return h("div.tbl-wrap", empty(emptyText));
  fill();
  return mount(wrap, h("table.tbl", head, tbody), more);
}
