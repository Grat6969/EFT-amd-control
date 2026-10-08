from tarkov_display.auto import AutoAdjuster, boosted_profile, target_boost
from tarkov_display.controller import DisplayController
from tarkov_display.gamma import build_ramp
from tarkov_display.profiles import AutoConfig, Config, Profile
from tarkov_display.screen import SAMPLE_POINTS, average_samples, box_luminance, sample_boxes
from tarkov_display.watcher import GameWatcher

from test_core import FakeADL, FakeGamma


def test_five_locations_inside_window():
    boxes = sample_boxes((100, 50, 1920, 1080))
    assert len(boxes) == len(SAMPLE_POINTS) == 5
    for x, y, w, h in boxes:
        assert 100 <= x and x + w <= 100 + 1920
        assert 50 <= y and y + h <= 50 + 1080
    cx = boxes[0][0] + boxes[0][2] // 2
    assert cx == 100 + 960


def test_box_luminance():
    white = bytes([255, 255, 255, 0]) * 16
    black = bytes([0, 0, 0, 0]) * 16
    assert abs(box_luminance(white, 16) - 1.0) < 1e-9
    assert box_luminance(black, 16) == 0.0
    green = bytes([0, 255, 0, 0]) * 4
    assert abs(box_luminance(green, 4) - 0.7152) < 1e-9


def test_average_samples():
    assert average_samples([0.1, 0.2, 0.3, 0.4, 0.5]) == 0.3
    assert average_samples([0.0] * 5) is None  # loading screen / exclusive fullscreen
    assert average_samples([]) is None


def test_target_boost_curve():
    auto = AutoConfig(dark_level=0.1, bright_level=0.3)
    assert target_boost(0.05, auto) == 1.0
    assert target_boost(0.5, auto) == 0.0
    assert abs(target_boost(0.2, auto) - 0.5) < 1e-9


def test_boosted_profile():
    auto = AutoConfig(gamma_boost=0.4, brightness_boost=20)
    base = Profile(brightness=10, gamma=1.1)
    assert boosted_profile(base, 0.0, auto) is base
    full = boosted_profile(base, 1.0, auto)
    assert full.gamma == 1.5 and full.brightness == 30
    assert full.saturation == base.saturation


def test_smoothing_ignores_short_flash():
    adj = AutoAdjuster(AutoConfig(response_seconds=1.5))
    for _ in range(40):  # 10 s in a dark room
        adj.update(0.02, 0.25)
    assert adj.applied == 1.0
    adj.update(0.9, 0.25)  # one frame of muzzle flash
    assert adj.applied >= 0.85
    for _ in range(40):  # walk outside
        adj.update(0.5, 0.25)
    assert adj.applied == 0.0


def test_black_frame_holds_boost():
    adj = AutoAdjuster(AutoConfig())
    for _ in range(40):
        adj.update(0.02, 0.25)
    assert adj.update(None, 0.25) is False
    assert adj.applied == 1.0


def test_watcher_boosts_in_dark_room(tmp_path):
    adl, gamma = FakeADL(), FakeGamma()
    ctl = DisplayController(adl, gamma, tmp_path / "s.json")
    cfg = Config()
    cfg.auto.enabled = True
    scene = {"value": 0.5}
    w = GameWatcher(ctl, cfg, probe=lambda: (True, True), sampler=lambda: scene["value"])
    base = cfg.profile

    w.tick(0.25)
    assert gamma.ramps[r"\\.\DISPLAY1"] == build_ramp(base.gamma)

    scene["value"] = 0.02  # walk into a dark room
    for _ in range(40):
        w.tick(0.25)
    assert ctl.active.gamma == round(base.gamma + cfg.auto.gamma_boost, 2)
    assert adl.values["brightness"] == base.brightness + cfg.auto.brightness_boost

    cfg.auto.enabled = False  # Ctrl+Alt+A
    w.tick(0.25)
    assert ctl.active.gamma == base.gamma

    cfg.auto.enabled = True
    w.tick(0.25)
    probe_off = GameWatcher(ctl, cfg, probe=lambda: (False, False), sampler=lambda: 0.02)
    probe_off.tick(0.25)
    assert ctl.active is None and adl.values["saturation"] == 110
