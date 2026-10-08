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
- **Flea market prices**: look up any item by name, or hover over an item in
  game and press `Ctrl+Alt+P` to see its flea price, best trader, price per
  slot, and whether it's needed for quests or the hideout.

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
2. Double-click `install.bat` once. It installs the Windows text-recognition
   packages used by the price check.
3. Double-click `run.bat`. The settings window opens.
4. Start Tarkov. When the game window is focused, the status line reads
   `game active - profile 'balanced' applied`.

Leave the window open while you play (minimised is fine). Closing it restores
your normal settings.

### Updating

Close the app, then double-click `update.bat`. It downloads the latest
version from GitHub and replaces the code in this folder. Your profiles and
settings are kept, because they are stored separately in
`%APPDATA%\TarkovDisplay`. Any other files you put in this folder are left
alone too.

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

## Flea market prices

Prices come from [tarkov.dev](https://tarkov.dev), a free community API, and
update every 10 minutes while the app is open. A copy is saved, so the last
prices still work offline. They are shown before flea market fees.

### Prices tab

Type part of a name, such as `ledx`, `gpu` or `salewa`. Each row shows:

- the flea price (24-hour average) and the lowest listing right now
- the best trader to sell to, and what they pay
- the price per inventory slot
- what hideout upgrades and quests it's needed for

Click a column heading to sort by it, and double-click a row to open the
item on tarkov.dev.

### Price check in game: Ctrl+Alt+P

Hover over an item in your stash or a container until Tarkov shows its name,
then press `Ctrl+Alt+P`. A small popup appears next to the cursor with the
prices. It doesn't take focus, so the game keeps your mouse and keyboard, and
it closes by itself after 8 seconds.

How it works: when you press the hotkey (and only then), it takes one
screenshot of the area around the cursor. Windows' built-in OCR reads the
text in it, and the result is matched against the tarkov.dev item list. The
match allows for small misreads and short names. Nothing touches the game's
memory, files or process. The popup is a normal window of this app, not
drawn into the game.

If it misreads items:

- Run `python -m tarkov_display scan --debug`, hover over items in game and
  watch what it reads. Each capture is saved as an image plus text in
  `%APPDATA%\TarkovDisplay\scans`, so you can see exactly what it saw.
- Adjust the capture area around the cursor in `config.json` under `"scan"`
  (`left`, `right`, `up`, `down`, in pixels at 1080p).
- Windows OCR needs the English language installed (Settings → Time &
  language → Language). If the winrt packages won't install, installing
  [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) works as a
  fallback.

For PvE flea prices, set `"game_mode": "pve"` in `config.json`.

## Hotkeys (work in game)

| Keys | Action |
|------|--------|
| `Ctrl+Alt+1` … `Ctrl+Alt+9` | Switch to profile 1–9 (order shown in the dropdown) |
| `Ctrl+Alt+0` | Turn the overlay off or on |
| `Ctrl+Alt+A` | Turn auto-boost in dark areas off or on |
| `Ctrl+Alt+P` | Price-check the item under the mouse |

With the built-in profiles: `1` = balanced, `2` = day, `3` = interiors, `4` = night.

## Command line

```
python -m tarkov_display              # settings window (default)
python -m tarkov_display watch        # no window, just run in the console
python -m tarkov_display watch --profile night --always
python -m tarkov_display displays     # show detected AMD displays and current values
python -m tarkov_display scene        # live auto-boost readings from the 5 sample spots
python -m tarkov_display price ledx   # flea/trader prices by name
python -m tarkov_display scan --debug # price-check under the mouse every 3 s (for testing)
python -m tarkov_display list         # list profiles
python -m tarkov_display apply day    # apply now and leave it on
python -m tarkov_display restore      # undo 'apply'
```

`--always` keeps the profile on whenever the game is running, even when
alt-tabbed.

## Building a standalone .exe

Run `build_exe.bat`. It installs PyInstaller and the OCR packages, and writes
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
