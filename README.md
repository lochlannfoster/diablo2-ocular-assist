# diablo2-overlay

A click-through "which way now" overlay for Diablo II: Resurrected on KDE Wayland.

It reads the area name the game draws in the top-right corner, looks it up in a
hand-written table, and shows two hints on top of the game:

```
● Cold Plains
WP    ↔  far edge from Blood Moor
NEXT  Stony Field
      ↺  ¼ turn CCW from WP; Cave/Burial sides
```

- **WP** — where the waypoint tends to be, from the entrance.
- **NEXT** — the next area, and where its exit tends to be, from the waypoint.
- The dot colour is how much to trust the entry: green high, yellow medium, red low.
  Dim title = the corner isn't readable right now (menu, loading), showing the last known area.

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

## Setup

Arch packages only, no pip:

```
sudo pacman -S gtk4 gtk4-layer-shell python-gobject python-cairo python-evdev \
               python-pillow python-xlib tesseract tesseract-data-eng
```

Hotkeys need your user in the `input` group (see Hotkeys). Then:

```
source ~/diablo2-overlay/shell/d2.sh    # put in ~/.bashrc
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
output = "DP-1"      # monitor the game is on
anchor = "top-left"  # top-left | top-right | bottom-left | bottom-right
margin_x = 20
margin_y = 130
font_size = 15
width = 48           # fixed characters per line
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

Every command also works over the control socket: `./overlay.py --ctl hide`.
Run with `--no-hotkeys` to use the socket only.

## The data — `data/areas.toml`

One table per area, keyed by the exact name the game shows:

```toml
[area."Cold Plains"]
act = 1
next = "Stony Field"
has_waypoint = true
to_waypoint = { dir = "opposite", tip = "far edge from Blood Moor" }
to_next     = { dir = "ccw",      tip = "¼ turn CCW from WP; Cave/Burial sides" }
confidence = "medium"
```

`dir` is one of `cw ccw opposite up down left right outer-wall linear dead-end none`
(glyph map in `areas.py`). Tips must fit the fixed-width box — `test_areas.py`
enforces the limit. The file is validated on load; a bad entry is one clear
error at startup rather than a hint that silently never appears.

**These are tendencies, not laws.** D2's map generator is random within
constraints; the entries come from commonly repeated community rules and the
`confidence` field is honest about which ones are solid. Expect to correct
some as you play — Ctrl+F12 logs the current area so you can batch the fixes.

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
overlay.py        GTK layer-shell window, reader thread, control socket, CLI
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
