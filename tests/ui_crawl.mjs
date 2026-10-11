// Crawls every page of a running RaidReady (see tests/replay.py) in PvP and
// PvE and reports anything that looks broken: script errors, console errors,
// error boxes, and text such as "undefined", "NaN" or "[object Object]" that
// leaks out when data has an unexpected shape.
//
//   node tests/ui_crawl.mjs http://127.0.0.1:47999/
//
// Set PLAYWRIGHT_MODULE to load Playwright from somewhere other than
// node_modules. Exits 1 if it found anything.

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const base = process.argv[2] || "http://127.0.0.1:47999/";
const ROUTES = ["home", "items", "quests", "raid", "hideout", "needed", "barters", "crafts", "ammo",
  "maps", "bosses", "traders", "achievements", "display", "settings"];
const SUSPICIOUS = /\bundefined\b|\bNaN\b|\[object Object\]|\bInfinity\b|\bnull\b/;

const browser = await chromium.launch({ args: ["--no-proxy-server"] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const issues = new Map(); // key -> {where, kind, detail, count}
let where = "start";
const add = (kind, detail) => {
  const text = String(detail).replace(/\s+/g, " ").slice(0, 400);
  const key = `${kind}|${where.split(" ")[0]}|${text}`;
  const known = issues.get(key);
  if (known) known.count += 1;
  else issues.set(key, { where, kind, detail: text, count: 1 });
};
page.on("pageerror", (e) => add("script error", `${e.message} @ ${(e.stack || "").split("\n").slice(1, 3).join(" | ")}`));
page.on("console", (m) => {
  if (m.type() === "error" && !/Failed to load resource|net::ERR_/.test(m.text())) add("console error", m.text());
});

// API calls go from here, not from inside the page: the page reloads itself
// when the game mode changes, which would cancel a request made from it.
let token = null;
const api = async (path, body) => {
  token ??= await page.locator('meta[name="token"]').getAttribute("content");
  const res = await page.request.fetch(base + "api/" + path, {
    method: body ? "POST" : "GET",
    headers: { "X-Token": token, "Content-Type": "application/json" },
    data: body ? JSON.stringify(body) : undefined,
  });
  return { status: res.status(), body: await res.json().catch(() => null) };
};

const settle = async (ms = 500) => {
  await page.waitForTimeout(150);
  await page.waitForFunction(() => !document.querySelector(".content .loading"), null, { timeout: 30000 }).catch(() => add("timeout", "still loading after 30 s"));
  await page.waitForTimeout(ms);
};

// Text anywhere in the content area, hidden parts included (collapsed quest
// cards are rendered but hidden).
async function scan(selector = ".content") {
  const found = await page.evaluate(([selector, source]) => {
    const re = new RegExp(source);
    const out = [];
    for (const root of document.querySelectorAll(selector)) {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        const parent = n.parentElement;
        if (!parent || parent.closest("script, style, input, textarea, code, pre")) continue;
        const text = n.textContent;
        const m = text.match(re);
        if (m) {
          const block = parent.closest("li, tr, .card, .quest, .list-row, p, div") || parent;
          out.push(`"${m[0]}" in: ${block.textContent.replace(/\s+/g, " ").trim().slice(0, 160)}`);
        }
      }
    }
    return out;
  }, [selector, SUSPICIOUS.source]);
  for (const f of found) add("suspicious text", f);
  for (const box of await page.$$(".error-box")) add("error box", await box.innerText());
}

async function visit(route, ms) {
  where = `#/${route}`;
  await page.evaluate((h) => { location.hash = h; }, "#/" + route);
  await settle(ms);
  await scan();
}

async function crawlMode(mode) {
  where = `${mode} setup`;
  const set = await api("settings", { gameMode: mode });
  if (set.status !== 200) add("api", `settings ${mode}: ${JSON.stringify(set.body)}`);
  await page.waitForTimeout(1500); // the app reloads itself when the mode changes
  for (let attempt = 0; ; attempt++) {
    try {
      await page.goto(base);
      break;
    } catch (e) {
      if (attempt >= 3) throw e;
      await page.waitForTimeout(1000);
    }
  }
  await page.waitForSelector(".nav-link", { timeout: 30000 });
  await api("progress", { op: "profile", player_level: 79 });
  for (const route of ROUTES) await visit(route, 700);

  // Every quest, details included.
  where = `${mode} #/quests all`;
  await page.evaluate(() => { location.hash = "#/quests"; });
  await settle();
  await page.click(".seg button:has-text('All')").catch(() => add("ui", "no All filter on Quests"));
  await settle();
  for (let i = 0; i < 30; i++) {
    const more = page.locator(".tbl-more button");
    if (!(await more.count())) break;
    await more.first().click();
    await page.waitForTimeout(250);
  }
  const shown = await page.locator(".quest").count();
  await scan();
  for (const row of (await page.locator(".quest .q-row").all()).slice(0, 25)) await row.click();
  await page.waitForTimeout(300);

  // Raid plan on every map with every quest pinned, and some objectives ticked.
  const tasks = (await api("data/tasks?wait=30")).body.data || [];
  await api("progress", { op: "pin", ids: tasks.map((t) => t.id), pinned: true });
  const objectives = tasks.flatMap((t) => t.objectives || []).filter((o) => o.id);
  for (const o of objectives.filter((_, i) => i % 7 === 0)) {
    await api("progress", { op: "objective", id: o.id, count: Math.max(1, Math.floor((o.count || 1) / 2)) });
  }
  const maps = ((await api("data/maps?wait=30")).body.data || []).filter((m) => m.normalizedName);
  for (const m of maps) await visit(`raid/${m.normalizedName}`, 600);
  await visit("raid", 600);
  await api("progress", { op: "pin", ids: tasks.map((t) => t.id), pinned: false });

  // Every map page.
  for (const m of maps) await visit(`maps/${m.normalizedName}`, 500);

  // Hideout with every station built, then what's still needed.
  const stations = (await api("data/hideout?wait=30")).body.data || [];
  for (const s of stations) await api("progress", { op: "hideout", station: s.id, level: Math.min(10, (s.levels || []).length) });
  await visit("hideout", 600);
  await visit("needed", 600);

  // Item panels: the first rows of the price list, plus a few searched by name.
  where = `${mode} item panels`;
  await page.evaluate(() => { location.hash = "#/items"; });
  await settle();
  const rows = await page.locator(".tbl tbody tr.click").count();
  for (let i = 0; i < Math.min(rows, 40); i++) {
    await page.locator(".tbl tbody tr.click").nth(i).click();
    await page.waitForTimeout(700);
    where = `${mode} item panel #${i}`;
    await scan(".drawer");
    await page.keyboard.press("Escape");
    await page.waitForTimeout(150);
  }
  return { quests: shown, maps: maps.length, objectivesTicked: Math.ceil(objectives.length / 7), itemPanels: Math.min(rows, 40) };
}

const summary = {};
await page.goto(base);
await page.waitForSelector(".nav-link", { timeout: 30000 });
for (const mode of ["regular", "pve"]) summary[mode] = await crawlMode(mode);
await browser.close();

console.log("Crawled:", JSON.stringify(summary));
const list = [...issues.values()].sort((a, b) => a.kind.localeCompare(b.kind) || a.where.localeCompare(b.where));
for (const i of list) console.log(`[${i.kind}] ${i.where}${i.count > 1 ? ` (x${i.count})` : ""}: ${i.detail}`);
console.log(`${list.length} distinct issue(s)`);
process.exit(list.length ? 1 : 0);
