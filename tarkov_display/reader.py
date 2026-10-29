"""Works out which item the mouse is on from text read off the screen.

Two things on Tarkov's stash screen name the item under the mouse:

- the game's tooltip, with the item's full name, which shows near the mouse
  once it rests on an item
- the short name printed in the top right corner of every item

The trouble is everything else: every item around it has a short name too,
and some short names (Toolset, Bolts...) are also full names. So each piece
of text is placed: the item's own label is the nearest one above and to the
right of the mouse (an item's corner label sits above and right of anywhere
on the item), never a neighbour below or to the left, however close. Then
the tooltip and the label are scored together against every item, so a
misread letter in one is outvoted by the other (Dorm room 206 vs 208). When
the evidence is weak or two items fit about as well, there's no answer:
better than naming the wrong item.

Text is compared the way OCR gets it wrong: O and 0, l and 1, S and 5 count
as the same, and similar digits (6 and 8) as nearly the same, but no more:
many items differ by just one digit or word.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .prices import Item, normalize

Box = Tuple[float, float, float, float]  # left, top, right, bottom (screen pixels)

# Characters OCR mixes up, mapped to one stand-in (both sides get the same).
_CANON = str.maketrans({"0": "o", "1": "l", "i": "l", "|": "l", "5": "s", "2": "z", "8": "b"})
# After that: pairs that look alike, so swapping them costs less than other mistakes.
_ALIKE = {frozenset(p) for p in ("3b", "s6", "6b", "l7", "49", "ce", "uv", "nh", "oc", "ao", "mn", "ft", "lt", "rl")}
ALIKE_COST = 0.55   # a lookalike character swapped
SPACE_COST = 0.3    # a space added or lost (OCR often joins or splits words)

TOOLTIP_MIN = 0.8   # a tooltip read must fit an item's full name this well...
LABEL_MIN = 0.86    # ... and a label its short name this well
LABEL_LIKE = 0.7    # text that fits some short name this well may be a label (and hides labels behind it)
CLOSE = 0.3         # names within this many letter edits of the best fit count as "about as well"
NEAR = 220          # the tooltip is read within this many pixels of the mouse (at 1080p)


def canon(text: str) -> str:
    t = normalize(text).replace("rn", "m").replace("vv", "w").translate(_CANON)
    return t.replace("lj", "u")  # U read as IJ or 1J


def distance(a: str, b: str, limit: float = 1e9) -> float:
    """Weighted edit distance between two canon() strings (see ALIKE_COST...)."""
    if a == b:
        return 0.0
    if not a or not b:
        return sum(SPACE_COST if c == " " else 1.0 for c in a or b)
    prev = [0.0]
    for c in b:
        prev.append(prev[-1] + (SPACE_COST if c == " " else 1.0))
    for ca in a:
        del_a = SPACE_COST if ca == " " else 1.0
        cur = [prev[0] + del_a]
        best = cur[0]
        for j, cb in enumerate(b, 1):
            if ca == cb:
                sub = prev[j - 1]
            else:
                sub = prev[j - 1] + (ALIKE_COST if frozenset((ca, cb)) in _ALIKE else 1.0)
            v = min(sub, prev[j] + del_a, cur[j - 1] + (SPACE_COST if cb == " " else 1.0))
            cur.append(v)
            if v < best:
                best = v
        if best > limit:
            return best
        prev = cur
    return prev[-1]


def similarity(a: str, b: str, floor: float = 0.0) -> float:
    """1 for the same text, falling towards 0 (both canon() strings). Below
    ``floor`` the answer is only roughly right (it gives up early)."""
    if a == b:
        return 1.0
    longest = max(len(a), len(b))
    if abs(len(a) - len(b)) * SPACE_COST > (1 - floor) * longest:
        return 0.0
    return max(0.0, 1.0 - distance(a, b, limit=(1 - floor) * longest + 1) / longest)


def contained_edits(text: str, name: str) -> float:
    """Letter edits to find ``name`` somewhere inside a longer ``text`` (the
    text around it costs nothing here)."""
    if not name:
        return 0.0
    # Edit distance with free skips at the start and end of ``text``.
    prev = [0.0] * (len(text) + 1)
    for i, cn in enumerate(name, 1):
        cur = [prev[0] + 1.0]
        for j, ct in enumerate(text, 1):
            sub = prev[j - 1] + (0.0 if cn == ct else ALIKE_COST if frozenset((cn, ct)) in _ALIKE else 1.0)
            cur.append(min(sub, prev[j] + 1.0, cur[j - 1] + 1.0))
        prev = cur
    return min(prev)


UNEXPLAINED = 0.1   # each letter of a read that a name found inside it leaves unexplained


def fit(text: str, name: str) -> Tuple[float, float]:
    """(similarity, letter edits) of a read and a full name, both canon().
    A name can also fit part of a longer read (a tooltip read together with
    a neighbour's label), at a small cost per letter left over: so a read of
    "Balaclava (Red Oni)" fits that name far better than plain "Balaclava"."""
    if text == name:
        return 1.0, 0.0
    longest = max(len(text), len(name), 1)
    d = distance(text, name, limit=0.5 * longest + 1)
    best = (max(0.0, 1.0 - d / longest), d)
    extra = len(text) - len(name)
    if extra > 3 and name:
        dp = contained_edits(text, name) + UNEXPLAINED * extra
        sp = max(0.0, 1.0 - dp / len(name))
        if sp > best[0]:
            best = (sp, dp)
    return best


def _grams(text: str, n: int = 3) -> set:
    t = f" {text} "
    return {t[i:i + n] for i in range(len(t) - n + 1)}


class ItemIndex:
    """Every item's full and short name, ready for fuzzy lookups."""

    def __init__(self, items: Sequence[Item]) -> None:
        self.full: Dict[str, List[Item]] = defaultdict(list)
        self.short: Dict[str, List[Item]] = defaultdict(list)
        for item in items:
            for key, index in ((canon(item.name), self.full), (canon(item.short_name), self.short)):
                if key and item not in index[key]:
                    index[key].append(item)
        for index in (self.full, self.short):
            for key, found in index.items():
                # A weapon's presets share its short name: the base item stands for them.
                if any(not i.is_preset for i in found):
                    index[key] = [i for i in found if not i.is_preset]
        self._grams = {(kind, n): self._gram_index(index, n) for kind, index in (("full", self.full), ("short", self.short))
                       for n in (2, 3)}

    @staticmethod
    def _gram_index(index: Dict[str, List[Item]], n: int) -> Dict[str, List[str]]:
        grams: Dict[str, List[str]] = defaultdict(list)
        for key in index:
            if n == 3 or len(key) <= 6:
                for g in _grams(key, n):
                    grams[g].append(key)
        return grams

    def keys(self, kind: str) -> Dict[str, List[Item]]:
        return self.full if kind == "full" else self.short

    def lookup(self, text: str, kind: str, k: int = 8) -> List[Tuple[str, float]]:
        """The ``k`` names (canon keys) of ``kind`` ("full" or "short") most
        like ``text``, best first, with their similarity."""
        q = canon(text)
        index = self.keys(kind)
        if not q:
            return []
        if q in index:
            exact = [(q, 1.0)]
        else:
            exact = []
        n = 2 if len(q) <= 5 else 3  # short texts have too few trigrams to go on
        counts: Dict[str, int] = defaultdict(int)
        for g in _grams(q, n):
            for key in self._grams[(kind, n)].get(g, ()):
                counts[key] += 1
        shortlist = sorted(counts, key=lambda key: -counts[key])[:40]
        scored = []
        for key in shortlist:
            if key == q:
                continue
            s = fit(q, key)[0] if kind == "full" else similarity(q, key, floor=0.6)
            scored.append((key, s))
        scored.sort(key=lambda t: -t[1])
        return (exact + scored)[:k]


# -- placing text on the screen ---------------------------------------------------------------


@dataclass
class Segment:
    """A run of words close together on one line, in screen pixels."""

    text: str
    box: Box

    @property
    def height(self) -> float:
        return self.box[3] - self.box[1]


def segments(lines: Iterable, origin: Tuple[float, float] = (0, 0), scale: float = 1.0,
             gap: float = 0.75) -> List[Segment]:
    """OCR lines (with word boxes, see ocr.OcrLine) split where the words are
    far apart (more than ``gap`` times their height): OCR runs neighbouring
    grid labels together into one line. Boxes go from image to screen pixels."""
    ox, oy = origin
    out: List[Segment] = []
    for line in lines:
        words = list(getattr(line, "words", ()) or ())
        if not words:
            x0, y0, x1, y1 = getattr(line, "box", None) or (line.x, line.y, line.x, line.y)
            words = [(line.text, (x0, y0, x1, y1))]
        run_text, run_box = [], None
        for text, (x0, y0, x1, y1) in words:
            if run_box is not None:
                h = max(run_box[3] - run_box[1], y1 - y0, 1)
                if x0 - run_box[2] > gap * h:
                    out.append(_segment(run_text, run_box, ox, oy, scale))
                    run_text, run_box = [], None
            run_text.append(text)
            run_box = (x0, y0, x1, y1) if run_box is None else (
                min(run_box[0], x0), min(run_box[1], y0), max(run_box[2], x1), max(run_box[3], y1))
        if run_box is not None:
            out.append(_segment(run_text, run_box, ox, oy, scale))
    return [s for s in out if s.text.strip()]


def _segment(words, box, ox, oy, scale) -> Segment:
    x0, y0, x1, y1 = box
    return Segment(" ".join(words), (ox + x0 / scale, oy + y0 / scale, ox + x1 / scale, oy + y1 / scale))


def box_distance(point: Tuple[float, float], box: Box) -> float:
    x, y = point
    dx = max(box[0] - x, 0.0, x - box[2])
    dy = max(box[1] - y, 0.0, y - box[3])
    return (dx * dx + dy * dy) ** 0.5


def own_label_side(seg: Segment, cursor: Tuple[float, float], k: float) -> bool:
    """Could ``seg`` be the corner label of the item the mouse is on? It sits
    above the mouse (at the item's top) and ends right of it (at its right)."""
    x, y = cursor
    return seg.box[3] <= y + 3 * k and seg.box[2] >= x - 3 * k


# -- deciding ----------------------------------------------------------------------------------


@dataclass
class Decision:
    item: Optional[Item]
    score: float = 0.0
    text: str = ""          # what was read that named it
    full: bool = False      # named by a full name (the tooltip), not just a label
    why: str = ""           # for the debug log
    alternatives: List[Tuple[Item, float]] = field(default_factory=list)
    hint: str = ""          # why there's no answer, for the player


class Reader:
    """Names the item under the mouse from the segments read around it."""

    def __init__(self, items: Sequence[Item]) -> None:
        self.index = ItemIndex(items)

    # Evidence: (segment, {item id: (item, similarity)}) for a kind of name.
    def _evidence(self, seg: Segment, kind: str, extra: Sequence[Tuple[str, float]] = ()) -> Dict[str, Tuple[Item, float]]:
        found: Dict[str, Tuple[Item, float]] = {}
        for key, s in list(self.index.lookup(seg.text, kind)) + list(extra):
            for item in self.index.keys(kind)[key]:
                if item.id not in found or found[item.id][1] < s:
                    found[item.id] = (item, s)
        return found

    def _score(self, text: str, item: Item, kind: str) -> float:
        q, key = canon(text), canon(item.name if kind == "full" else item.short_name)
        return fit(q, key)[0] if kind == "full" else similarity(q, key)

    def tooltip_segments(self, segs: Sequence[Segment], cursor, k: float, inside: Optional[Box] = None) -> List[Segment]:
        """Text that may be the tooltip: inside its box when that's known, else
        anything near the mouse. Alone, a piece of text that is word for word
        some item's short name doesn't count when the box isn't known: that's
        a grid label (and an item whose full name is its short name, like
        Toolset, is named by its own label anyway). Also pieces of one line
        joined (OCR splits a tooltip at hyphens and gaps) and a line joined
        with the one below (long names can wrap)."""
        if inside is not None:
            # Mostly inside: a neighbour's label the box only clips isn't the tooltip.
            pool = [s for s in segs if _inside_share(s.box, inside) >= 0.6]
        else:
            pool = [s for s in segs if box_distance(cursor, s.box) <= NEAR * k]
        def may_be_tooltip(s: Segment) -> bool:
            q = canon(s.text)
            if len(q) < 3:
                return False
            # A bare short name is a grid label, unless it's wholly inside the tooltip box.
            return q not in self.index.short or (inside is not None and _inside_share(s.box, inside) >= 0.9)

        out = [s for s in pool if may_be_tooltip(s)]
        # Grid labels side by side aren't pieces of one tooltip: when the box
        # isn't known, text that is word for word a short name isn't joined.
        joinable = pool if inside is not None else [s for s in pool if canon(s.text) not in self.index.short]
        rows: List[List[Segment]] = []
        for seg in sorted(joinable, key=lambda s: ((s.box[1] + s.box[3]) / 2, s.box[0])):
            mid = (seg.box[1] + seg.box[3]) / 2
            row = rows[-1] if rows else None
            if row and abs(mid - (row[-1].box[1] + row[-1].box[3]) / 2) <= 0.5 * max(seg.height, row[-1].height, 1):
                row.append(seg)
            else:
                rows.append([seg])
        for row in rows:
            row.sort(key=lambda s: s.box[0])
            for i in range(len(row)):
                run = [row[i]]
                for nxt in row[i + 1:i + 4]:
                    if nxt.box[0] - run[-1].box[2] > 1.2 * max(nxt.height, run[-1].height, 1):
                        break
                    run.append(nxt)
                    out.append(_join(run))
        by_top = sorted(pool, key=lambda s: (s.box[1], s.box[0]))
        for a, b in zip(by_top, by_top[1:]):
            if 0 <= b.box[1] - a.box[3] <= 1.2 * max(a.height, b.height) and abs(a.box[0] - b.box[0]) < 40 * k:
                out.append(_join([a, b]))
        return out

    def own_label(self, segs: Sequence[Segment], cursor, k: float, exclude: Optional[Box] = None):
        """The item's own corner label: the nearest text above and right of the
        mouse that looks like a short name. (segment, evidence), or None when
        that text doesn't read clearly as one: then it's no use taking the
        next label along, which is some other item's."""
        nearest = None
        usable = [s for s in segs if exclude is None or not _overlaps(s.box, exclude)]
        for seg in usable:
            if not own_label_side(seg, cursor, k) or len(seg.text) > 24:
                continue
            d = box_distance(cursor, seg.box)
            if nearest is not None and d >= nearest[0]:
                continue
            ev = self._evidence(seg, "short")
            if ev and max(s for _, s in ev.values()) >= LABEL_LIKE:  # stack counts and the like don't count
                nearest = (d, seg, ev)
        if nearest is None:
            return None
        _, seg, ev = nearest
        # OCR may have split the label in two ("TT" + "856A1", and TT alone is
        # another item's): try it with the text right after it, keep the better.
        h = max(seg.height, 1)
        after = [s for s in usable if 0 <= s.box[0] - seg.box[2] <= 1.2 * h
                 and abs((s.box[1] + s.box[3]) / 2 - (seg.box[1] + seg.box[3]) / 2) <= 0.5 * h]
        if after:
            joined = _join([seg, min(after, key=lambda s: s.box[0])])
            jev = self._evidence(joined, "short")
            if jev and max(s for _, s in jev.values()) >= max(s for _, s in ev.values()):
                seg, ev = joined, jev
        if max(s for _, s in ev.values()) < LABEL_MIN:
            return None
        return seg, ev

    def decide(self, segs: Sequence[Segment], cursor: Tuple[float, float], k: float = 1.0,
               tooltip_box: Optional[Box] = None, need_tooltip: bool = False) -> Decision:
        """The item under the mouse. ``tooltip_box``: where the tooltip is,
        when hover price check saw it appear. ``need_tooltip``: only answer
        from a full name (hover checks that didn't see the tooltip appear).

        The tooltip decides: its full name is the one thing on screen that
        is only about this item. The item's own label just picks between
        names the tooltip read can't tell apart (a misread 6 or 8), or names
        the item alone when there's no tooltip to read. A label never
        overrules a clear tooltip read: it may be a neighbour's, when the
        item's own is covered or out of view."""
        k = max(0.5, k)
        tips = []
        for seg in self.tooltip_segments(segs, cursor, k, tooltip_box):
            ev = self._evidence(seg, "full")
            if ev:
                tips.append((max(s for _, s in ev.values()), seg, ev))
        # Ties: the text more wholly inside the tooltip box, then the taller
        # text (the tooltip's letters are bigger than grid labels'), then the nearer.
        tips.sort(key=lambda t: (-round(t[0], 3), -(_inside_share(t[1].box, tooltip_box) if tooltip_box else 0),
                                 -round(t[1].height), box_distance(cursor, t[1].box)))
        tip = tips[0] if tips and tips[0][0] >= TOOLTIP_MIN - 0.1 else None
        label = self.own_label(segs, cursor, k, exclude=tooltip_box)
        if tip and tip[0] < TOOLTIP_MIN and label and not need_tooltip:
            # A weak "tooltip" read (often neighbours' labels run together) doesn't
            # outrank a clear label of the item's own, unless they agree.
            mine = {it.id for it, s in label[1].values() if s >= LABEL_MIN}
            top = max(tip[2].values(), key=lambda e: e[1])[0]
            if mine and top.id not in mine:
                tip = None
        why = f"tooltip {tip[1].text!r} ({tip[0]:.2f})" if tip else "no tooltip"
        why += f", label {label[0].text!r}" if label else ", no label"

        def lb(item) -> Optional[float]:
            return self._score(label[0].text, item, "short") if label else None

        if tip:
            best_t = tip[0]
            read = canon(tip[1].text)

            def edits(item, t) -> float:  # how many letters off the read is
                return fit(read, canon(item.name))[1]

            # Every item the tooltip read fits about as well as the best, counted
            # in letters: an exact read of one name isn't "about as good" a read
            # of its one-letter twin (M856A1, M855A1); a garbled digit is.
            scored = [(self._score(tip[1].text, item, "full"), item) for item, _ in tip[2].values()]
            fewest = min(edits(item, t) for t, item in scored)
            close: Dict[str, Tuple[float, Item]] = {}
            for t, item in scored:
                name = canon(item.name)
                if edits(item, t) <= fewest + CLOSE and (name not in close or close[name][0] < t or
                                                         (close[name][0] == t and close[name][1].is_preset)):
                    close[name] = (t, item)
            ranked = sorted(close.values(), key=lambda c: (-c[0], c[1].is_preset))
            full = best_t >= TOOLTIP_MIN
            others = sorted((c for c in scored if canon(c[1].name) not in close), key=lambda c: -c[0])
            alternatives = [(item, round(t, 3)) for t, item in (ranked[1:] + others)[:3]]
            if label and best_t < 0.92:
                # A middling tooltip read against a clear label of an item the
                # read doesn't fit at all: one of them is something else.
                mine = [it for it, s in label[1].values() if s >= LABEL_MIN]
                if mine and all(canon(it.name) not in close and self._score(tip[1].text, it, "full") < 0.6 for it in mine):
                    return Decision(None, best_t, tip[1].text, False, why + ": the tooltip read and the label disagree",
                                    alternatives, "The name and the item's label don't match.")
            if label and full and box_distance(cursor, label[0].box) <= 80 * k:
                # The item's own label, read clearly, names an item whose full name
                # is a letter or two off the tooltip read, and doesn't fit the item
                # the read names at all: OCR misread the tooltip into another
                # name (7.62x54mm R LPS... read as R PS...).
                best_item = ranked[0][1]
                if (lb(best_item) or 0) < 0.75:
                    fixes = [(fit(read, canon(it.name))[1], it) for it, s in label[1].values() if s >= 0.95]
                    fixes = [f for f in fixes if f[0] <= 2.0 and canon(f[1].name) != canon(best_item.name)]
                    if fixes:
                        e, item = min(fixes, key=lambda f: (f[0], f[1].is_preset))
                        t = self._score(tip[1].text, item, "full")
                        return Decision(item, round(min(1.0, t), 3), tip[1].text, True,
                                        why + f": its label corrects the read ({e:.1f} letters off)", alternatives)
            if len(ranked) == 1:
                t, item = ranked[0]
                agree = lb(item)
                score = t + (0.03 if agree is not None and agree >= LABEL_MIN else 0.0)
                if need_tooltip and not full:
                    return Decision(None, t, tip[1].text, False, why + ": no full name", alternatives)
                if full:
                    return Decision(item, round(min(1.0, score), 3), tip[1].text, True, why, alternatives)
                # A weak read: only with the item's own label to back it up.
                if agree is not None and agree >= LABEL_MIN:
                    return Decision(item, round(min(1.0, (t + agree) / 2), 3), label[0].text, False,
                                    why + ": backed by its label", alternatives)
                return Decision(None, t, tip[1].text, False, why + ": too unsure", alternatives)
            # Several names fit the tooltip read about as well: the label picks.
            if label:
                picks = sorted(((lb(item), t, item) for t, item in ranked), key=lambda p: (-p[0], -p[1]))
                (l1, t1, item), l2 = picks[0], picks[1][0]
                if l1 >= LABEL_MIN and l1 - l2 >= 0.1 and (full or not need_tooltip):
                    return Decision(item, round(min(1.0, (t1 + l1) / 2), 3), tip[1].text, full,
                                    why + f": the label picks it from {len(ranked)}", alternatives)
            names = " or ".join(item.name for _, item in ranked[:2])
            return Decision(None, best_t, tip[1].text, full, why + f": {names}?", alternatives, f"Could be {names}.")

        if need_tooltip or not label:
            return Decision(None, why=why + (": no full name" if need_tooltip else ": nothing to go on"))
        # No tooltip: the item's own label alone, when its short name is clear and
        # no one else's. Closeness in letters again: TT 856A1 read exactly isn't
        # about as good a read of TT 855A1; FMJ is just as much every FMJ's.
        said = canon(label[0].text)
        fits: Dict[str, Tuple[float, Item, float]] = {}
        for item, s in label[1].values():
            name = canon(item.name)
            if s >= LABEL_MIN and (name not in fits or fits[name][0] < s):
                fits[name] = (s, item, distance(said, canon(item.short_name)))
        if not fits:
            return Decision(None, why=why + ": too unsure")
        fewest = min(f[2] for f in fits.values())
        ranked = sorted(((s, it) for s, it, d in fits.values() if d <= fewest + CLOSE), key=lambda c: (-c[0], c[1].is_preset))
        s1, item = ranked[0]
        alternatives = [(i, round(s, 3)) for s, i in ranked[1:4]]
        if len(ranked) > 1:
            return Decision(None, s1, label[0].text, False, why + f": {len(ranked)} items have that short name",
                            alternatives, f"{len(ranked)} items are labelled \u201c{label[0].text}\u201d.")
        return Decision(item, round(s1 - 0.04, 3), label[0].text, False, why, alternatives)


def _overlaps(a: Box, b: Box) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _inside_share(a: Box, b: Box) -> float:
    """How much of box ``a`` lies inside box ``b`` (0..1). A box with no size
    (text whose words had no boxes) is wholly inside or not at all."""
    area = (a[2] - a[0]) * (a[3] - a[1])
    if area <= 0:
        return 1.0 if b[0] <= a[0] <= b[2] and b[1] <= a[1] <= b[3] else 0.0
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h / area if w > 0 and h > 0 else 0.0


def _join(parts: Sequence[Segment]) -> Segment:
    return Segment(" ".join(p.text for p in parts), (min(p.box[0] for p in parts), min(p.box[1] for p in parts),
                                                     max(p.box[2] for p in parts), max(p.box[3] for p in parts)))
