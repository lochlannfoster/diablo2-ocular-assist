"""The settings window: an ordinary, clickable GTK window that owns the run.

It is the application's main window. Every control applies immediately to the
live overlay and is written back to config.toml (debounced), and closing the
window calls Session.shutdown(): OCR thread, hotkeys, control socket and the
overlay itself all go with it.
"""

from __future__ import annotations

import io
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

import config as configmod  # noqa: E402
import hotkeys  # noqa: E402
import overlay as overlaymod  # noqa: E402

SAVE_DEBOUNCE_MS = 500


class SettingsWindow(Gtk.ApplicationWindow):
    def __init__(self, app, session, config_path: Path):
        super().__init__(application=app, title="Diablo II overlay")
        self.session = session
        self.config = session.config
        self.config_path = config_path
        self._save_timer = None
        self._loading = False   # suppress handlers while widgets are being filled
        self.set_default_size(600, 860)
        self.connect("close-request", self._on_close)
        session.on_update = self._refresh_status
        session.overlay.on_placement_edited = self._on_placement_edited

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                        margin_top=14, margin_bottom=14, margin_start=16, margin_end=16)
        # Scroll rather than demand height: the wrapping status labels change
        # size every read, and a toplevel that keeps asking for more height
        # than it was given makes GTK complain on every frame.
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                      vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(outer)
        self.set_child(scroller)

        outer.append(self._build_status())
        outer.append(self._build_overlay_section())
        outer.append(self._build_capture_section())
        outer.append(self._build_buttons())

        self._fill_from_config()
        self._refresh_status()
        # Game presence changes without any reading arriving (game closed), so
        # poll it alongside the reader's updates.
        self._status_timer = GLib.timeout_add_seconds(2, self._refresh_status_tick)

    # -- building ----------------------------------------------------------

    @staticmethod
    def _frame(title: str) -> tuple[Gtk.Frame, Gtk.Grid]:
        frame = Gtk.Frame(label=title)
        grid = Gtk.Grid(column_spacing=12, row_spacing=8,
                        margin_top=10, margin_bottom=10, margin_start=12, margin_end=12)
        frame.set_child(grid)
        return frame, grid

    @staticmethod
    def _row(grid: Gtk.Grid, row: int, text: str, widget: Gtk.Widget):
        label = Gtk.Label(label=text, xalign=1)
        label.add_css_class("dim-label")
        grid.attach(label, 0, row, 1, 1)
        widget.set_hexpand(True)
        grid.attach(widget, 1, row, 1, 1)

    def _build_status(self):
        frame, grid = self._frame("Status")
        self.game_label = Gtk.Label(xalign=0)
        self.area_label = Gtk.Label(xalign=0, wrap=True, max_width_chars=50)
        self.ocr_label = Gtk.Label(xalign=0, wrap=True, selectable=True, max_width_chars=50)
        self.ocr_label.add_css_class("monospace")
        self.preview = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True)
        self.preview.set_size_request(-1, 90)
        self._row(grid, 0, "Game", self.game_label)
        self._row(grid, 1, "Area", self.area_label)
        self._row(grid, 2, "OCR read", self.ocr_label)
        self._row(grid, 3, "Capture", self.preview)
        return frame

    def _build_overlay_section(self):
        frame, grid = self._frame("Overlay")
        row = 0

        toggles = Gtk.Box(spacing=18)
        self.show_switch = self._switch(toggles, "Show", self._on_show)
        self.freeze_switch = self._switch(toggles, "Freeze recognition", self._on_freeze)
        self.hotkeys_switch = self._switch(toggles, "Hotkeys (Ctrl+F9–F12)", self._on_hotkeys)
        self._row(grid, row, "", toggles); row += 1

        self.edit_check = Gtk.CheckButton(
            label="Edit mode — drag the overlay to move it, drag a corner to resize")
        self.edit_check.connect("toggled", self._on_edit_mode)
        self._row(grid, row, "", self.edit_check); row += 1

        sections = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3,
                               column_spacing=12, row_spacing=4)
        self.section_checks = {}
        for key, label in configmod.SECTIONS.items():
            check = Gtk.CheckButton(label=label)
            check.connect("toggled", self._on_section, key)
            self.section_checks[key] = check
            sections.append(check)
        self._row(grid, row, "Sections", sections); row += 1

        self.output_combo = Gtk.DropDown.new_from_strings(["(compositor default)"])
        self._outputs = [""]
        for connector, model, geometry in overlaymod.list_monitors():
            self._outputs.append(connector)
            self.output_combo.get_model().append(f"{connector}  {geometry}  {model}".strip())
        self.output_combo.connect("notify::selected", self._on_output)
        self._row(grid, row, "Monitor", self.output_combo); row += 1

        self.anchor_combo = Gtk.DropDown.new_from_strings(list(configmod.ANCHORS))
        self.anchor_combo.connect("notify::selected", self._on_placement)
        self._row(grid, row, "Corner", self.anchor_combo); row += 1

        margins = Gtk.Box(spacing=8)
        self.margin_x = self._spin(margins, "x", 0, 4000, 1, self._on_placement)
        self.margin_y = self._spin(margins, "y", 0, 4000, 1, self._on_placement)
        self._row(grid, row, "Margins (px)", margins); row += 1

        text = Gtk.Box(spacing=8)
        self.font_spin = self._spin(text, "font px", 8, 40, 1, self._on_font)
        self.width_spin = self._spin(text, "width chars", 30, 120, 1, self._on_width)
        self._row(grid, row, "Text", text); row += 1
        return frame

    def _build_capture_section(self):
        frame, grid = self._frame("Capture (fractions of the game window)")
        region = Gtk.Box(spacing=8)
        self.region_spins = {}
        for key in ("x", "y", "w", "h"):
            self.region_spins[key] = self._spin(region, key, 0.0, 1.0, 0.005,
                                                self._on_region, digits=3)
        self._row(grid, 0, "Region", region)
        misc = Gtk.Box(spacing=8)
        self.interval_spin = self._spin(misc, "interval s", 0.2, 10.0, 0.1,
                                        self._on_interval, digits=1)
        self._row(grid, 1, "Timing", misc)
        return frame

    def _build_buttons(self):
        box = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        flag = Gtk.Button(label="Flag current area as wrong")
        flag.connect("clicked", lambda *_: self.session.flag())
        reset = Gtk.Button(label="Reload config.toml")
        reset.connect("clicked", self._on_reload)
        quit_button = Gtk.Button(label="Quit")
        quit_button.add_css_class("destructive-action")
        quit_button.connect("clicked", lambda *_: self.close())
        for button in (flag, reset, quit_button):
            box.append(button)
        return box

    @staticmethod
    def _switch(box, text, handler):
        inner = Gtk.Box(spacing=6)
        switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        switch.connect("state-set", handler)
        inner.append(switch)
        inner.append(Gtk.Label(label=text))
        box.append(inner)
        return switch

    @staticmethod
    def _spin(box, text, low, high, step, handler, digits=0):
        inner = Gtk.Box(spacing=4)
        inner.append(Gtk.Label(label=text))
        spin = Gtk.SpinButton.new_with_range(low, high, step)
        spin.set_digits(digits)
        spin.connect("value-changed", handler)
        inner.append(spin)
        box.append(inner)
        return spin

    # -- config <-> widgets --------------------------------------------------

    def _fill_from_config(self):
        self._loading = True
        ov, cap = self.config["overlay"], self.config["capture"]
        self.show_switch.set_active(not self.session.hidden)
        self.freeze_switch.set_active(self.session.recognizer.frozen)
        self.hotkeys_switch.set_active(bool(ov["hotkeys"]))
        for key, check in self.section_checks.items():
            check.set_active(bool(ov["sections"].get(key, True)))
        output = ov["output"]
        self.output_combo.set_selected(
            self._outputs.index(output) if output in self._outputs else 0)
        self.anchor_combo.set_selected(configmod.ANCHORS.index(ov["anchor"]))
        self.margin_x.set_value(ov["margin_x"])
        self.margin_y.set_value(ov["margin_y"])
        self.font_spin.set_value(ov["font_size"])
        self.width_spin.set_value(ov["width"])
        for key, spin in self.region_spins.items():
            spin.set_value(cap["region"][key])
        self.interval_spin.set_value(cap["interval"])
        self._loading = False

    def _schedule_save(self):
        if self._loading:
            return
        if self._save_timer is not None:
            GLib.source_remove(self._save_timer)
        self._save_timer = GLib.timeout_add(SAVE_DEBOUNCE_MS, self._save_now)

    def _save_now(self):
        self._save_timer = None
        try:
            configmod.save(self.config, self.config_path)
        except OSError as exc:
            print(f"warning: could not save {self.config_path}: {exc}", flush=True)
        return GLib.SOURCE_REMOVE

    # -- handlers ----------------------------------------------------------

    def _on_show(self, switch, state):
        if not self._loading:
            self.session.set_hidden(not state)
        return False

    def _on_freeze(self, switch, state):
        if not self._loading:
            self.session.set_frozen(state)
        return False

    def _on_hotkeys(self, switch, state):
        if not self._loading:
            self.session.set_hotkeys(state)
            self._schedule_save()
        return False

    def _on_edit_mode(self, check):
        editing = check.get_active()
        self.session.overlay.set_edit_mode(editing)
        if not editing:
            # Unticking is the "done" action: persist whatever was dragged.
            if self._save_timer is not None:
                GLib.source_remove(self._save_timer)
            self._save_now()

    def _on_placement_edited(self):
        """The overlay was dragged: mirror the new placement into the widgets."""
        ov = self.config["overlay"]
        self._loading = True
        self.anchor_combo.set_selected(configmod.ANCHORS.index(ov["anchor"]))
        self.margin_x.set_value(ov["margin_x"])
        self.margin_y.set_value(ov["margin_y"])
        self.width_spin.set_value(ov["width"])
        self._loading = False
        self._schedule_save()

    def _on_section(self, check, key):
        if self._loading:
            return
        self.config["overlay"]["sections"][key] = check.get_active()
        self.session.overlay.refresh()
        self._schedule_save()

    def _on_output(self, combo, _param):
        if self._loading:
            return
        output = self._outputs[combo.get_selected()]
        self.config["overlay"]["output"] = output
        self.session.overlay.set_monitor(output)
        self._schedule_save()

    def _on_placement(self, *_):
        if self._loading:
            return
        ov = self.config["overlay"]
        ov["anchor"] = configmod.ANCHORS[self.anchor_combo.get_selected()]
        ov["margin_x"] = int(self.margin_x.get_value())
        ov["margin_y"] = int(self.margin_y.get_value())
        self.session.overlay.set_placement(ov["anchor"], ov["margin_x"], ov["margin_y"])
        self._schedule_save()

    def _on_font(self, spin):
        if self._loading:
            return
        self.config["overlay"]["font_size"] = int(spin.get_value())
        self.session.overlay.set_font_size(int(spin.get_value()))
        self._schedule_save()

    def _on_width(self, spin):
        if self._loading:
            return
        self.config["overlay"]["width"] = int(spin.get_value())
        self.session.overlay.set_width(int(spin.get_value()))
        self._schedule_save()

    def _on_region(self, *_):
        if self._loading:
            return
        region = self.config["capture"]["region"]
        for key, spin in self.region_spins.items():
            region[key] = round(spin.get_value(), 4)
        self.session.reader.region = overlaymod.capture.Region(**region)
        self._schedule_save()

    def _on_interval(self, spin):
        if self._loading:
            return
        self.config["capture"]["interval"] = round(spin.get_value(), 2)
        self.session.reader.interval = self.config["capture"]["interval"]
        self._schedule_save()

    def _on_reload(self, *_):
        try:
            fresh = configmod.load(self.config_path)
        except configmod.ConfigError as exc:
            self.ocr_label.set_text(f"config error: {exc}")
            return
        # Update in place: the Session and Overlay hold references to this dict.
        self.config["overlay"].update(fresh["overlay"])
        self.config["capture"].update(fresh["capture"])
        self._fill_from_config()
        ov = self.config["overlay"]
        self.session.overlay.set_placement(ov["anchor"], ov["margin_x"], ov["margin_y"])
        self.session.overlay.set_font_size(ov["font_size"])
        self.session.overlay.set_width(ov["width"])
        self.session.overlay.refresh()
        self.session.reader.region = overlaymod.capture.Region(**self.config["capture"]["region"])
        self.session.reader.interval = self.config["capture"]["interval"]

    # -- status ------------------------------------------------------------

    def _refresh_status_tick(self):
        self._refresh_status()
        return GLib.SOURCE_CONTINUE

    def _refresh_status(self):
        session = self.session
        rec = session.recognizer
        running = hotkeys.game_is_running()
        self.game_label.set_markup(
            '<span foreground="#2ec27e">D2R running</span>' if running
            else '<span foreground="#e5a50a">D2R not detected</span>')

        if session.error:
            self.area_label.set_markup(f'<span foreground="#e01b24">{GLib.markup_escape_text(session.error)}</span>')
        elif rec.area:
            bits = [rec.area]
            if rec.difficulty:
                bits.append(rec.difficulty.capitalize())
            if rec.frozen:
                bits.append("frozen")
            elif not rec.visible:
                bits.append("not on screen right now")
            self.area_label.set_text("  ·  ".join(bits))
        else:
            self.area_label.set_text("nothing recognised yet")

        reading = session.last_reading
        if reading is not None:
            raw = " / ".join(line for line in reading.raw.splitlines() if line.strip()) or "(blank)"
            match = f"→ {reading.area} ({reading.score:.2f})" if reading.area else f"(best {reading.score:.2f})"
            self.ocr_label.set_text(f"{raw}   {match}")

        frame = session.last_frame
        if frame is not None and frame is not getattr(self, "_shown_frame", None):
            self._shown_frame = frame
            buffer = io.BytesIO()
            frame.save(buffer, format="PNG")
            try:
                texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(buffer.getvalue()))
                self.preview.set_paintable(texture)
            except GLib.Error:
                pass

        # Keep the toggles honest when state changed via hotkey / --ctl.
        self._loading = True
        self.show_switch.set_active(not session.hidden)
        self.freeze_switch.set_active(rec.frozen)
        if self.edit_check.get_active() != session.overlay.editing:
            self.edit_check.set_active(session.overlay.editing)
        self._loading = False

    # -- lifecycle ---------------------------------------------------------

    def _on_close(self, *_):
        if self.session.overlay.editing:
            self.session.overlay.set_edit_mode(False)
        if self._save_timer is not None:
            GLib.source_remove(self._save_timer)
            self._save_now()
        GLib.source_remove(self._status_timer)
        self.session.on_update = None
        self.session.shutdown()
        return False  # let the window close
