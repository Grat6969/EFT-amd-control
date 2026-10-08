import json

from tarkov_display.adl import COLOR_TYPES, ColorRange, Display
from tarkov_display.controller import DisplayController
from tarkov_display.gamma import build_ramp, identity_ramp
from tarkov_display.profiles import Config, Profile, load_config, save_config
from tarkov_display.watcher import GameWatcher

DEFAULTS = {
    "brightness": ColorRange(0, 0, -100, 100, 1),
    "contrast": ColorRange(100, 100, 0, 200, 1),
    "saturation": ColorRange(100, 100, 0, 200, 1),
    "hue": ColorRange(0, 0, -30, 30, 1),
    "temperature": ColorRange(6500, 6500, 4000, 10000, 100),
}


class FakeADL:
    def __init__(self):
        self.disp = Display(0, 0, "Test Monitor", r"\\.\DISPLAY1")
        self.values = {k: r.current for k, r in DEFAULTS.items()}
        self.values["saturation"] = 110  # user's own desktop setting

    def displays(self):
        return [self.disp]

    def get_color(self, d, name):
        r = DEFAULTS[name]
        return ColorRange(self.values[name], r.default, r.minimum, r.maximum, r.step)

    def set_color(self, d, name, value):
        self.values[name] = value


class FakeGamma:
    def __init__(self, accept=True):
        self.ramps = {r"\\.\DISPLAY1": identity_ramp()}
        self.accept = accept

    def displays(self):
        return list(self.ramps)

    def get(self, dev):
        return self.ramps[dev]

    def set(self, dev, ramp):
        if self.accept:
            self.ramps[dev] = ramp
        return self.accept


def test_ramp_identity_and_monotonic():
    ramp = identity_ramp()
    assert ramp[0][0] == 0 and ramp[0][255] == 65535
    assert ramp[0][128] == round(128 / 255 * 65535)
    bright = build_ramp(1.5, brightness=40, contrast=150)
    assert all(b >= a for a, b in zip(bright[0], bright[0][1:]))
    assert build_ramp(1.5)[1][64] > ramp[1][64]  # shadows lifted


def test_clamp_and_step():
    r = ColorRange(6500, 6500, 4000, 10000, 100)
    assert r.clamp(20000) == 10000
    assert r.clamp(6549) == 6500
    assert r.clamp(6551) == 6600


def test_apply_then_restore(tmp_path):
    adl, gamma = FakeADL(), FakeGamma()
    state = tmp_path / "state.json"
    ctl = DisplayController(adl, gamma, state)

    ctl.apply(Profile(brightness=500, contrast=120, saturation=150, gamma=1.3))
    assert adl.values["brightness"] == 100  # clamped
    assert adl.values["saturation"] == 150
    assert adl.values["temperature"] == 6500  # None -> driver default
    assert gamma.ramps[r"\\.\DISPLAY1"] == build_ramp(1.3)
    assert state.exists()

    ctl.apply(Profile(saturation=170))  # switching profiles keeps original snapshot
    ctl.restore()
    assert adl.values["saturation"] == 110
    assert gamma.ramps[r"\\.\DISPLAY1"] == identity_ramp()
    assert not state.exists()


def test_recover_after_crash(tmp_path):
    adl, gamma = FakeADL(), FakeGamma()
    state = tmp_path / "state.json"
    DisplayController(adl, gamma, state).apply(Profile(saturation=180, gamma=1.4))
    assert adl.values["saturation"] == 180

    # New process: nothing in memory, only the state file.
    assert DisplayController(adl, gamma, state).recover()
    assert adl.values["saturation"] == 110
    assert gamma.ramps[r"\\.\DISPLAY1"] == identity_ramp()
    assert not state.exists()


def test_gamma_only_fallback_emulates_brightness(tmp_path):
    gamma = FakeGamma()
    ctl = DisplayController(None, gamma, tmp_path / "s.json")
    ctl.apply(Profile(brightness=20, contrast=110, gamma=1.2))
    assert gamma.ramps[r"\\.\DISPLAY1"] == build_ramp(1.2, 20, 110)


def test_rejected_gamma_does_not_break_colour(tmp_path):
    adl = FakeADL()
    ctl = DisplayController(adl, FakeGamma(accept=False), tmp_path / "s.json")
    ctl.apply(Profile(saturation=140, gamma=2.0))
    assert adl.values["saturation"] == 140


def test_watcher_follows_game_focus(tmp_path):
    adl, gamma = FakeADL(), FakeGamma()
    ctl = DisplayController(adl, gamma, tmp_path / "s.json")
    cfg = Config()
    state = {"running": False, "focused": False}
    w = GameWatcher(ctl, cfg, probe=lambda: (state["running"], state["focused"]))

    w.tick()
    assert ctl.active is None

    state.update(running=True, focused=True)
    w.tick()
    assert adl.values["saturation"] == cfg.profile.saturation

    state["focused"] = False  # alt-tabbed
    w.tick()
    assert adl.values["saturation"] == 110

    cfg.foreground_only = False
    w.refresh()
    w.tick()
    assert adl.values["saturation"] == cfg.profile.saturation

    w.paused = True
    w.refresh()
    w.tick()
    assert ctl.active is None and adl.values["saturation"] == 110

    w.paused = False
    cfg.active_profile = "night"
    w.refresh()
    w.tick()
    assert adl.values["saturation"] == cfg.profiles["night"].saturation

    state["running"] = False
    w.tick()
    assert ctl.active is None and adl.values["saturation"] == 110


def test_config_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    cfg = load_config(path)  # creates defaults
    assert path.exists() and "balanced" in cfg.profiles
    cfg.profiles["mine"] = Profile(saturation=160, gamma=1.25)
    cfg.active_profile = "mine"
    save_config(cfg, path)
    again = load_config(path)
    assert again.profile == Profile(saturation=160, gamma=1.25)

    data = json.loads(path.read_text())
    data["active_profile"] = "missing"
    path.write_text(json.dumps(data))
    assert load_config(path).active_profile in load_config(path).profiles


def test_all_color_types_handled():
    assert set(COLOR_TYPES) == set(DEFAULTS)
