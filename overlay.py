#!/usr/bin/env python3
"""diablo2-overlay — a click-through "which way now" overlay for Diablo II: Resurrected.

Reads the area name the game draws in the top-right corner (a screen grab of
the game window through Xwayland, nothing loaded into the game), looks it up
in data/areas.toml, and shows two hints on top of the game: where the
waypoint tends to be, and where the exit to the next area tends to be from
the waypoint.

The overlay sits on the compositor's overlay layer, never takes focus and has
an empty input region, so every click goes straight to the game. It is driven
from a normal settings window (settings.py): the window owns the OCR reader,
the hotkeys and the control socket, and closing it shuts everything down.

    ./overlay.py                  # run (opens the settings window + overlay)
    ./overlay.py --ctl hide       # toggle visibility of a running overlay
    ./overlay.py --list-outputs   # which monitor names exist
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
from pathlib import Path

import preload

preload.ensure()  # must run before gi pulls in libwayland

import cairo  # noqa: E402
import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import (  # noqa: E402
    Gdk,
    Pango,
    GLib,
    GLibUnix,
    Gtk,
    Gtk4LayerShell as LayerShell,
)

import areas  # noqa: E402
import capture  # noqa: E402
import config as configmod  # noqa: E402
import hotkeys  # noqa: E402
import ocr  # noqa: E402
from state import Recognizer  # noqa: E402

HERE = Path(__file__).parent
CSS_PATH = HERE / "overlay.css"
CONFIG_PATH = configmod.CONFIG_PATH
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
SOCKET_PATH = RUNTIME / "d2-overlay.sock"
FLAG_LOG = HERE / "debug" / "flagged.log"

COMMANDS = ("hide", "freeze", "quit", "flag")

DIFFICULTY_COLOURS = {"normal": "#9be59b", "nightmare": "#ffd166", "hell": "#ff5f5f"}
GOOD, AVG, BAD = "#00ff9c", "#ffd166", "#ff5f5f"
NORULE = "#ff9f5f"


def esc(text: str) -> str:
    return GLib.markup_escape_text(text)


def direction(hint) -> str:
    """The direction word, coloured: orange for 'no rule', white otherwise."""
    colour = NORULE if hint.no_rule else "#ffffff"
    return f'<span foreground="{colour}" weight="bold">{esc(hint.label)}</span>'


def band(rate: str, levels: str, colour: str) -> str:
    """'100%  45–55': the XP rate, then the character levels that get it."""
    return f'<span foreground="{colour}" weight="bold">{rate}</span>  {levels}'


def rng(pair) -> str:
    low, high = pair
    return f"{low}" if low == high else f"{low}–{high}"


class Reader(threading.Thread):
    """Capture + OCR loop, off the GTK thread.

    Tesseract takes a few hundred milliseconds; doing that on the main loop
    would stall rendering. Results are handed back with GLib.idle_add, so the
    Recognizer and the widgets are only ever touched from the GTK thread.
    """

    def __init__(self, config, names, on_reading, on_error, on_frame=None):
        super().__init__(daemon=True)
        cap = config["capture"]
        # `interval` and `region` may be reassigned from the GTK thread while
        # the loop runs; each iteration reads them once, which is enough.
        self.interval = float(cap.get("interval", 1.0))
        self.region = capture.Region(**cap["region"])
        self.backend = capture.make(cap.get("backend", "xwayland"),
                                    display_name=cap.get("display"))
        self.names = names
        self.on_reading = on_reading
        self.on_error = on_error
        self.on_frame = on_frame
        self.stop_event = threading.Event()

    def run(self):
        while not self.stop_event.is_set():
            started = time.monotonic()
            try:
                image = self.backend.grab(self.region)
                if self.on_frame is not None:
                    GLib.idle_add(self.on_frame, image)
                reading = ocr.read_area(image, self.names)
                GLib.idle_add(self.on_reading, reading)
            except capture.CaptureError as exc:
                # The game is not up (yet); report and keep polling.
                GLib.idle_add(self.on_error, str(exc))
            except Exception as exc:  # noqa: BLE001 - keep the loop alive
                GLib.idle_add(self.on_error, f"{type(exc).__name__}: {exc}")
            elapsed = time.monotonic() - started
            self.stop_event.wait(max(0.1, self.interval - elapsed))

    def stop(self):
        self.stop_event.set()


class Overlay:
    """The click-through window. Pure display: state lives in the Session."""

    def __init__(self, app, session):
        self.session = session
        ov = session.config["overlay"]
        self.rules = session.rules
        self.font_size = int(ov["font_size"])
        self.width = int(ov["width"])
        self.last_act = None  # disambiguates names shared between acts
        self._last_render = None
        self._sizing_provider = None
        self._labels = []

        self.win = Gtk.ApplicationWindow(application=app)
        self._init_layer_shell(ov["anchor"], int(ov["margin_x"]), int(ov["margin_y"]),
                               ov["output"])

        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.root.add_css_class("root")
        self.win.set_child(self.root)

        self.title_label = self._label("title", wrap=False)
        self.wp_head_label = self._label("head", "wp", wrap=False)
        self.wp_label = self._label("hint", "wp")
        self.next_head_label = self._label("head", "next", wrap=False)
        self.next_tip_label = self._label("hint", "next")
        self.quest_labels = [self._label("hint", "quest"), self._label("hint", "quest")]
        self.exp_head_label = self._label("head", "exp", wrap=False)
        self.exp_label = self._label("hint", "exp")
        self.notes_label = self._label("hint", "notes")
        self.uniques_label = self._label("hint", "uniques")
        self.next_label = self.next_head_label
        # Gaps between sections.
        for label in (self.wp_head_label, self.next_head_label, self.quest_labels[0],
                      self.exp_head_label, self.notes_label, self.uniques_label):
            label.set_margin_top(10)

        self._load_css()
        self.win.connect("realize", self._clear_input_region)
        self.win.present()
        self.render()

    def _label(self, *classes, wrap=True):
        # width_chars is a *minimum*: GTK estimates it from the font's
        # approximate character width, which undershoots Hack's real advance
        # and clipped the ends of lines when it was also the maximum.
        label = Gtk.Label(xalign=0)
        label.set_width_chars(self.width)
        label.set_ellipsize(Pango.EllipsizeMode.NONE)
        label.set_margin_end(12)
        label.set_use_markup(True)
        if wrap:
            # Long tips wrap onto further lines inside the fixed width rather
            # than being cut; the box grows in height only.
            label.set_max_width_chars(self.width)
            label.set_wrap(True)
            label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        else:
            # Single-line headers take their natural width: the bigger, bold
            # title was being squeezed into a width estimated for body text.
            label.set_wrap(False)
        for cls in classes:
            label.add_css_class(cls)
        self.root.append(label)
        self._labels.append(label)
        return label

    def _init_layer_shell(self, anchor, margin_x, margin_y, output=""):
        # init_for_window must happen before the window is realized; the rest
        # can be changed at any time (see the set_* methods below).
        LayerShell.init_for_window(self.win)
        # OVERLAY is the topmost layer -- above normal and fullscreen windows.
        LayerShell.set_layer(self.win, LayerShell.Layer.OVERLAY)
        LayerShell.set_keyboard_mode(self.win, LayerShell.KeyboardMode.NONE)
        self._apply_monitor(output)
        self._apply_anchor(anchor, margin_x, margin_y)

    def _apply_monitor(self, output):
        if not output:
            return
        monitor, error = find_monitor(output)
        if monitor is not None:
            LayerShell.set_monitor(self.win, monitor)
        else:
            print(f"warning: {error}", file=sys.stderr)

    def _apply_anchor(self, anchor, margin_x, margin_y):
        anchor = str(anchor).lower()
        top = not anchor.startswith("bottom")
        right = anchor.endswith("right")
        for edge, on, margin in (
            (LayerShell.Edge.TOP, top, margin_y),
            (LayerShell.Edge.BOTTOM, not top, margin_y),
            (LayerShell.Edge.LEFT, not right, margin_x),
            (LayerShell.Edge.RIGHT, right, margin_x),
        ):
            LayerShell.set_anchor(self.win, edge, on)
            LayerShell.set_margin(self.win, edge, margin if on else 0)

    # -- live settings (called by the settings window) --------------------

    def set_placement(self, anchor, margin_x, margin_y):
        self._apply_anchor(anchor, margin_x, margin_y)

    def set_monitor(self, output):
        # A layer surface's output is fixed while mapped: unmap, move, remap.
        visible = self.win.get_visible()
        self.win.set_visible(False)
        self._apply_monitor(output)
        if visible:
            self.win.present()

    def set_font_size(self, size: int):
        self.font_size = int(size)
        self._load_sizing_css()

    def set_width(self, width: int):
        self.width = int(width)
        for label in self._labels:
            label.set_width_chars(self.width)
            if label.get_wrap():
                label.set_max_width_chars(self.width)

    def set_visible(self, visible: bool):
        self.win.set_visible(visible)

    def refresh(self):
        """Force a redraw (sections toggled, freeze, etc.)."""
        self._last_render = None
        self.render()

    def _clear_input_region(self, widget):
        """Empty input region = the compositor routes every pointer event to
        whatever is underneath. This is the whole click-through mechanism."""
        surface = widget.get_native().get_surface()
        surface.set_input_region(cairo.Region())

    def _load_css(self):
        display = self.win.get_display()
        provider = Gtk.CssProvider()
        try:
            provider.load_from_path(str(CSS_PATH))
        except GLib.Error as exc:
            print(f"warning: could not load {CSS_PATH}: {exc}", file=sys.stderr)
            return
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self._load_sizing_css()

    def _load_sizing_css(self):
        # The overlay's own CSS lives in overlay.css; only the size is code,
        # so it is a separate provider that can be swapped at runtime. Scoped
        # to .root so the settings window keeps the system theme's sizes.
        display = self.win.get_display()
        if self._sizing_provider is not None:
            Gtk.StyleContext.remove_provider_for_display(display, self._sizing_provider)
        sizing = Gtk.CssProvider()
        sizing.load_from_data(
            f".root label {{ font-size: {self.font_size}px; }}"
            f".root .title {{ font-size: {self.font_size + 1}px; }}".encode()
        )
        Gtk.StyleContext.add_provider_for_display(
            display, sizing, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
        )
        self._sizing_provider = sizing

    # -- rendering ---------------------------------------------------------

    def render(self):
        rec = self.session.recognizer
        sections = self.session.config["overlay"]["sections"]
        error = self.session.error
        state = (rec.area, rec.difficulty, rec.visible, rec.frozen, error,
                 tuple(sorted(sections.items())))
        if state == self._last_render:
            return
        self._last_render = state

        for label in (self.title_label, self.wp_head_label, self.wp_label,
                      self.next_head_label, self.next_tip_label, *self.quest_labels,
                      self.exp_head_label, self.exp_label, self.notes_label,
                      self.uniques_label):
            for cls in ("stale", "frozen", "error"):
                label.remove_css_class(cls)
            label.set_visible(True)

        if rec.area is None:
            if error:
                self.title_label.set_text("waiting for game")
                self.title_label.add_css_class("stale")
                self.wp_label.set_text(error)
                self.wp_label.add_css_class("error")
            else:
                self.title_label.set_text("reading…")
                self.title_label.add_css_class("stale")
                self.wp_label.set_text("area name must be on screen")
            for label in (self.wp_head_label, self.next_label, self.next_tip_label,
                          *self.quest_labels, self.exp_head_label, self.exp_label,
                          self.notes_label, self.uniques_label):
                label.set_visible(False)
            return

        area = areas.resolve(self.rules, rec.area, self.last_act)
        self.last_act = area.act
        dot = {"high": "●", "medium": "●", "low": "○"}[area.confidence]
        level = area.level(rec.difficulty)
        if rec.difficulty:
            diff = f'<span foreground="{DIFFICULTY_COLOURS[rec.difficulty]}">' \
                   f'{rec.difficulty.upper()}</span>'
        else:
            diff = "difficulty ?"
        detail = f"arealvl {level}" if level else ("town" if not area.levels[0] else "arealvl ?")
        frozen = "  (frozen)" if rec.frozen else ""
        self.title_label.set_markup(
            f"{dot} {esc(area.name)} - {diff} ({detail}){esc(frozen)}")
        for cls in ("conf-high", "conf-medium", "conf-low"):
            self.title_label.remove_css_class(cls)
        self.title_label.add_css_class(f"conf-{area.confidence}")
        if rec.frozen:
            self.title_label.add_css_class("frozen")
        elif not rec.visible:
            self.title_label.add_css_class("stale")

        wp = area.to_waypoint
        if area.has_waypoint:
            self.wp_head_label.set_markup(f"WAYPOINT  ·  {direction(wp)}")
            self.wp_label.set_text(esc(wp.tip))
        else:
            self.wp_head_label.set_markup("WAYPOINT  ·  <span foreground=\"#8a9a94\">none</span>")
            self.wp_label.set_text("No waypoint in this area.")
        (self.wp_label.add_css_class if wp.no_rule else self.wp_label.remove_css_class)("norule")

        nx = area.to_next
        origin = "from waypoint" if area.has_waypoint else "from entrance"
        self.next_head_label.set_markup(
            f"NEXT  {esc(area.next or 'end of the line')}  ·  {direction(nx)}"
            f"  <span foreground=\"#8a9a94\">({origin})</span>")
        self.next_tip_label.set_text(esc(nx.tip))
        (self.next_tip_label.add_css_class if nx.no_rule
         else self.next_tip_label.remove_css_class)("norule")

        # One quest per line; unused lines are hidden so the box stays tight.
        for label, quest in zip(self.quest_labels, list(area.quests) + ["", ""]):
            label.set_visible(bool(quest))
            if quest:
                label.set_markup(f"QUEST  {esc(quest)}")

        if level:
            b = areas.exp_bands(level)
            self.exp_head_label.set_markup(
                f"EXP RANGES  <span foreground=\"#8a9a94\">(your clvl vs monster lvl {level})</span>")
            self.exp_label.set_markup(
                f"{band('100%', rng(b['good']), GOOD)}     "
                f"{band('43–81%', rng(b['avg_low']) + ' · ' + rng(b['avg_high']), AVG)}     "
                f"{band('≤24%', f'≤{b['bad_low'][1]} · ≥{b['bad_high'][0]}', BAD)}")
        else:
            self.exp_head_label.set_visible(False)
            self.exp_label.set_visible(False)

        notes = list(area.notes)
        if area.levels[2] >= 85:
            notes.insert(0, f"Hell area level {area.levels[2]}: every item in the game can drop here.")
        self.notes_label.set_visible(bool(notes))
        if notes:
            self.notes_label.set_markup("NOTE  " + esc("  ·  ".join(notes)))

        self.uniques_label.set_visible(bool(area.uniques))
        if area.uniques:
            names = "  ·  ".join(esc(n) for n in area.uniques)
            self.uniques_label.set_markup(
                f"SUPERUNIQUE  <span foreground=\"#d4a24c\" weight=\"bold\">{names}</span>")

        # Sections the user switched off in the settings window.
        for key, labels in (
            ("waypoint", (self.wp_head_label, self.wp_label)),
            ("next", (self.next_head_label, self.next_tip_label)),
            ("quests", self.quest_labels),
            ("exp", (self.exp_head_label, self.exp_label)),
            ("notes", (self.notes_label,)),
            ("uniques", (self.uniques_label,)),
        ):
            if not sections.get(key, True):
                for label in labels:
                    label.set_visible(False)

class Session:
    """Everything that runs: config, rules, recogniser, overlay window, OCR
    reader, control socket, hotkeys. Created by the settings window and torn
    down by `shutdown()` when it closes -- nothing outlives the window.
    """

    def __init__(self, app, config, rules):
        self.app = app
        self.config = config
        self.rules = rules
        self.recognizer = Recognizer()
        self.error = None
        self.last_reading = None
        self.last_frame = None
        self.hidden = False
        self.on_update = None   # settings window hook: called after each reading
        self._closed = False

        self.overlay = Overlay(app, self)
        self.server = ControlServer(SOCKET_PATH, self.handle)
        self.reader = Reader(config, areas.screen_names(rules),
                             self.on_reading, self.on_error, self.on_frame)
        self.reader.start()
        self.bridge = HotkeyBridge(self.handle)
        if config["overlay"].get("hotkeys", True):
            self.bridge.start()
        print(f"overlay running: {len(rules)} areas loaded", flush=True)
        print(f"control socket: {SOCKET_PATH}", flush=True)

    # -- from the reader thread (delivered on the GTK thread) -------------

    def on_frame(self, image):
        self.last_frame = image
        return GLib.SOURCE_REMOVE

    def on_reading(self, reading: ocr.Reading):
        self.error = None
        self.last_reading = reading
        changed = self.recognizer.feed(reading.area, reading.difficulty)
        if changed:
            raw = " / ".join(reading.raw.split("\n")).strip(" /")
            print(f"area: {self.recognizer.area}  (score {reading.score:.2f}, read {raw!r})",
                  flush=True)
        self.overlay.render()
        if self.on_update:
            self.on_update()
        return GLib.SOURCE_REMOVE

    def on_error(self, message: str):
        if message != self.error:
            print(f"capture: {message}", flush=True)
        self.error = message
        self.overlay.render()
        if self.on_update:
            self.on_update()
        return GLib.SOURCE_REMOVE

    # -- commands (hotkeys, --ctl, settings window) ------------------------

    def handle(self, command: str):
        if command == "hide":
            self.set_hidden(not self.hidden)
        elif command == "freeze":
            self.set_frozen(not self.recognizer.frozen)
        elif command == "flag":
            self.flag()
        elif command == "quit":
            self.shutdown()
            return
        else:
            print(f"ignoring unknown command: {command!r}", file=sys.stderr)
            return
        if self.on_update:
            self.on_update()

    def set_hidden(self, hidden: bool):
        self.hidden = hidden
        self.overlay.set_visible(not hidden)

    def set_frozen(self, frozen: bool):
        self.recognizer.frozen = frozen
        print(f"recognition {'frozen' if frozen else 'resumed'}", flush=True)
        self.overlay.refresh()

    def set_hotkeys(self, enabled: bool):
        self.config["overlay"]["hotkeys"] = enabled
        if enabled:
            self.bridge.start()
        else:
            self.bridge.stop()

    def flag(self):
        """Append the current area to debug/flagged.log for later correction."""
        area = self.recognizer.area
        if area is None:
            return
        FLAG_LOG.parent.mkdir(exist_ok=True)
        with open(FLAG_LOG, "a") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {area}\n")
        print(f"flagged: {area}", flush=True)

    # -- teardown ---------------------------------------------------------

    def shutdown(self):
        """Stop every subsystem, then quit. Safe to call more than once."""
        if self._closed:
            return
        self._closed = True
        self.reader.stop()
        self.bridge.stop()
        self.server.close()
        self.overlay.win.destroy()
        print("overlay stopped", flush=True)
        self.app.quit()


class ControlServer:
    """Receives one-word commands over a unix socket. Command-in only."""

    def __init__(self, path: Path, on_command):
        self.path = path
        self.on_command = on_command
        if path.exists():
            path.unlink()  # left behind by a crash
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.sock.bind(str(path))
        self.sock.setblocking(False)
        GLib.io_add_watch(
            GLib.IOChannel.unix_new(self.sock.fileno()),
            GLib.PRIORITY_DEFAULT,
            GLib.IOCondition.IN,
            self._on_readable,
        )

    def _on_readable(self, *_):
        try:
            data = self.sock.recv(64)
        except BlockingIOError:
            return GLib.SOURCE_CONTINUE
        command = data.decode("utf-8", "replace").strip()
        if command:
            self.on_command(command)
        return GLib.SOURCE_CONTINUE

    def close(self):
        self.sock.close()
        self.path.unlink(missing_ok=True)


def list_monitors():
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


class HotkeyBridge:
    """Runs the evdev hotkey listener on the GLib main loop."""

    POLL_SECONDS = 2

    def __init__(self, on_command):
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


def overlay_is_running() -> bool:
    if not SOCKET_PATH.exists():
        return False
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.connect(str(SOCKET_PATH))
        return True
    except OSError:
        return False  # stale file from a crash
    finally:
        sock.close()


def send_command(command: str) -> int:
    if command not in COMMANDS:
        print(f"unknown command {command!r}; expected one of {', '.join(COMMANDS)}",
              file=sys.stderr)
        return 2
    if not SOCKET_PATH.exists():
        print("no overlay running", file=sys.stderr)
        return 1
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.sendto(command.encode(), str(SOCKET_PATH))
    except OSError as exc:
        print(f"could not reach the overlay: {exc}", file=sys.stderr)
        return 1
    finally:
        sock.close()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ctl", metavar="CMD",
                        help=f"send a command to a running overlay ({', '.join(COMMANDS)})")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--no-hotkeys", action="store_true",
                        help="start with hotkeys off (can be enabled in the window)")
    parser.add_argument("--list-outputs", action="store_true",
                        help="list connected monitors and exit")
    args = parser.parse_args(argv)

    if args.ctl:
        return send_command(args.ctl)

    if args.list_outputs:
        Gtk.init()
        rows = list_monitors()
        if not rows:
            print("no outputs found")
            return 1
        for connector, model, geometry in rows:
            print(f"{connector:<10} {geometry:<18} {model}")
        return 0

    if overlay_is_running():
        print("an overlay is already running (use --ctl quit to stop it)",
              file=sys.stderr)
        return 1

    try:
        config = configmod.load(args.config)
        rules = areas.load()
    except (OSError, configmod.ConfigError, areas.AreaError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.no_hotkeys:
        config["overlay"]["hotkeys"] = False

    import settings  # noqa: E402  (after preload; imports Gtk)

    app = Gtk.Application(application_id="dev.wagmi.d2overlay")
    session = None

    def on_activate(application):
        nonlocal session
        session = Session(application, config, rules)
        window = settings.SettingsWindow(application, session, args.config)
        window.present()

    app.connect("activate", on_activate)
    GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, 2,
                        lambda: (session.shutdown() if session else app.quit(), True)[1])
    try:
        return app.run(None)
    finally:
        if session:
            session.shutdown()


if __name__ == "__main__":
    sys.exit(main())
