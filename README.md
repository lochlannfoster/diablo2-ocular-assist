# diablo2-ocular-assist

A click-through "which way now" overlay for Diablo II: Resurrected — Linux
(KDE Wayland) and Windows.

**New here?** Read [docs/quickstart.md](docs/quickstart.md). To change or add
rules, [docs/editing-rules.md](docs/editing-rules.md).

It reads the area name the game draws in the top-right corner, looks it up in a
hand-written table, and shows two hints on top of the game:

```
● Flayer Jungle - NIGHTMARE (alvl 50)

WAYPOINT  ·  INSIDE
Three camps are marked by pairs of poles. The waypoint is in the
camp with the Swampy Pit entrance; the Gidbinn and Flayer Dungeon
share another.

NEXT  Lower Kurast  ·  STRAIGHT  (from waypoint)
Keep heading up: the Lower Kurast exit is on the last grid tile
(row 6), where Stormtree stands. A river connects every tile;
follow it.

QUEST  Blade of the Old Religion: Gidbinn

EXP RANGES  (your clvl vs mlvl 50)
100%  45–55     43–81%  42–44 · 56–58     ≤24%  ≤41 · ≥59

SUPERUNIQUE  Stormtree
```

- **Title** — area, difficulty (coloured green / amber / red) and the area
  level for that difficulty; towns show "town".
