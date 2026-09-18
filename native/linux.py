"""Linux backend: KDE/KWin on Wayland, D2R under Proton (an Xwayland client).

- Overlay window: gtk4-layer-shell on the OVERLAY layer, positioned by
  anchors + margins in logical pixels; click-through via an empty input region.
- Capture: XGetImage of the game window through Xwayland (capture.py).
- Hotkeys: evdev, read only while the game runs (hotkeys.py).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HAS_CONTROL_SOCKET = True


def init():
    import preload
    preload.ensure()  # must run before gi pulls in libwayland


def _layer_shell():
    import gi
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell as LayerShell
    return LayerShell


def prepare_window(win):
    LayerShell = _layer_shell()
    LayerShell.init_for_window(win)
    # OVERLAY is the topmost layer -- above normal and fullscreen windows.
    LayerShell.set_layer(win, LayerShell.Layer.OVERLAY)
    LayerShell.set_keyboard_mode(win, LayerShell.KeyboardMode.NONE)


def on_realize(win, overlay):
    set_click_through(win, True)
    # In edit mode the input region is the whole surface; re-apply it whenever
    # the surface changes size.
    surface = win.get_native().get_surface()
    surface.connect("layout", lambda *_: set_click_through(win, not overlay.editing))


def set_placement(win, anchor, margin_x, margin_y):
    LayerShell = _layer_shell()
    anchor = str(anchor).lower()
    top = not anchor.startswith("bottom")
    right = anchor.endswith("right")
    for edge, on, margin in (
        (LayerShell.Edge.TOP, top, margin_y),
        (LayerShell.Edge.BOTTOM, not top, margin_y),
        (LayerShell.Edge.LEFT, not right, margin_x),
        (LayerShell.Edge.RIGHT, right, margin_x),
    ):
        LayerShell.set_anchor(win, edge, on)
        LayerShell.set_margin(win, edge, margin if on else 0)


def set_monitor(win, output):
    if not output:
        return
    LayerShell = _layer_shell()
    from gi.repository import Gdk

    monitor, error = find_monitor(output)
    if monitor is None:
        print(f"warning: {error}", file=sys.stderr)
        return
    # A layer surface's output is fixed while mapped: unmap, move, remap.
    visible = win.get_visible()
    win.set_visible(False)
    LayerShell.set_monitor(win, monitor)
    if visible:
        win.present()


def monitor_size(win):
    LayerShell = _layer_shell()
    monitor = LayerShell.get_monitor(win)
    if monitor is None:
        native = win.get_native()
        surface = native.get_surface() if native else None
        if surface is not None:
            monitor = win.get_display().get_monitor_at_surface(surface)
    if monitor is None:
        return None
    geometry = monitor.get_geometry()
    return geometry.width, geometry.height


def set_click_through(win, enabled: bool):
    """Empty input region = the compositor routes every pointer event to
    whatever is underneath. This is the whole click-through mechanism."""
    import cairo

    native = win.get_native()
    surface = native.get_surface() if native else None
    if surface is None:
        return
    if enabled:
        surface.set_input_region(cairo.Region())
    else:
        rect = cairo.RectangleInt(0, 0, win.get_width(), win.get_height())
        surface.set_input_region(cairo.Region(rect))


def set_opacity(win, alpha: float):
    """The scrim alpha is in the CSS on Wayland; nothing to do."""


def list_monitors():
    """Every connected output, as (connector, model, geometry-string)."""
    from gi.repository import Gdk

    display = Gdk.Display.get_default()
    if display is None:
        return []
    monitors = display.get_monitors()
    found = []
    for i in range(monitors.get_n_items()):
        monitor = monitors.get_item(i)
        geometry = monitor.get_geometry()
        found.append((
            monitor.get_connector() or f"output-{i}",
            monitor.get_model() or "",
            f"{geometry.width}x{geometry.height}+{geometry.x}+{geometry.y}",
        ))
    return found


def find_monitor(name: str):
    """Match an output by connector or model, case-insensitively."""
    from gi.repository import Gdk

    display = Gdk.Display.get_default()
    if display is None:
        return None, "no display"
    monitors = display.get_monitors()
    wanted = name.strip().lower()
    for i in range(monitors.get_n_items()):
        monitor = monitors.get_item(i)
        connector = (monitor.get_connector() or "").lower()
        model = (monitor.get_model() or "").lower()
        if wanted in (connector, model) or (wanted and wanted in model):
            return monitor, ""
    available = ", ".join(c for c, _, _ in list_monitors()) or "(none)"
    return None, f"no output matching {name!r}; available: {available}"


def capture_backend(cap: dict):
    import capture
    return capture.XwaylandCapture(display_name=cap.get("display"))


def hotkey_bridge(on_command):
    from gi.repository import GLib
    import hotkeys

    class HotkeyBridge:
        """Runs the evdev hotkey listener on the GLib main loop."""

        POLL_SECONDS = 2

        def __init__(self):
            self.listener = hotkeys.Listener(
                on_command=on_command, attach=self._attach, detach=self._detach
            )
            self._timer = None

        def _attach(self, fd, callback):
            channel = GLib.IOChannel.unix_new(fd)
            return GLib.io_add_watch(
                channel, GLib.PRIORITY_DEFAULT, GLib.IOCondition.IN,
                lambda *_: callback(fd) or GLib.SOURCE_REMOVE,
            )

        def _detach(self, source):
            GLib.source_remove(source)

        def start(self):
            if self._timer is not None:
                return True
            ok, reason = hotkeys.available()
            if not ok:
                print(f"hotkeys disabled: {reason}", file=sys.stderr)
                return False
            self.listener.poll_game()
            self._timer = GLib.timeout_add_seconds(self.POLL_SECONDS, self._poll)
            print("hotkeys: armed — devices open only while D2R is running", flush=True)
            return True

        def _poll(self):
            self.listener.poll_game()
            return GLib.SOURCE_CONTINUE

        def stop(self):
            if self._timer is not None:
                GLib.source_remove(self._timer)
                self._timer = None
            if self.listener.open:
                self.listener.close_devices()

    return HotkeyBridge()


def tray_icon(on_command, overlay_hidden: bool):
    """StatusNotifierItem over DBus (native/sni.py); None if there is no host."""
    from gi.repository import GLib
    from . import sni

    try:
        tray = sni.SniTray(on_command, overlay_hidden)
    except (sni.TrayUnavailable, GLib.Error) as exc:
        print(f"tray: unavailable ({exc}); closing the settings window quits", flush=True)
        return None
    print("tray: icon registered (left click: settings, right click: menu)", flush=True)
    return tray


def game_is_running() -> bool:
    import hotkeys
    return hotkeys.game_is_running()


def tesseract_command() -> list[str]:
    return [os.environ.get("D2_TESSERACT", "tesseract")]


def config_dir() -> Path:
    return Path(__file__).resolve().parent.parent
