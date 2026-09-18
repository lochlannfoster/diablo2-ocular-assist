"""Windows backend: plain Win32 through ctypes, no extra packages.

- Overlay window: an undecorated GTK toplevel made topmost, non-activating
  and hidden from the taskbar with extended window styles; click-through is
  WS_EX_TRANSPARENT (on a layered window). Placement is SetWindowPos from the
  chosen monitor's rectangle, margins in physical pixels.
- Capture: screen grab (PIL.ImageGrab) of the D2R window's client rectangle.
  Exclusive-fullscreen D3D cannot be captured or drawn over; the game must be
  in Windowed / Windowed (Fullscreen) mode.
- Hotkeys: RegisterHotKey on a dedicated message-loop thread.

Untested paths are marked; this file is exercised by the CI build and by
whoever runs the exe, not by the Linux development machine.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
from ctypes import wintypes
from pathlib import Path

HAS_CONTROL_SOCKET = False

user32 = ctypes.windll.user32 if sys.platform.startswith("win") else None
kernel32 = ctypes.windll.kernel32 if sys.platform.startswith("win") else None

GAME_WINDOW_TITLE = "Diablo II: Resurrected"
OVERLAY_TITLE = "d2-overlay-surface"   # how we find our own HWND

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
LWA_ALPHA = 0x2
MONITOR_DEFAULTTONEAREST = 2
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
MOD_CONTROL, MOD_NOREPEAT = 0x0002, 0x4000
VK_F9 = 0x78

# Per-window desired placement, applied once the HWND exists and again on
# every surface layout (the box changes height as the text changes).
_placement: dict[int, dict] = {}


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


def init():
    # Physical pixels everywhere (GetWindowRect, ImageGrab, monitor rects)
    # so the capture region and the placement maths agree. GTK may set this
    # itself; a second call just fails, harmlessly.
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    except (AttributeError, OSError):
        pass


# -- overlay window ---------------------------------------------------------

def _hwnd(win):
    return user32.FindWindowW(None, OVERLAY_TITLE) or None


def prepare_window(win):
    win.set_title(OVERLAY_TITLE)
    win.set_decorated(False)
    win.set_resizable(False)
    # GTK4's win32 backend does not do per-pixel alpha on a layered window
    # reliably, so the overlay draws on a solid dark background instead of
    # the translucent scrim (overlay.css: window.overlay.win32).
    win.add_css_class("win32")


def on_realize(win, overlay):
    hwnd = _hwnd(win)
    if not hwnd:
        print("warning: could not find the overlay HWND", file=sys.stderr)
        return
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    style |= WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
    user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
    set_click_through(win, not overlay.editing)
    _apply_placement(win)
    surface = win.get_native().get_surface()
    surface.connect("layout", lambda *_: _apply_placement(win))


def set_click_through(win, enabled: bool):
    hwnd = _hwnd(win)
    if not hwnd:
        return
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    style = (style | WS_EX_TRANSPARENT) if enabled else (style & ~WS_EX_TRANSPARENT)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)


def set_placement(win, anchor, margin_x, margin_y):
    state = _placement.setdefault(id(win), {"output": ""})
    state.update(anchor=str(anchor).lower(), margin_x=int(margin_x), margin_y=int(margin_y))
    _apply_placement(win)


def set_monitor(win, output):
    state = _placement.setdefault(id(win), {"anchor": "top-right", "margin_x": 0, "margin_y": 0})
    state["output"] = output or ""
    _apply_placement(win)


def _monitors():
    """[(device name, RECT)] for every display."""
    found = []
    MonitorEnumProc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                                         ctypes.POINTER(wintypes.RECT), ctypes.c_double)

    def callback(hmonitor, hdc, rect, data):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            found.append((info.szDevice, info.rcMonitor, hmonitor))
        return 1

    user32.EnumDisplayMonitors(None, None, MonitorEnumProc(callback), 0)
    return found


def _monitor_rect(win):
    state = _placement.get(id(win), {})
    output = state.get("output", "")
    monitors = _monitors()
    for device, rect, _ in monitors:
        if output and device.lower() == output.lower():
            return rect
    hwnd = _hwnd(win)
    if hwnd:
        hmon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        for _, rect, handle in monitors:
            if handle == hmon:
                return rect
    return monitors[0][1] if monitors else None


def monitor_size(win):
    rect = _monitor_rect(win)
    if rect is None:
        return None
    return rect.right - rect.left, rect.bottom - rect.top


def _apply_placement(win):
    hwnd = _hwnd(win)
    state = _placement.get(id(win))
    if not hwnd or not state or "anchor" not in state:
        return
    mon = _monitor_rect(win)
    if mon is None:
        return
    size = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(size))
    w, h = size.right - size.left, size.bottom - size.top
    anchor, mx, my = state["anchor"], state["margin_x"], state["margin_y"]
    x = mon.left + mx if anchor.endswith("left") else mon.right - mx - w
    y = mon.top + my if anchor.startswith("top") else mon.bottom - my - h
    user32.SetWindowPos(hwnd, HWND_TOPMOST, int(x), int(y), 0, 0, SWP_NOSIZE | SWP_NOACTIVATE)


def list_monitors():
    rows = []
    for device, rect, _ in _monitors():
        rows.append((device, "", f"{rect.right - rect.left}x{rect.bottom - rect.top}+{rect.left}+{rect.top}"))
    return rows


# -- capture ---------------------------------------------------------------

class WindowsCapture:
    """Screen grab of the game window's client area."""

    def __init__(self, title: str = GAME_WINDOW_TITLE):
        self.title = title

    def _client_rect(self):
        import capture

        hwnd = user32.FindWindowW(None, self.title)
        if not hwnd:
            raise capture.CaptureError(f"no window titled {self.title!r}")
        rect = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        origin = wintypes.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(origin))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w <= 0 or h <= 0:
            raise capture.CaptureError("game window is minimised")
        return origin.x, origin.y, w, h

    def window_size(self):
        _, _, w, h = self._client_rect()
        return w, h

    def grab(self, region=None):
        from PIL import ImageGrab

        left, top, w, h = self._client_rect()
        if region is not None:
            rx, ry, rw, rh = region.to_pixels(w, h)
            left, top, w, h = left + rx, top + ry, rw, rh
        # Coordinates are relative to the virtual screen, which starts at
        # negative offsets when a monitor sits left of / above the primary.
        vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        screen = ImageGrab.grab(all_screens=True)
        return screen.crop((left - vx, top - vy, left - vx + w, top - vy + h)).convert("RGB")

    def close(self):
        pass