- **EXP RANGES** — the experience rate you get here, by clvl. D2 pays full
  experience while your level is within 5 of the mlvl (= alvl
  in Nightmare/Hell), then 81 / 62 / 43 / 24 % at 6 / 7 / 8 / 9 apart and 5 %
  from 10 on ([PureDiablo](https://www.purediablo.com/d2wiki/Experience)).
  So 100% = within ±5, 43–81% = 6–8 apart, ≤24% = 9+ apart. (From clvl 25, monsters *above*
  you are penalised more gently, by clvl ÷ mlvl — the bands stay symmetric
  because being 9+ levels under an area is a survival problem anyway.)
- **Q** — quest objectives located in this area (up to two lines).
- **WP** — where the waypoint is, from the entrance.
- **NEXT** — the next area and where its exit is, from the waypoint (or the
  entrance if the area has no waypoint).
- **FARM** — farm-run routes that pass through here (Countess from Black
  Marsh, ...): how to reach the target fast, and what to skip.
- **DROPS** — what can drop at this alvl in the current difficulty: item qlvl
  cap, the act's rune tier, and the Hell 78 / 81 / 85 thresholds for Zod and
  "everything".
- **TURN LEFT / STRAIGHT / TURN RIGHT are relative to how your character
  faces on arriving** — the speedrunners' convention, never compass
  directions. Tips are full sentences and wrap inside the fixed-width box.
- `NO RULE  no accepted rule` (orange) means the sources say the map is random —
  don't look for a pattern.
- Direction words are white; `NO RULE` is orange. The dot colour is source agreement: green = both sources, yellow = one,
  red = inferred. Dim title = the corner isn't readable right now (menu,
  loading); it's showing the last known area.

## It never touches the game

No memory reading, no injection, no hooks. The pipeline is:

1. **Capture** — `capture.py` asks Xwayland for the pixels of the window titled
   "Diablo II: Resurrected" (D2R under Proton is an X client). Just a small
   corner rectangle, ~3 ms.
2. **OCR** — `ocr.py` runs the crop through the `tesseract` CLI and fuzzy-matches
   the result against the closed list of area names in `data/areas.toml`. OCR
   sloppiness ("SPIDER F®REST", "BLack [TTARSH") doesn't matter with ~130 candidates.
3. **Debounce** — `state.py` commits an area only after two agreeing reads.
4. **Draw** — `overlay.py` puts a GTK4 layer-shell window on the compositor's
   overlay layer: always on top (including over exclusive fullscreen on KWin),
   never focused, empty input region so every click goes to the game.

## The settings window

`./overlay.py` (or `d2_on`) opens a normal, clickable **settings window** on the
desktop alongside the overlay. It is the application: the OCR thread, hotkeys,
control socket and overlay all belong to it, and **closing it shuts everything
down** — nothing keeps running in the background.

- **Status** — whether D2R is detected, the recognised area/difficulty, the raw
  OCR text with its match score, and a live picture of the captured region
  (the calibration feedback loop).
- **Overlay** — show / freeze / hotkeys switches; which sections to display;
  monitor, corner, margins, font size, width. Every change applies to the
  overlay immediately.
- **Capture** — the region as fractions of the game window, and the read interval.
  **Select on screen…** grabs a frame of the game and lets you drag a box around
  the clock / area / difficulty text; or nudge x/y/w/h while watching the
  capture picture.
- **Edit mode** (checkbox) — the overlay becomes draggable: drag its body to move
  it (on release it snaps its anchor to the nearest screen corner), drag a yellow
  corner handle to change the width. Unticking restores click-through and saves.
- Changes are written back to `config.toml` automatically (half a second after
  the last edit). "Reload config.toml" pulls in hand edits.

## Windows

A Windows build is produced by GitHub Actions on every push
(`.github/workflows/build.yml`): download `diablo2-ocular-assist-windows.zip` from the
latest run's artifacts (or from a release for `v*` tags), unzip, run
`overlay.exe`. It bundles Python, GTK and tesseract — nothing to install.

Platform differences live in `native/windows.py` (Win32 through `ctypes`):
topmost/click-through window styles, `PIL.ImageGrab` of the game window, and
`RegisterHotKey` for Ctrl+F9–F12. Same settings window, same data, same rules.

- **D2R must be in Windowed or Windowed (Fullscreen) mode.** Nothing can draw
  over, or capture, an exclusive-fullscreen game on Windows.
- The overlay draws on a solid dark background there (no per-pixel alpha).
- `config.toml` is created next to `overlay.exe` on first run.
- `--ctl` is Linux-only; use the settings window.

## Setup

Arch packages only, no pip:

```
sudo pacman -S gtk4 gtk4-layer-shell python-gobject python-cairo python-evdev \
               python-pillow python-xlib tesseract tesseract-data-eng
```

Hotkeys need your user in the `input` group (see Hotkeys). Then:

```
source ~/diablo2-ocular-assist/shell/d2.sh    # put in ~/.bashrc
d2_on          # start (detached, logs to $XDG_RUNTIME_DIR/d2-overlay.log)
d2_off         # stop
d2_status
d2_outputs     # monitor names for config.toml
d2_calibrate   # what the OCR sees right now
```

## Configuration — `config.toml`

```toml
[capture]
display = ":1"       # Xwayland display (echo $DISPLAY)
interval = 1.0       # seconds between reads

[capture.region]     # fractions of the game window; the top-right text block
x = 0.84
y = 0.02
w = 0.155
h = 0.09

[overlay]
output = "DP-1"      # monitor the game is on ("" = compositor default)
anchor = "top-right" # top-left | top-right | bottom-left | bottom-right
margin_x = 12
margin_y = 122        # just under the clock/area/difficulty block
font_size = 15
width = 60           # minimum characters per line (never clips)
hotkeys = true
follow_focus = true  # show the overlay only while the game window is focused
hide_unread = true   # hide it while the area name cannot be read (map off, menus)

[overlay.sections]   # which blocks the overlay shows
waypoint = true
next = true
farm = true
quests = true
exp = true
drops = true
notes = true
uniques = true
```

If the area name isn't being read, run `tools/calibrate.py`: it saves
`debug/frame.png` (whole game window) and `debug/crop.png` (the region) and
prints the raw tesseract output, so you can adjust `[capture.region]` by eye.
`tools/calibrate.py X Y W H` tries a region without editing the config.

## Hotkeys

Wayland can't grab global hotkeys, so `hotkeys.py` reads `/dev/input` via
evdev — only while `D2R.exe` is running, only the chords below are acted on,
nothing is logged or forwarded. Same posture as aoe2-overlay; see the module
docstring.

| Chord | Command | |
|---|---|---|
| Ctrl+F9  | `hide`   | toggle the overlay |
| Ctrl+F10 | `freeze` | stop updating (keep the current hint) |
| Ctrl+F11 | `quit`   | |
| Ctrl+F12 | `flag`   | append the current area to `debug/flagged.log` — "this rule was wrong" |
| —        | `edit`   | toggle edit mode (socket only: `./overlay.py --ctl edit`) |

Every command also works over the control socket: `./overlay.py --ctl hide`, and from the settings window.
`--no-hotkeys` starts with the hotkey switch off.

## The data — `data/areas.toml`

One table per area, keyed by the exact name the game shows:

```toml
[area."Cold Plains"]
act = 1
next = "Stony Field"
has_waypoint = true
to_waypoint = { dir = "near", tip = "Right next to where you come in from Blood Moor, in the corner." }
to_next     = { dir = "edge", tip = "Follow the road. The Stony Field exit is near the middle of an edge; ..." }
confidence = "high"
source = "maxroll, cheatsheet"
levels = [2, 36, 68]          # Normal, Nightmare, Hell
quests = []                   # e.g. ["Search for Cain: Tree of Inifuss"]
uniques = ["Bishibosh"]
notes = []
```

`dir` vocabulary (labels in `areas.py`): `left straight right back` (character-
relative), `corner edge opposite near inside path` (outdoor shape rules),
`fixed`, `random` (no accepted rule), `none`. Tips are sentences; they wrap. The file is validated on load; a bad entry is one clear
error at startup rather than a hint that silently never appears.

### Where the rules come from

Every entry has a `source` field. Two independent write-ups of the speedrun
community's map-reading knowledge, which agree closely:

- [PureDiablo — Area Levels](https://www.purediablo.com/diablo-2/diablo-2-area-levels) for `levels`
- [Maxroll — D2R Map Reading](https://maxroll.gg/d2/resources/map-reading)
- [d2r-speedrun-cheatsheet](https://github.com/minimapletinytools/d2r-speedrun-cheatsheet)
  (derived from Teo-'s general map reading guide on speedrun.com)

Their taxonomy: **static** maps (fixed layouts), **semi-static** maps (fixed
border, rule-bound placement — most outdoor areas), **left/straight/right**
rules for caves and dungeons, and **random** maps with no rule (Catacombs 1 &
3, Arcane Sanctuary, Worldstone Keep 1 & 3, …). A few areas neither source
covers (Cathedral, Pit 1) are marked `low` / `random` rather than guessed.

Act 2 and Act 3 both have areas literally named "Sewers Level 1/2". The TOML
keys are `Kurast Sewers Level 1/2` with `ocr_name = "Sewers Level 1"`, and the
overlay picks the entry matching the act you were last seen in.

Ctrl+F12 logs the current area to `debug/flagged.log` when a rule is wrong in
practice, so fixes can be batched.

## Tests

```
python -m venv --system-site-packages .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest
```

## Gotchas

- `preload.py` re-execs the interpreter with `LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so`.
  Without it every layer-shell call silently no-ops and you get a plain window.
- Grabbing the X *root* window fails under rootless Xwayland (BadMatch); the
  game window is located by title and read directly.
- The Xwayland window is in physical pixels (e.g. 3264×1836 for a 1080p
  monitor at 1.7× scale); the region is stored as fractions so that doesn't matter.
- Only one instance runs at a time (probed via the control socket).

## Layout

```
overlay.py        Session (owns everything), overlay window, reader thread, socket, CLI
native/           OS layer: linux.py (layer-shell, Xlib, evdev) / windows.py (Win32 via ctypes)
overlay.spec      PyInstaller spec for the Windows bundle
.github/workflows/build.yml   tests on Linux + Windows, builds and uploads the zip
settings.py       the settings window (main window; closing it shuts the session down)
config.py         config.toml defaults, load, save
capture.py        Xwayland window grab (Region as fractions)
ocr.py            tesseract + fuzzy match to the area list
areas.py          load/validate data/areas.toml
state.py          Recognizer (debounce, stale, frozen)
hotkeys.py        evdev chords, gated on the game process
preload.py        LD_PRELOAD re-exec
overlay.css       theme
config.toml       capture region, monitor, placement
data/areas.toml   the rules
tools/calibrate.py
shell/d2.sh       d2_on / d2_off / d2_status / d2_outputs / d2_calibrate
test_*.py
```
