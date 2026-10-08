# Tarkov Display

Switches your AMD Radeon display settings automatically when you play
**Escape from Tarkov**, then puts them back when you leave the game.

- **Saturation**: makes player kits stand out from grass, rocks and concrete.
- **Brightness, contrast and gamma**: let you see into dark corners, interiors and night raids.
- Settings go on while the Tarkov window is focused and come off when you alt-tab
  or close the game, so your desktop, browser and videos look normal.
- In-game hotkeys switch between profiles such as day, night and interiors.
- **Auto-boost in dark areas** (optional): samples the screen at 5 spots and
  raises gamma and brightness when you walk into a dark room, then lowers
  them again outside.

The app changes the same **Display Color** settings found in AMD Software:
Adrenalin Edition, through the AMD Display Library (`atiadlxx.dll`), which
comes with every Radeon driver. Gamma goes through the standard Windows
gamma ramp. It never touches the game process, its files or its memory, so
it works like changing your monitor or driver settings by hand.

## Requirements

- Windows 10 or 11
- AMD Radeon GPU with the Adrenalin driver installed
- Python 3.9+ from [python.org](https://www.python.org/downloads/) (tick "Add python to PATH")
  or a pre-built `TarkovDisplay.exe` (see below)

On NVIDIA or Intel GPUs it still runs but falls back to gamma only:
brightness and contrast are emulated and saturation has no effect.

## Quick start

1. Download or clone this repo.
2. Double-click `run.bat`. The settings window opens.
3. Start Tarkov. When the game window is focused, the status line reads
   `game active - profile 'balanced' applied`.

Leave the window open while you play (minimised is fine). Closing it restores
your normal settings.

### Recommended one-time setup

Windows limits how far gamma can move. To allow the full range, double-click
`enable_full_gamma_range.reg`, accept the prompt and reboot. If you skip this,
higher gamma values (around 1.3 and up) may be refused; the log will say so.

Also in Adrenalin, turn **off** *Vari-Bright* and *Radeon Image Sharpening
(optional)* if they fight with your settings, and make sure no Adrenalin
game profile for Tarkov overrides Display Color.

## Profiles

| Profile     | Brightness | Contrast | Saturation | Gamma | Use for |
|-------------|-----------:|---------:|-----------:|------:|---------|
| `balanced`  | 10 | 110 | 135 | 1.15 | Default, most maps |
| `day`       | 5  | 112 | 140 | 1.05 | Bright daytime: Woods, Shoreline, Lighthouse |
| `interiors` | 15 | 115 | 135 | 1.30 | Labs, Interchange, Reserve bunkers, Factory |
| `night`     | 25 | 105 | 125 | 1.50 | Night raids |

Brightness, contrast and saturation use Adrenalin's units: brightness runs
-100 to 100 with a default of 0, and contrast and saturation run 0 to 200
with a default of 100. Gamma 1.0 is normal, and higher values brighten
shadows.

Tune any profile with the sliders, or tick **Preview on desktop now** to see
changes without the game running. **New** copies the current profile under a
new name.

Profiles are saved to `%APPDATA%\TarkovDisplay\config.json`, which you can
also edit by hand. In that file, `"hue"` and `"temperature"` (Kelvin) can be
set to a number, or to `null` to keep the driver default.

## Auto-boost in dark areas

Tick **Auto-boost in dark areas** in the settings window, or press
`Ctrl+Alt+A` in game.

Four times a second it reads 5 small patches of the Tarkov window: the
centre, plus upper-left, upper-right, lower-left and lower-right of centre.
It averages each patch, then averages the five into a single scene
brightness:

- Below **"Counts as fully dark"** (8% by default), the full boost is added
  on top of your current profile: +0.40 gamma and +15 brightness.
- Above **"Counts as bright"** (30%), there is no boost.
- In between, the boost scales smoothly.

Changes are eased in over the **Reaction time** (1.5 s), so a muzzle flash,
flashlight or a glance at the sky doesn't make the screen pump. A pure black
frame, such as a loading screen, holds the current boost instead of maxing
it out. The screen capture sees the game's own image, before your boost is
applied, so the boost doesn't feed back into the reading.

The settings window shows the live scene brightness and boost next to the
checkbox. To check what it sees, run `python -m tarkov_display scene` and
alt-tab into the game. It prints the 5 readings and their average.

**Run Tarkov in Borderless (windowed) mode.** In exclusive Fullscreen,
Windows usually returns black screenshots, so auto-boost will stay where it
is.

Note: auto-boost reads the screen (like OBS or Discord screen share) and
changes display settings in response. It never touches the game itself, but
as with any screen-reading tool you use it at your own risk with BattlEye.
Everything else in this app only changes driver and display settings.

## Hotkeys (work in game)

| Keys | Action |
|------|--------|
| `Ctrl+Alt+1` … `Ctrl+Alt+9` | Switch to profile 1–9 (order shown in the dropdown) |
| `Ctrl+Alt+0` | Turn the overlay off or on |
| `Ctrl+Alt+A` | Turn auto-boost in dark areas off or on |

With the built-in profiles: `1` = balanced, `2` = day, `3` = interiors, `4` = night.

## Command line

```
python -m tarkov_display              # settings window (default)
python -m tarkov_display watch        # no window, just run in the console
python -m tarkov_display watch --profile night --always
python -m tarkov_display displays     # show detected AMD displays and current values
python -m tarkov_display scene        # live auto-boost readings from the 5 sample spots
python -m tarkov_display list         # list profiles
python -m tarkov_display apply day    # apply now and leave it on
python -m tarkov_display restore      # undo 'apply'
```

`--always` keeps the profile on whenever the game is running, even when
alt-tabbed.

## Building a standalone .exe

Run `build_exe.bat`. It installs PyInstaller and writes
`dist\TarkovDisplay.exe`, which you can pin to the taskbar or add to
startup with `Win+R` → `shell:startup`.

## Safety

- Before the first change, your current settings are saved to
  `%APPDATA%\TarkovDisplay\original_settings.json`. If the app crashes or the
  PC loses power while a profile is on, they are restored the next time you
  start the app (or run `python -m tarkov_display restore`).
- If something looks wrong, open Adrenalin → Display → Display Color → Reset.
- Log file: `%APPDATA%\TarkovDisplay\tarkov_display.log`.

## Development

```
pip install pytest
python -m pytest
```

The tests use fake driver backends, so they run on any OS.