def capture_backend(cap: dict):
    return WindowsCapture()


# -- hotkeys ---------------------------------------------------------------

CHORDS = {0: "hide", 1: "freeze", 2: "quit", 3: "flag"}   # Ctrl+F9..F12


class WinHotkeys(threading.Thread):
    """RegisterHotKey is per-thread and delivers WM_HOTKEY to that thread's
    message queue, so the hotkeys get a thread and a loop of their own."""

    def __init__(self, on_command):
        super().__init__(daemon=True)
        self.on_command = on_command
        self.thread_id = None
        self.started_ok = threading.Event()

    def run(self):
        from gi.repository import GLib

        self.thread_id = kernel32.GetCurrentThreadId()
        for index in CHORDS:
            if not user32.RegisterHotKey(None, index + 1, MOD_CONTROL | MOD_NOREPEAT, VK_F9 + index):
                print(f"hotkeys: could not register Ctrl+F{9 + index}", file=sys.stderr)
        self.started_ok.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                command = CHORDS.get(int(msg.wParam) - 1)
                if command:
                    GLib.idle_add(lambda c=command: (self.on_command(c), False)[1])
        for index in CHORDS:
            user32.UnregisterHotKey(None, index + 1)

    def start(self):
        if self.is_alive():
            return True
        super().start()
        self.started_ok.wait(2)
        print("hotkeys: Ctrl+F9 hide, F10 freeze, F11 quit, F12 flag", flush=True)
        return True

    def stop(self):
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)


def hotkey_bridge(on_command):
    return WinHotkeys(on_command)


# -- misc ------------------------------------------------------------------

def game_is_running() -> bool:
    return bool(user32.FindWindowW(None, GAME_WINDOW_TITLE))


def _bundle_dir() -> Path | None:
    return Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "frozen", False) else None


def tesseract_command() -> list[str]:
    override = os.environ.get("D2_TESSERACT")
    if override:
        return [override]
    bundle = _bundle_dir()
    if bundle is not None:
        # overlay.spec puts tesseract.exe beside the bundled DLLs it needs and
        # the language data under tessdata/.
        exe = bundle / "tesseract.exe"
        if exe.exists():
            os.environ.setdefault("TESSDATA_PREFIX", str(bundle / "tessdata"))
            return [str(exe)]
    return ["tesseract"]


def config_dir() -> Path:
    # Next to the exe when frozen, so settings survive re-downloads of the
    # bundle; the repo root otherwise.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent
