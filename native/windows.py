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
    # The bundle is built console=False, so stdout/stderr go nowhere: send
    # them to overlay.log next to the exe (same place as config.toml), fresh
    # each start, and record any uncaught exception there too. Without this a
    # startup crash is a window that never appears and nothing to send back.
    if getattr(sys, "frozen", False):
        import faulthandler
        log_path = config_dir() / "overlay.log"
        try:
            log = open(log_path, "w", buffering=1, encoding="utf-8", errors="replace")
        except OSError:
            log = None
        if log is not None:
            sys.stdout = sys.stderr = log
            faulthandler.enable(log)
            print(f"diablo2-ocular-assist starting; log at {log_path}", flush=True)

            def hook(exc_type, exc, tb):
                import traceback
                traceback.print_exception(exc_type, exc, tb, file=log)
                log.flush()
            sys.excepthook = hook
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
    set_opacity(win, float(overlay.session.config["overlay"].get("opacity", 0.82)))
    set_click_through(win, not overlay.editing)
    _apply_placement(win)
    surface = win.get_native().get_surface()
    surface.connect("layout", lambda *_: _apply_placement(win))


def set_opacity(win, alpha: float):
    """Whole-window alpha: the win32 backend has no per-pixel alpha, so the
    scrim opacity from the settings is applied to the layered window."""
    hwnd = _hwnd(win)
    if hwnd:
        user32.SetLayeredWindowAttributes(hwnd, 0, int(max(0.2, min(1.0, alpha)) * 255), LWA_ALPHA)


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

    def game_focused(self):
        hwnd = user32.FindWindowW(None, self.title)
        return bool(hwnd) and user32.GetForegroundWindow() == hwnd

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

MOD_SHIFT = 0x0004
# (modifiers, virtual key, command); the RegisterHotKey id is the index + 1.
# Same table as hotkeys.CHORDS on Linux.
HOTKEYS = (
    (MOD_CONTROL, VK_F9, "hide"),
    (MOD_CONTROL, VK_F9 + 1, "freeze"),
    (MOD_CONTROL, VK_F9 + 2, "quit"),
    (MOD_CONTROL, VK_F9 + 3, "flag"),
    (MOD_CONTROL | MOD_SHIFT, VK_F9, "compact"),
    (MOD_CONTROL | MOD_SHIFT, VK_F9 + 1, "profile"),
    (MOD_CONTROL | MOD_SHIFT, VK_F9 + 2, "edit"),
)


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
        for index, (mods, vk, command) in enumerate(HOTKEYS):
            if not user32.RegisterHotKey(None, index + 1, mods | MOD_NOREPEAT, vk):
                shift = "Shift+" if mods & MOD_SHIFT else ""
                print(f"hotkeys: could not register Ctrl+{shift}F{9 + vk - VK_F9} ({command})",
                      file=sys.stderr)
        self.started_ok.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                index = int(msg.wParam) - 1
                if 0 <= index < len(HOTKEYS):
                    command = HOTKEYS[index][2]
                    GLib.idle_add(lambda c=command: (self.on_command(c), False)[1])
        for index in range(len(HOTKEYS)):
            user32.UnregisterHotKey(None, index + 1)

    def start(self):
        if self.is_alive():
            return True
        super().start()
        self.started_ok.wait(2)
        print("hotkeys: Ctrl+F9 hide, F10 freeze, F11 quit, F12 flag; "
              "Ctrl+Shift+F9 compact, F10 profile, F11 edit", flush=True)
        return True

    def stop(self):
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)


def hotkey_bridge(on_command):
    return WinHotkeys(on_command)


# -- tray icon ---------------------------------------------------------------

WM_DESTROY, WM_CLOSE, WM_COMMAND, WM_NULL = 0x0002, 0x0010, 0x0111, 0x0000
WM_RBUTTONUP, WM_LBUTTONDBLCLK, WM_CONTEXTMENU = 0x0205, 0x0203, 0x007B
WM_APP = 0x8000
WM_TRAY = WM_APP + 1
NIM_ADD, NIM_DELETE, NIM_SETVERSION = 0x0, 0x2, 0x4
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4
NOTIFYICON_VERSION_4 = 4
TPM_RETURNCMD, TPM_NONOTIFY, TPM_RIGHTBUTTON = 0x0100, 0x0080, 0x0002
MF_STRING, MF_SEPARATOR = 0x0, 0x800
IDI_APPLICATION = 32512
WS_OVERLAPPED = 0
CS_DBLCLKS = 0x0008

