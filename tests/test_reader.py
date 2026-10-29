"""Working out which item the mouse is on from text placed on the screen (reader.py)."""

from types import SimpleNamespace

import pytest

from tarkov_display.ocr import OcrLine
from tarkov_display.reader import Reader, Segment, canon, fit, own_label_side, segments, similarity


def item(id, name, short, preset=False):
    return SimpleNamespace(id=id, name=name, short_name=short, is_preset=preset)


ITEMS = [
    item("gpu", "Graphics card", "GPU"),
    item("toolset", "Toolset", "Toolset"),
    item("bolts", "Bolts", "Bolts"),
    item("k203", "Dorm room 203 key", "203"), item("k206", "Dorm room 206 key", "206"),
    item("k208", "Dorm room 208 key", "208"),
    item("m856", "7.62x25mm TT M856A1", "TT 856A1"), item("m855", "7.62x25mm TT M855A1", "TT 855A1"),
    item("tt", "Tokarev TT-33 7.62x25 TT pistol", "TT"),
    item("ps", "7.62x54mm R PS gzh ammo pack (20 pcs)", "PS"), item("lps", "7.62x54mm R LPS gzh ammo pack (20 pcs)", "LPS"),
    item("fmj545", "5.45x39mm FMJ", "FMJ"), item("fmj556", "5.56x45mm FMJ", "FMJ"),
    item("bala", "Balaclava", "Balaclava"), item("oni", "Balaclava (Red Oni)", "Red Oni"),
    item("m4", "Colt M4A1 5.56x45 assault rifle", "M4A1"),
    item("m4p", "Colt M4A1 5.56x45 assault rifle Default", "M4A1", preset=True),
    item("aks", "AKS-74U dust cover", "AKS-74U DC"), item("aksub", "AKS-74UB dust cover", "AKS-74UB DC"),
]
CURSOR = (1000, 500)
TIP = (1015, 512, 1200, 528)        # the tooltip's text, just below right of the mouse
OWN = (1030, 452, 1056, 462)        # the item's own corner label: above right of the mouse
BELOW = (1004, 540, 1040, 550)      # the item below's label
LEFT = (900, 452, 940, 462)         # the item to the left's
UP_RIGHT_FAR = (1094, 388, 1120, 398)  # the label of the item above right


@pytest.fixture(scope="module")
def reader():
    return Reader(ITEMS)


def seg(text, box):
    return Segment(text, box)


def name(d):
    return d.item.id if d.item else None


def test_canon_and_similarity():
    assert canon("Dorm room 2O6 key") == canon("Dorm room 206 key")       # O for 0
    assert canon("Graphlcs card") == canon("Graphics card")               # l for i
    assert canon("AKS-7IJ") == canon("AKS-7u")                            # U read as IJ
    assert canon("5.45x39mm") == canon("S.45x39mm")
    assert canon("206") != canon("208")                                   # but digits stay digits
    assert similarity(canon("Dorm room 206 key"), canon("Dorm room 208 key")) > 0.95  # 6 and 8 look alike
    assert similarity(canon("M995"), canon("M995")) == 1.0 and similarity("", "abc") == 0.0


def test_fit_counts_letters_left_over():
    exact = fit(canon("Balaclava (Red Oni)"), canon("Balaclava (Red Oni)"))
    part = fit(canon("Balaclava (Red Oni)"), canon("Balaclava"))
    assert exact == (1.0, 0.0) and part[1] > 0.5   # an exact fit is far better than a name inside it
    merged = fit(canon("Graphics card GPU"), canon("Graphics card"))
    assert merged[0] > 0.95                         # a neighbour's label read with the tooltip costs little


def test_segments_split_neighbouring_labels():
    words = [("Bolts", (0, 0, 40, 20)), ("Pliers", (90, 0, 140, 20)),            # far apart: two labels
             ("Graphics", (0, 40, 70, 60)), ("card", (78, 40, 110, 60))]          # one name
    lines = [OcrLine.of_words(words[:2]), OcrLine.of_words(words[2:])]
    out = segments(lines, origin=(100, 200), scale=2)
    assert [s.text for s in out] == ["Bolts", "Pliers", "Graphics card"]
    assert out[0].box == (100, 200, 120, 210)  # back to screen pixels
    assert segments([OcrLine("No boxes", 10, 10)])[0].text == "No boxes"


def test_own_label_side():
    assert own_label_side(seg("x", OWN), CURSOR, 1)
    assert not own_label_side(seg("x", BELOW), CURSOR, 1) and not own_label_side(seg("x", LEFT), CURSOR, 1)


