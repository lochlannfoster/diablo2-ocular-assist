"""Grab pixels from the game window without touching the game.

D2R under Proton is an X11 client, so on a KDE Wayland desktop it lives inside
Xwayland. Asking the X server for the window's image is a plain XGetImage on
*our* X connection: no hooks, no injection, nothing loaded into the game. It
is also the only route that needs no consent dialog and no compositor
authorisation -- the portal and KWin ScreenShot2 paths both do.

Grabbing the X *root* fails with BadMatch under rootless Xwayland (the root has
no backing pixmap), which is why the game window is located by name and read
directly. A full 3264x1836 grab measured ~300 ms; the overlay only needs a
small corner, so `grab()` asks X for just that rectangle.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from PIL import Image

try:
    from Xlib import X, display
    from Xlib.error import XError
except ImportError:  # not on Linux
    X = display = None

    class XError(Exception):
        pass

# The window title D2R sets. Matched exactly: a browser tab or editor buffer
# showing a wiki page about the game would otherwise be a candidate.
GAME_WINDOW_TITLE = "Diablo II: Resurrected"


class CaptureError(Exception):
    pass


@dataclass(frozen=True)
class Region:
    """A rectangle as fractions of the game window, so it survives resolution
    changes and windowed/fullscreen switches."""

    x: float
    y: float
    w: float
    h: float

    def to_pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        left = int(self.x * width)
        top = int(self.y * height)
        w = max(1, int(self.w * width))
        h = max(1, int(self.h * height))
        # Clamp: a region that spills past the window edge makes XGetImage fail.
        w = min(w, width - left)
        h = min(h, height - top)
        return left, top, w, h


class XwaylandCapture:
    """Reads the game window through Xwayland."""

    def __init__(self, display_name: str | None = None, title: str = GAME_WINDOW_TITLE):
        self.display_name = display_name or os.environ.get("DISPLAY", ":0")
        self.title = title
        self._display = None
        self._window = None

    def _connect(self):
        if display is None:
            raise CaptureError("python-xlib is not installed")
        if self._display is None:
            try:
                self._display = display.Display(self.display_name)
            except Exception as exc:  # python-xlib raises a mix of types
                raise CaptureError(f"cannot open X display {self.display_name}: {exc}")
        return self._display

    def find_window(self):
        """Locate the game window, caching it while it stays valid."""
        if self._window is not None:
            try:
                self._window.get_geometry()
                return self._window
            except XError:
                self._window = None  # the game was closed; look again
        root = self._connect().screen().root
        found = self._search(root)
        if found is None:
            raise CaptureError(f"no viewable window titled {self.title!r} on {self.display_name}")
        self._window = found
        return found

    def _search(self, window):
        try:
            children = window.query_tree().children
        except XError:
            return None
        for child in children:
            try:
                if (child.get_wm_name() == self.title
                        and child.get_attributes().map_state == X.IsViewable):
                    return child
            except XError:
                continue
            inner = self._search(child)
            if inner is not None:
                return inner
        return None

    def window_size(self) -> tuple[int, int]:
        geometry = self.find_window().get_geometry()
        return geometry.width, geometry.height

    def game_focused(self) -> bool:
        """Is the game the active window? KWin mirrors the focused toplevel
        into Xwayland's root _NET_ACTIVE_WINDOW; while a native Wayland window
        (browser, terminal) has focus it points at a nameless placeholder
        instead, so comparing against the game's id is enough."""
        try:
            window = self.find_window()
            root = self._connect().screen().root
            atom = self._display.intern_atom("_NET_ACTIVE_WINDOW")
            prop = root.get_full_property(atom, X.AnyPropertyType)
        except (CaptureError, XError):
            return False
        return bool(prop and prop.value and prop.value[0] == window.id)

    def grab(self, region: Region | None = None) -> Image.Image:
        """Return an RGB image of `region` (or the whole window)."""
        window = self.find_window()
        try:
            geometry = window.get_geometry()
            if region is None:
                left, top, w, h = 0, 0, geometry.width, geometry.height
            else:
                left, top, w, h = region.to_pixels(geometry.width, geometry.height)
            raw = window.get_image(left, top, w, h, X.ZPixmap, 0xFFFFFFFF)
        except XError as exc:
            self._window = None
            raise CaptureError(f"XGetImage failed: {exc}")
        if raw.depth not in (24, 32):
            raise CaptureError(f"unexpected pixel depth {raw.depth}")
        # Xwayland hands back 32-bit BGRX for 24-bit visuals.
        return Image.frombytes("RGB", (w, h), raw.data, "raw", "BGRX")

    def close(self):
        if self._display is not None:
            self._display.close()
            self._display = None
            self._window = None


def make(backend: str, **kwargs):
    """Build a capture backend by config name."""
    if backend == "xwayland":
        return XwaylandCapture(**kwargs)
    raise CaptureError(f"unknown capture backend {backend!r} (available: xwayland)")