# LRESULT is pointer-sized; the default int return would truncate on x64.
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM) if user32 else None


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC or ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class WinTray(threading.Thread):
    """Shell_NotifyIcon needs a window and a message loop, so like the
    hotkeys it lives on its own thread; menu picks are forwarded to the GTK
    thread with GLib.idle_add. The menu text is shared with the Linux tray
    (native/sni.py) so both platforms say the same thing."""

    CLASS = "D2OverlayTray"

    def __init__(self, on_command, overlay_hidden: bool):
        super().__init__(daemon=True)
        self.on_command = on_command
        self._hidden = bool(overlay_hidden)
        self.hwnd = None
        self.started_ok = threading.Event()
        self._proc = None
        self._nid = None
        self._taskbar_created = 0

    # -- run on the tray thread ----------------------------------------------

    def run(self):
        from gi.repository import GLib
        self._glib = GLib
        shell32 = ctypes.windll.shell32
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.CreateWindowExW.restype = wintypes.HWND
        self._proc = WNDPROC(self._wndproc)   # keep referenced: ctypes callbacks must not be GC'd
        wc = WNDCLASSW()
        wc.style = CS_DBLCLKS
        wc.lpfnWndProc = self._proc
        wc.hInstance = kernel32.GetModuleHandleW(None)
        wc.lpszClassName = self.CLASS
        user32.RegisterClassW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(0, self.CLASS, "diablo2-ocular-assist", WS_OVERLAPPED,
                                           0, 0, 0, 0, None, None, wc.hInstance, None)
        if not self.hwnd:
            print("tray: could not create the message window", file=sys.stderr)
            self.started_ok.set()
            return
        self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        icon = None
        if getattr(sys, "frozen", False):
            icon = shell32.ExtractIconW(wc.hInstance, sys.executable, 0)
        if not icon:
            icon = user32.LoadIconW(None, wintypes.LPCWSTR(IDI_APPLICATION))
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = icon
        nid.szTip = "Diablo II overlay"
        self._nid = nid
        self._add_icon()
        self.started_ok.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _add_icon(self):
        shell32 = ctypes.windll.shell32
        if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._nid)):
            print("tray: Shell_NotifyIcon failed", file=sys.stderr)
            return
        self._nid.uVersion = NOTIFYICON_VERSION_4
        shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(self._nid))

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            event = lparam & 0xFFFF
            if event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                self._popup()
            elif event == WM_LBUTTONDBLCLK:
                self._dispatch("settings")
            return 0
        if msg == self._taskbar_created and self._nid is not None:
            self._add_icon()          # explorer restarted: the icon is gone, add it back
            return 0
        if msg == WM_DESTROY:
            if self._nid is not None:
                ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _popup(self):
        from . import sni
        menu = user32.CreatePopupMenu()
        for item_id, props in sni.menu_items(self._hidden):
            if props.get("type") == "separator":
                user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            else:
                user32.AppendMenuW(menu, MF_STRING, item_id, props["label"])
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        user32.SetForegroundWindow(self.hwnd)   # otherwise the menu will not dismiss on click-away
        picked = user32.TrackPopupMenu(menu, TPM_RETURNCMD | TPM_NONOTIFY | TPM_RIGHTBUTTON,
                                       point.x, point.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        command = sni.command_for(int(picked)) if picked else None
        if command:
            self._dispatch(command)

    def _dispatch(self, command):
        self._glib.idle_add(lambda c=command: (self.on_command(c), False)[1])

    # -- interface used by the Session (GTK thread) --------------------------

    def set_overlay_hidden(self, hidden: bool):
        self._hidden = bool(hidden)      # the menu is rebuilt on every right-click

    def close(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)


def tray_icon(on_command, overlay_hidden: bool):
    tray = WinTray(on_command, overlay_hidden)
    tray.start()
    tray.started_ok.wait(2)
    if not tray.hwnd:
        return None
    print("tray: icon added (double-click: settings, right click: menu)", flush=True)
    return tray


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
