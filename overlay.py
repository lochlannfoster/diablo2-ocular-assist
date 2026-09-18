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

import native

native.init()  # Linux: LD_PRELOAD re-exec, must run before gi pulls in libwayland

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

try:
    from gi.repository import GLibUnix  # noqa: E402
except ImportError:  # Windows
    GLibUnix = None

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
FLAG_LOG = native.config_dir() / "debug" / "flagged.log"

list_monitors = native.impl.list_monitors

COMMANDS = ("hide", "freeze", "quit", "flag", "edit")

DIFFICULTY_COLOURS = {"normal": "#9be59b", "nightmare": "#ffd166", "hell": "#ff5f5f"}
GOOD = "#00ff9c"
NORULE = "#ff9f5f"


def esc(text: str) -> str:
    return GLib.markup_escape_text(text)


def direction(hint) -> str:
    """The direction word, coloured: orange for 'no rule', white otherwise."""
    colour = NORULE if hint.no_rule else "#ffffff"
    return f'<span foreground="{colour}" weight="bold">{esc(hint.label)}</span>'


def band(levels: str, label: str, colour: str) -> str:
    """'45–55 recommended': a clvl range, coloured, then its label."""
    return f'<span foreground="{colour}" weight="bold">{levels}</span> {label}'


def rng(pair) -> str:
    low, high = pair
    return f"{low}" if low == high else f"{low}–{high}"


class Reader(threading.Thread):
    """Capture + OCR loop, off the GTK thread.

    Tesseract takes a few hundred milliseconds; doing that on the main loop
    would stall rendering. Results are handed back with GLib.idle_add, so the
    Recognizer and the widgets are only ever touched from the GTK thread.
    """

    FOCUS_POLL = 0.25   # seconds between game-focus checks (cheap X/Win32 call)

    def __init__(self, config, names, on_reading, on_error, on_frame=None, on_focus=None):
        super().__init__(daemon=True)
        cap = config["capture"]
        # `interval` and `region` may be reassigned from the GTK thread while
        # the loop runs; each iteration reads them once, which is enough.
        self.interval = float(cap.get("interval", 1.0))
        self.region = capture.Region(**cap["region"])
        self.backend = native.capture_backend(cap)
        self.names = names
        self.on_reading = on_reading
        self.on_error = on_error
        self.on_frame = on_frame
        self.on_focus = on_focus
        self._focused = None
        self.stop_event = threading.Event()

    def _poll_focus(self):
        """Report focus changes; runs on this thread because the X connection
        belongs to the backend and must not be shared with the GTK thread."""
        if self.on_focus is None:
            return
        try:
            focused = bool(self.backend.game_focused())
        except Exception:  # noqa: BLE001 - never let this kill the loop
            focused = False
        if focused != self._focused:
            self._focused = focused
            GLib.idle_add(self.on_focus, focused)

    def _wait(self, seconds):
        deadline = time.monotonic() + seconds
        while not self.stop_event.is_set():
            self._poll_focus()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self.stop_event.wait(min(self.FOCUS_POLL, remaining))

    def run(self):
        while not self.stop_event.is_set():
            started = time.monotonic()
            self._poll_focus()
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
            self._wait(max(0.1, self.interval - elapsed))

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
        self.win.add_css_class("overlay")  # scopes overlay.css to this window
        # Layer-shell / Win32 setup that has to precede realization.
        native.prepare_window(self.win)
        native.set_monitor(self.win, ov["output"])
        native.set_placement(self.win, ov["anchor"], int(ov["margin_x"]), int(ov["margin_y"]))

        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.root.add_css_class("root")
        self.stack = Gtk.Overlay()
        self.stack.set_child(self.root)
        self.win.set_child(self.stack)
        self.editing = False
        self.on_placement_edited = None  # settings window hook
        self._build_edit_handles()

        self.title_label = self._label("title", wrap=False)
        self.wp_head_label = self._label("head", "wp", wrap=False)
        self.wp_label = self._label("hint", "wp")
        self.next_head_label = self._label("head", "next", wrap=False)
        self.next_tip_label = self._label("hint", "next")
        self.farm_label = self._label("hint", "farm")
        self.quest_labels = [self._label("hint", "quest"), self._label("hint", "quest")]
        self.exp_head_label = self._label("head", "exp", wrap=False)
        self.exp_label = self._label("hint", "exp")
        self.drops_label = self._label("hint", "drops")
        self.notes_label = self._label("hint", "notes")
        self.uniques_label = self._label("hint", "uniques")
        self.next_label = self.next_head_label
        # Gaps between sections.
        for label in (self.wp_head_label, self.next_head_label, self.farm_label,
                      self.quest_labels[0], self.exp_head_label, self.drops_label,
                      self.notes_label, self.uniques_label):
            label.set_margin_top(10)

        self._load_css()
        self.win.connect("realize", lambda w: native.on_realize(w, self))
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

    # -- edit mode: drag to move, corner handles to resize -----------------

    HANDLE = 14

    def _build_edit_handles(self):
        self.handles = {}
        for corner, (h, v) in {
            "top-left": (Gtk.Align.START, Gtk.Align.START),
            "top-right": (Gtk.Align.END, Gtk.Align.START),
            "bottom-left": (Gtk.Align.START, Gtk.Align.END),
            "bottom-right": (Gtk.Align.END, Gtk.Align.END),
        }.items():
            handle = Gtk.Box(halign=h, valign=v)
            handle.set_size_request(self.HANDLE, self.HANDLE)
            handle.add_css_class("handle")
            handle.set_visible(False)
            drag = Gtk.GestureDrag()
            drag.connect("drag-begin", self._drag_begin)
            drag.connect("drag-update", self._resize_update, corner)
            drag.connect("drag-end", self._drag_end)
            handle.add_controller(drag)
            self.stack.add_overlay(handle)
            self.handles[corner] = handle
        move = Gtk.GestureDrag()
        move.connect("drag-begin", self._drag_begin)
        move.connect("drag-update", self._move_update)
        move.connect("drag-end", self._drag_end)
        self.root.add_controller(move)
        self._drag = None

    def set_edit_mode(self, editing: bool):
        """Editable = the surface accepts input and shows its handles. Leaving
        edit mode restores the empty input region (click-through)."""
        self.editing = editing
        for handle in self.handles.values():
            handle.set_visible(editing)
        (self.win.add_css_class if editing else self.win.remove_css_class)("editing")
        self._apply_input_region()

    def _apply_input_region(self):
        native.set_click_through(self.win, not self.editing)

    def _monitor_size(self):
        return native.monitor_size(self.win)

    def _box_rect(self):
        """Current box as (left, top, w, h) in monitor-logical pixels."""
        ov = self.session.config["overlay"]
        size = self._monitor_size()
        w, h = self.win.get_width(), self.win.get_height()
        if size is None:
            return None
        mon_w, mon_h = size
        anchor = ov["anchor"]
        left = ov["margin_x"] if anchor.endswith("left") else mon_w - ov["margin_x"] - w
        top = ov["margin_y"] if anchor.startswith("top") else mon_h - ov["margin_y"] - h
        return left, top, w, h, mon_w, mon_h

    def _drag_begin(self, gesture, x, y):
        if not self.editing:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        rect = self._box_rect()
        if rect is None:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        left, top, w, h, mon_w, mon_h = rect
        self._drag = {
            "left": left, "top": top, "w": w, "h": h, "mon_w": mon_w, "mon_h": mon_h,
            "char_px": max(1.0, w / max(1, self.width)),
            "width": self.width,
            "anchor": self.session.config["overlay"]["anchor"],
            "pending": False,
        }
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    # The drag offset GTK reports is relative to the overlay's own surface --
    # and the drag moves that surface. Once a move is applied, the pointer's
    # offset from its start point collapses back toward zero, so each update
    # is treated as an increment. Between applying a move and the compositor
    # actually moving the surface (about a frame), the offset would be applied
    # twice, so updates are ignored until a short settle time passes.
    SETTLE_MS = 40

    def _take_increment(self, dx, dy):
        d = self._drag
        if d is None or d["pending"]:
            return None
        if abs(dx) < 1 and abs(dy) < 1:
            return None
        d["pending"] = True
        GLib.timeout_add(self.SETTLE_MS, self._settled)
        return dx, dy

    def _settled(self):
        if self._drag is not None:
            self._drag["pending"] = False
        return GLib.SOURCE_REMOVE

    def _place(self, left, top, w, h, anchor, mon_w, mon_h):
        """Express a box rectangle as margins for `anchor` and apply it."""
        margin_x = int(round(left if anchor.endswith("left") else mon_w - left - w))
        margin_y = int(round(top if anchor.startswith("top") else mon_h - top - h))
        margin_x, margin_y = max(0, margin_x), max(0, margin_y)
        native.set_placement(self.win, anchor, margin_x, margin_y)
        ov = self.session.config["overlay"]
        ov["anchor"], ov["margin_x"], ov["margin_y"] = anchor, margin_x, margin_y

    def _move_update(self, gesture, dx, dy):
        step = self._take_increment(dx, dy)
        if step is None:
            return
        d = self._drag
        d["left"] += step[0]
        d["top"] += step[1]
        self._place(d["left"], d["top"], d["w"], d["h"], d["anchor"], d["mon_w"], d["mon_h"])

    def _resize_update(self, gesture, dx, dy, corner):
        step = self._take_increment(dx, dy)
        if step is None:
            return
        d = self._drag
        # The dragged corner moves; the opposite one stays put. Only width is
        # adjustable -- height follows the text.
        if corner.endswith("left"):
            d["left"] += step[0]
            d["w"] -= step[0]
        else:
            d["w"] += step[0]
        min_w = 30 * d["char_px"]
        if d["w"] < min_w:
            if corner.endswith("left"):
                d["left"] -= min_w - d["w"]
            d["w"] = min_w
        chars = int(round(d["w"] / d["char_px"]))
        if chars != self.width:
            self.set_width(chars)
            self.session.config["overlay"]["width"] = chars
        self._place(d["left"], d["top"], d["w"], d["h"], d["anchor"], d["mon_w"], d["mon_h"])

    def _drag_end(self, gesture, dx, dy):
        d = self._drag
        self._drag = None
        if not d:
            return
        # Snap the anchor to the nearest screen corner so the margins stay
        # small and the box keeps its place across resolution changes.
        rect = self._box_rect()
        if rect is not None:
            left, top, w, h, mon_w, mon_h = rect
            cx, cy = left + w / 2, top + h / 2
            anchor = ("top" if cy < mon_h / 2 else "bottom") + "-" + \
                     ("left" if cx < mon_w / 2 else "right")
            self._place(left, top, w, h, anchor, mon_w, mon_h)
        self._apply_input_region()
        if self.on_placement_edited:
            self.on_placement_edited()

    # -- live settings (called by the settings window) --------------------

    def set_placement(self, anchor, margin_x, margin_y):
        native.set_placement(self.win, anchor, margin_x, margin_y)

    def set_monitor(self, output):
        native.set_monitor(self.win, output)

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
                      self.next_head_label, self.next_tip_label, self.farm_label,
                      *self.quest_labels, self.exp_head_label, self.exp_label,
                      self.drops_label, self.notes_label, self.uniques_label):
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
                          self.farm_label, *self.quest_labels, self.exp_head_label,
                          self.exp_label, self.drops_label, self.notes_label,
                          self.uniques_label):
                label.set_visible(False)
            return

        area = areas.resolve(self.rules, rec.area, self.last_act)
        self.last_act = area.act
        dot = {"high": "●", "medium": "●", "low": "○"}[area.confidence]
        level = area.level(rec.difficulty)
        diff = f'<span foreground="{DIFFICULTY_COLOURS[rec.difficulty]}">' \
               f'{rec.difficulty.upper()}</span>'
        detail = f"alvl {level}" if level else ("town" if not area.levels[0] else "alvl ?")
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

        self.farm_label.set_visible(bool(area.farm))
        if area.farm:
            self.farm_label.set_markup("FARM  " + esc("  ·  ".join(area.farm)))

        # One quest per line; unused lines are hidden so the box stays tight.
        for label, quest in zip(self.quest_labels, list(area.quests) + ["", ""]):
            label.set_visible(bool(quest))
            if quest:
                label.set_markup(f"QUEST  {esc(quest)}")

        # One line: the clvl band that gets full XP here, then the band that
        # still gets a worthwhile rate (43-81%).
        self.exp_head_label.set_visible(False)
        if level:
            b = areas.exp_bands(level)
            self.exp_label.set_markup(
                f"CLVL  {band(rng(b['good']), 'recommended', GOOD)}"
                f"  <span foreground=\"#8a9a94\">"
                f"({rng((b['avg_low'][0], b['avg_high'][1]))} still ok, mlvl {level})</span>")
        else:
            self.exp_label.set_visible(False)

        drops = areas.drop_note(area.act, rec.difficulty, level)
        self.drops_label.set_visible(bool(drops))
        if drops:
            self.drops_label.set_markup("DROPS  " + esc(drops))

        notes = list(area.notes)
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
            ("farm", (self.farm_label,)),
            ("quests", self.quest_labels),
            ("exp", (self.exp_head_label, self.exp_label)),
            ("drops", (self.drops_label,)),
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
        self.game_focused = True   # optimistic until the reader reports
        self.on_update = None   # settings window hook: called after each reading
        self._closed = False

        self.overlay = Overlay(app, self)
        self.server = ControlServer(SOCKET_PATH, self.handle) if native.HAS_CONTROL_SOCKET else None
        self.reader = Reader(config, areas.screen_names(rules),
                             self.on_reading, self.on_error, self.on_frame, self.on_focus)
        self.reader.start()
        self.bridge = native.hotkey_bridge(self.handle)
        if config["overlay"].get("hotkeys", True):
            self.bridge.start()
        print(f"overlay running: {len(rules)} areas loaded", flush=True)
        if self.server:
            print(f"control socket: {SOCKET_PATH}", flush=True)

    # -- from the reader thread (delivered on the GTK thread) -------------

    def on_frame(self, image):
        self.last_frame = image
        return GLib.SOURCE_REMOVE

    def on_focus(self, focused: bool):
        self.game_focused = focused
        self.apply_visibility()
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
        self.apply_visibility()
        if self.on_update:
            self.on_update()
        return GLib.SOURCE_REMOVE

    def on_error(self, message: str):
        if message != self.error:
            print(f"capture: {message}", flush=True)
        self.error = message
        self.recognizer.feed(None)
        self.overlay.render()
        self.apply_visibility()
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
        elif command == "edit":
            self.set_edit_mode(not self.overlay.editing)
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
        self.apply_visibility()

    def set_edit_mode(self, editing: bool):
        self.overlay.set_edit_mode(editing)
        self.apply_visibility()   # edit mode always shows it, focus or not

    def set_follow_focus(self, enabled: bool):
        self.config["overlay"]["follow_focus"] = enabled
        self.apply_visibility()

    def set_hide_unread(self, enabled: bool):
        self.config["overlay"]["hide_unread"] = enabled
        self.apply_visibility()

    UNREAD_GRACE = 2   # consecutive unreadable frames before hiding

    def apply_visibility(self):
        """Ctrl+F9 hides outright. Otherwise, unless the user is dragging the
        overlay around in edit mode: follow the game's focus, and hide while
        the area name has been unreadable for a couple of frames (map off,
        menus, loading) -- a frozen overlay is exempt, that is the point of
        freezing it."""
        ov = self.config["overlay"]
        rec = self.recognizer
        visible = not self.hidden
        if visible and not self.overlay.editing:
            if ov.get("follow_focus", True):
                visible = self.game_focused
            if visible and ov.get("hide_unread", True) and not rec.frozen:
                visible = rec.visible or rec.misses < self.UNREAD_GRACE
        self.overlay.set_visible(visible)

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
        if self.server:
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


def overlay_is_running() -> bool:
    if not native.HAS_CONTROL_SOCKET or not SOCKET_PATH.exists():
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
    if not native.HAS_CONTROL_SOCKET:
        print("--ctl is not available on this platform; use the settings window",
              file=sys.stderr)
        return 1
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
    if GLibUnix is not None:
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, 2,
                            lambda: (session.shutdown() if session else app.quit(), True)[1])
    try:
        return app.run(None)
    finally:
        if session:
            session.shutdown()


if __name__ == "__main__":
    sys.exit(main())