def test_the_tooltip_decides(reader):
    d = reader.decide([seg("Graphics card", TIP), seg("Bolts", BELOW), seg("Toolset", LEFT)], CURSOR)
    assert name(d) == "gpu" and d.full
    d = reader.decide([seg("Graphlcs cad", TIP)], CURSOR)  # misread, still clearly it
    assert name(d) == "gpu" and d.full


def test_a_neighbours_label_never_names_the_item(reader):
    assert reader.decide([seg("Bolts", BELOW)], CURSOR).item is None
    assert reader.decide([seg("Toolset", LEFT)], CURSOR).item is None
    d = reader.decide([seg("Bolts", BELOW), seg("Toolset", LEFT), seg("GPU", OWN)], CURSOR)
    assert name(d) == "gpu" and not d.full


def test_a_label_it_cant_read_hides_the_ones_behind_it(reader):
    # The nearest text above right is the item's own label, misread; the next
    # one along is some other item's: no answer rather than that one.
    d = reader.decide([seg("GPLJX", OWN), seg("Bolts", UP_RIGHT_FAR)], CURSOR)
    assert d.item is None


def test_an_exact_read_is_not_a_tie_with_its_one_letter_twin(reader):
    assert name(reader.decide([seg("7.62x25mm TT M856A1", TIP)], CURSOR)) == "m856"
    assert name(reader.decide([seg("AKS-74U dvst cover", TIP)], CURSOR)) == "aks"
    assert name(reader.decide([seg("Balaclava (Red Oni)", TIP)], CURSOR)) == "oni"


def test_the_label_picks_between_names_the_read_cant_tell_apart(reader):
    d = reader.decide([seg("Dorm room 20 key", TIP)], CURSOR)
    assert d.item is None and "Could be" in d.hint
    d = reader.decide([seg("Dorm room 20 key", TIP), seg("206", OWN), seg("203", BELOW)], CURSOR)
    assert name(d) == "k206" and d.full


def test_the_label_corrects_a_read_that_came_out_as_another_name(reader):
    read = seg("7.62x54mm R PS gzh ammo pack (20 pcs)", TIP)  # the L of LPS lost
    assert name(reader.decide([read], CURSOR)) == "ps"
    assert name(reader.decide([read, seg("LPS", OWN)], CURSOR)) == "lps"
    # A clear read of one item and a label of something unrelated: the read stands.
    assert name(reader.decide([seg("Graphics card", TIP), seg("Bolts", OWN)], CURSOR)) == "gpu"


def test_a_split_label_is_put_back_together(reader):
    d = reader.decide([seg("TT", (1030, 452, 1042, 462)), seg("856A1", (1046, 452, 1070, 462))], CURSOR)
    assert name(d) == "m856"  # not the TT pistol, whose short name is TT


def test_labels_side_by_side_dont_pose_as_a_tooltip(reader):
    # Two neighbours' labels run together can look like a full name.
    segs = [seg("Bolts", (1010, 515, 1040, 525)), seg("Toolset", (1046, 515, 1090, 525))]
    assert reader.decide(segs, CURSOR).item is None


def test_a_weak_tooltip_read_doesnt_outrank_a_clear_label(reader):
    d = reader.decide([seg("AKS-74U gas SPEAR 6.8", TIP), seg("AKS-74U DC", OWN)], CURSOR)
    assert name(d) == "aks"


def test_shared_short_names_and_presets(reader):
    d = reader.decide([seg("FMJ", OWN)], CURSOR)
    assert d.item is None and "2 items are labelled" in d.hint
    assert name(reader.decide([seg("M4A1", OWN)], CURSOR)) == "m4"  # a weapon's label: the weapon, not its presets


def test_known_tooltip_box(reader):
    box = (1008, 506, 1210, 534)
    # Inside a seen tooltip box even a short name counts (an item whose full name is its short name)...
    assert name(reader.decide([seg("Toolset", (1020, 512, 1070, 526))], CURSOR, tooltip_box=box)) == "toolset"
    # ... but not a neighbour's label the box only clips.
    clipped = seg("Bolts", (1004, 500, 1046, 512))
    assert reader.decide([clipped], CURSOR, tooltip_box=box).item is None


def test_need_tooltip(reader):
    assert reader.decide([seg("GPU", OWN)], CURSOR, need_tooltip=True).item is None
    assert name(reader.decide([seg("Graphics card", TIP)], CURSOR, need_tooltip=True)) == "gpu"
