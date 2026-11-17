// Story chapters: the 1.0 storyline, which tarkov.dev's quest data doesn't
// include. The steps come with the app (story.py); your ticks are saved like
// quest progress, separately for PvP and PvE.

import { api, badge, button, debounce, empty, ext, fmt, h, loading, mount, progressBar, segmented, stat, toast, toggle } from "../lib.js";
import { on, setProgress, store } from "../store.js";

const state = { hideDone: false, kind: "all", open: new Set() };

function done() {
  return new Set(store.progress?.story?.steps || []);
}

// Mirrors story.chapter_status in story.py.
function status(ch, ticked) {
  const routes = new Set(ch.steps.filter((s) => s.branch && ticked.has(s.id)).map((s) => s.branch));
  const required = ch.steps.filter((s) => !s.optional && (!s.branch || routes.has(s.branch)));
  const finished = ch.steps.filter((s) => ticked.has(s.id)).length;
  const reqLeft = required.filter((s) => !ticked.has(s.id)).length;
  const st = !finished ? "not started" : !reqLeft ? "done" : "in progress";
  return { state: st, finished, total: ch.steps.length };
}

export default {
  title: "Story",
  subtitle: "The story chapters, step by step. Tick what you've done; it goes into the Ask Claude export",
  async render(root) {
    mount(root, loading("Loading the story chapters…"));
    let data;
    try {
      data = await api("story");
    } catch (e) {
      mount(root, empty("Couldn't load the story chapters", e.message));
      return;
    }
    const summary = h("div.stat-grid");
    const list = h("div.story-list");

    const set = (ids, on_) => setProgress({ op: "story", ids, done: on_ }).catch((e) => toast(e.message, { kind: "bad" }));
    const saveNote = debounce((chapter, text) => setProgress({ op: "story_note", chapter, text })
      .catch((e) => toast(e.message, { kind: "bad" })), 600);

    const draw = () => {
      const ticked = done();
      const notes = store.progress?.story?.notes || {};
      const all = data.chapters.map((ch) => ({ ch, st: status(ch, ticked) }));
      mount(summary,
        stat("Chapters done", `${all.filter((x) => x.st.state === "done").length} / ${all.length}`, { kind: "accent" }),
        stat("In progress", fmt.num(all.filter((x) => x.st.state === "in progress").length)),
        stat("Steps ticked", `${ticked.size}`, { sub: `of ${all.reduce((n, x) => n + x.st.total, 0)}` }),
        stat("Main story", all.filter((x) => x.ch.kind === "main").map((x) => x.st.state === "done" ? "✓" : `${x.st.finished}/${x.st.total}`).join(" · "),
          { sub: "Tour · Falling Skies · The Ticket" }));
      const shown = all.filter((x) => state.kind === "all" || x.ch.kind === state.kind);
      mount(list, shown.map(({ ch, st }) => {
        const isOpen = state.open.has(ch.id) || (!state.open.size && st.state === "in progress");
        const steps = state.hideDone ? ch.steps.filter((s) => !ticked.has(s.id)) : ch.steps;
        const body = h("div.story-body",
          h("div.story-meta",
            h("div", h("span.muted", "Starts: "), ch.start),
            ch.choices.length ? h("div.story-choices", h("span.muted", "Choices:"), h("ul", ch.choices.map((c) => h("li", c)))) : null,
            h("div", h("span.muted", "Reward: "), ch.reward)),
          h("div.list", steps.map((s) => {
            const on_ = ticked.has(s.id);
            const idx = ch.steps.indexOf(s);
            return h("div.list-row.story-step" + (on_ ? ".done" : ""),
              h("input", { type: "checkbox", checked: on_, title: on_ ? "Mark not done" : "Mark done", onchange: (e) => set([s.id], e.target.checked) }),
              h("span.story-n", String(idx + 1)),
              h("div.grow",
                h("div", s.text),
                h("div.chips.small",
                  s.map ? badge(s.map, "info") : badge("Trader / hideout", "muted"),
                  s.need ? badge(s.need, "warn") : null,
                  s.optional ? badge("Optional", "muted") : null,
                  s.branch ? badge(`Only if: ${s.branch}`, "accent") : null)),
              !on_ && idx > 0 ? h("button.btn.small.ghost", { type: "button", title: "Tick this step and every step before it",
                onclick: () => set(ch.steps.slice(0, idx + 1).filter((x) => !x.optional || ticked.has(x.id)).map((x) => x.id), true) }, "Done up to here") : null);
          })),
          h("div.story-note",
            h("div.muted.small", "Your notes: choices you made, where you're stuck (goes into the export)"),
            h("textarea.adv-notes", { rows: 2, maxlength: 500, placeholder: "e.g. Gave the case to Prapor",
              oninput: (e) => saveNote(ch.id, e.target.value) }, notes[ch.id] || "")),
          h("div.toolbar",
            button("Mark chapter done", () => set(ch.steps.filter((s) => !s.optional).map((s) => s.id), true), { kind: "ghost", iconName: "check" }),
            st.finished ? button("Clear chapter", () => set(ch.steps.map((s) => s.id), false), { kind: "ghost", iconName: "x" }) : null));
        const details = h("details.card.story-card" + (st.state === "done" ? ".is-done" : ""), { open: isOpen },
          h("summary.story-head",
            h("div.grow",
              h("div.story-title", ch.name, " ", badge(ch.kind === "main" ? "Main story" : "Investigation", ch.kind === "main" ? "accent" : "muted")),
              h("div.muted.small", ch.summary)),
            h("div.story-prog",
              badge(st.state === "done" ? "Done" : st.state === "in progress" ? "In progress" : "Not started",
                st.state === "done" ? "good" : st.state === "in progress" ? "info" : "muted"),
              h("div.muted.small", `${st.finished} / ${st.total} steps`),
              progressBar(st.finished, st.total, st.state === "done" ? "good" : ""))),
          body);
        details.addEventListener("toggle", () => {
          if (!state.open.size) all.forEach((x) => { if (x.st.state === "in progress") state.open.add(x.ch.id); });
          details.open ? state.open.add(ch.id) : state.open.delete(ch.id);
        });
        return details;
      }));
    };

    mount(root, summary,
      h("div.toolbar",
        segmented([["all", "All chapters"], ["main", "Main story"], ["investigation", "Investigations"]], state.kind, (v) => { state.kind = v; rebuild(); draw(); }),
        toggle("Hide ticked steps", state.hideDone, (v) => { state.hideDone = v; draw(); }),
        h("span.spacer"),
        h("span.muted.small", "Steps from ", ext(data.sourceUrl, "community guides"), ". If one doesn't match the game, the game is right.")),
      list);
    function rebuild() {
      const seg = root.querySelector(".seg");
      if (seg) [...seg.children].forEach((b, i) => b.classList.toggle("on", ["all", "main", "investigation"][i] === state.kind));
    }
    draw();
    return on((kind) => {
      // Don't rebuild under someone typing a note: the box would lose focus.
      if (kind === "progress" && !(document.activeElement && document.activeElement.closest?.(".story-note"))) draw();
    });
  },
};
