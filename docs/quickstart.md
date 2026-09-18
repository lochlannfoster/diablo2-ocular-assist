# Quickstart

## Windows (the zip)

1. Download `diablo2-ocular-assist-windows.zip` from the latest
   [release](https://github.com/lochlannfoster/diablo2-ocular-assist/releases).
2. Unzip it anywhere (e.g. `C:\Games\diablo2-ocular-assist\`).
3. In Diablo II: Resurrected, **Options → Video → Window Mode: Windowed** or
   **Windowed (Fullscreen)**. Exclusive fullscreen cannot be captured or drawn
   over — this is a Windows limitation every overlay tool shares.
4. Run `overlay.exe`. Two things appear: a **settings window** on your desktop
   and the **overlay box** in the top-right of the game monitor.
5. Look at the settings window's *Status → Capture* picture. It should show the
   game's clock / area name / difficulty block. If it doesn't (different
   resolution or aspect ratio), click *Capture → Select on screen…*, drag a box
   around that text on the frame it shows, and click *Use this region*. Once
   the picture shows the three lines, the *OCR read* line will show the area
   name and the overlay fills in.
6. Tick **Edit mode** to drag the overlay where you want it; untick to lock it.
7. Closing the settings window quits everything.

Hotkeys while the game is running: `Ctrl+F9` hide/show · `Ctrl+F10` freeze ·
`Ctrl+F11` quit · `Ctrl+F12` flag the current area's rule as wrong.

Settings are saved next to `overlay.exe` in `config.toml`. Everything the
program prints (area reads, capture errors, crashes) goes to `overlay.log` in
the same folder — send that file when reporting a problem.

## Linux (KDE Wayland, D2R under Proton)

```
sudo pacman -S gtk4 gtk4-layer-shell python-gobject python-cairo python-evdev \
               python-pillow python-xlib tesseract tesseract-data-eng
git clone https://github.com/lochlannfoster/diablo2-ocular-assist ~/diablo2-ocular-assist
echo 'source ~/diablo2-ocular-assist/shell/d2.sh' >> ~/.bashrc
```

Then `d2_on` to start, `d2_off` to stop. Exclusive fullscreen works here (KWin
draws layer-shell surfaces over it). Hotkeys need your user in the `input`
group: `sudo usermod -aG input $USER` and log back in.

Other desktops: anything with wlr-layer-shell (Sway, Hyprland, KWin) should
work; GNOME does not implement it.

## What the overlay shows

```
● Flayer Jungle - NIGHTMARE (alvl 50)

WAYPOINT  ·  INSIDE
Three camps are marked by pairs of poles. The waypoint is in the
camp with the Swampy Pit entrance; ...

NEXT  Lower Kurast  ·  STRAIGHT  (from waypoint)
Keep heading up: the Lower Kurast exit is on the last grid tile
(row 6), where Stormtree stands. ...

QUEST  Blade of the Old Religion: Gidbinn

CLVL  45–55 recommended  (42–58 still ok, mlvl 50)

SUPERUNIQUE  Stormtree
```

- **TURN LEFT / STRAIGHT / TURN RIGHT** are relative to the way your character
  faces as you arrive through the entrance (speedrunners' convention).
- **NO RULE** in orange means the map is random; don't look for a pattern.
- The dot colour is how well-sourced the rule is: green = two sources agree,
  yellow = one source, red = inferred.
- Dimmed title = the area name isn't on screen right now (menu, loading); it's
  showing the last known area.
