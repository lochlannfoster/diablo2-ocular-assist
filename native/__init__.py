"""The operating-system layer.

Everything that differs between Linux (KDE Wayland) and Windows lives in one
of the two backend modules; the rest of the program only ever imports this
package. The interface, implemented by both backends:

    init()                            before GTK is imported (Linux: LD_PRELOAD re-exec)
    prepare_window(win)               overlay toplevel, before it is realized
    on_realize(win, overlay)          after it has a surface: click-through, topmost...
    set_placement(win, anchor, mx, my)  corner + margins
    set_monitor(win, output)          which output the overlay is on ("" = default)
    monitor_size(win) -> (w, h)|None  size of the overlay's monitor, in the same
                                      units as the margins
    set_click_through(win, enabled)   True = every click goes to the game
    set_opacity(win, alpha)           Windows: layered-window alpha (CSS alpha is
                                      unavailable there); Linux: no-op, CSS does it
    capture_backend(capture_config)   object with .grab(region) / .window_size()
    hotkey_bridge(on_command)         object with .start() / .stop()
    game_is_running() -> bool
    tesseract_command() -> list[str]  how to invoke tesseract
    HAS_CONTROL_SOCKET                unix-socket --ctl support
    config_dir() -> Path              where config.toml lives (next to the exe when frozen)
"""

from __future__ import annotations

import sys

IS_WINDOWS = sys.platform.startswith("win")

if IS_WINDOWS:
    from . import windows as impl
else:
    from . import linux as impl

init = impl.init
prepare_window = impl.prepare_window
on_realize = impl.on_realize
set_placement = impl.set_placement
set_monitor = impl.set_monitor
monitor_size = impl.monitor_size
set_click_through = impl.set_click_through
set_opacity = impl.set_opacity
capture_backend = impl.capture_backend
hotkey_bridge = impl.hotkey_bridge
game_is_running = impl.game_is_running
tesseract_command = impl.tesseract_command
config_dir = impl.config_dir
HAS_CONTROL_SOCKET = impl.HAS_CONTROL_SOCKET
