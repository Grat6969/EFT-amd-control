// Tiny SVG charts (no libraries, works offline).

import { fmt, h } from "./lib.js";

function niceTicks(min, max, count = 4) {
  if (min === max) { min -= 1; max += 1; }
  const span = max - min;
  const step0 = Math.pow(10, Math.floor(Math.log10(span / count)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * step0).find((s) => span / s <= count) || step0 * 10;
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(v);
  return { lo, hi, ticks };
}

// points: [{t: ms, v: number, min?: number}]
export function priceChart(points, { width = 470, height = 190 } = {}) {
  const pts = points.filter((p) => p.v).sort((a, b) => a.t - b.t);
  if (pts.length < 2) return h("div.chart-empty", "Not enough price history yet.");
  const pad = { l: 52, r: 10, t: 10, b: 24 };
  const W = width - pad.l - pad.r, H = height - pad.t - pad.b;
  const t0 = pts[0].t, t1 = pts[pts.length - 1].t;
  const vals = pts.flatMap((p) => [p.v, p.min || p.v]);
  const { lo, hi, ticks } = niceTicks(Math.min(...vals), Math.max(...vals));
  const x = (t) => pad.l + ((t - t0) / Math.max(1, t1 - t0)) * W;
  const y = (v) => pad.t + H - ((v - lo) / Math.max(1, hi - lo)) * H;
  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join("");
  const area = `${line}L${x(t1).toFixed(1)},${pad.t + H}L${x(t0).toFixed(1)},${pad.t + H}Z`;
  const minLine = pts.some((p) => p.min)
    ? pts.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.min || p.v).toFixed(1)}`).join("") : null;
  const days = [];
  const d0 = new Date(t0); d0.setHours(0, 0, 0, 0);
  for (let d = d0.getTime() + 86400000; d < t1; d += 86400000) days.push(d);
  const svg = h("svg.chart", { viewBox: `0 0 ${width} ${height}`, width: "100%", preserveAspectRatio: "none" },
    h("defs", h("linearGradient", { id: "pc-grad", x1: 0, y1: 0, x2: 0, y2: 1 },
      h("stop", { offset: "0%", "stop-color": "var(--accent)", "stop-opacity": 0.35 }),
      h("stop", { offset: "100%", "stop-color": "var(--accent)", "stop-opacity": 0 }))),
    ticks.map((v) => h("g",
      h("line", { x1: pad.l, x2: width - pad.r, y1: y(v), y2: y(v), class: "grid" }),
      h("text", { x: pad.l - 6, y: y(v) + 4, "text-anchor": "end", class: "axis" }, fmt.short(v)))),
    days.map((d) => h("text", { x: x(d), y: height - 6, "text-anchor": "middle", class: "axis" },
      new Date(d).toLocaleDateString(undefined, { weekday: "short" }))),
    h("path", { d: area, fill: "url(#pc-grad)" }),
    minLine ? h("path", { d: minLine, class: "line-min" }) : null,
    h("path", { d: line, class: "line" }));
  return h("div.chart-wrap", svg, h("div.chart-legend",
    h("span.lg.avg", "Average"), minLine ? h("span.lg.min", "Lowest") : null));
}

// points: [{x, y, label, color, title}]
export function scatter(points, { width = 900, height = 380, xLabel = "", yLabel = "", onClick, bands } = {}) {
  if (!points.length) return h("div.chart-empty", "Nothing to plot.");
  const pad = { l: 48, r: 18, t: 14, b: 38 };
  const W = width - pad.l - pad.r, H = height - pad.t - pad.b;
  const xs = niceTicks(0, Math.max(...points.map((p) => p.x)) * 1.05, 8);
  const ys = niceTicks(0, Math.max(...points.map((p) => p.y), 10) * 1.05, 6);
  const x = (v) => pad.l + ((v - xs.lo) / (xs.hi - xs.lo)) * W;
  const y = (v) => pad.t + H - ((v - ys.lo) / (ys.hi - ys.lo)) * H;
  return h("svg.chart.scatter", { viewBox: `0 0 ${width} ${height}`, width: "100%" },
    (bands || []).map((b) => h("g",
      h("rect", { x: pad.l, width: W, y: y(Math.min(b.to, ys.hi)), height: Math.max(0, y(b.from) - y(Math.min(b.to, ys.hi))), class: "band " + (b.cls || "") }),
      h("text", { x: width - pad.r - 4, y: y(Math.min(b.to, ys.hi)) + 12, "text-anchor": "end", class: "band-label" }, b.label))),
    ys.ticks.map((v) => h("g",
      h("line", { x1: pad.l, x2: width - pad.r, y1: y(v), y2: y(v), class: "grid" }),
      h("text", { x: pad.l - 6, y: y(v) + 4, "text-anchor": "end", class: "axis" }, v))),
    xs.ticks.map((v) => h("text", { x: x(v), y: height - 20, "text-anchor": "middle", class: "axis" }, v)),
    h("text", { x: pad.l + W / 2, y: height - 4, "text-anchor": "middle", class: "axis-title" }, xLabel),
    h("text", { x: 12, y: pad.t + H / 2, "text-anchor": "middle", class: "axis-title", transform: `rotate(-90 12 ${pad.t + H / 2})` }, yLabel),
    points.map((p) => h("g.pt", { onclick: onClick ? () => onClick(p) : null },
      h("title", p.title || p.label),
      h("circle", { cx: x(p.x), cy: y(p.y), r: 5, fill: p.color || "var(--accent)" }),
      h("text", { x: x(p.x) + 8, y: y(p.y) + 4, class: "pt-label" }, p.label))));
}
