"""Work around gtk4-layer-shell's linking requirement under Python.

gtk4-layer-shell has to be linked ahead of libwayland-client. A Python process
loads libwayland first (via PyGObject), so the library's hooks never take effect
and every layer-shell call is silently ignored -- the window falls back to being
an ordinary, focusable, non-transparent toplevel.

The upstream fix is LD_PRELOAD. Rather than making that the caller's problem,
`ensure()` re-executes the interpreter once with the preload in place. Call it
before importing anything from gi.

See https://github.com/wmww/gtk4-layer-shell/blob/main/linking.md
"""

import os
import sys

# The library itself, not the liblayer-shell-preload.so shim that ships beside
# it -- the shim was measured to leave the layer surface uninitialised here,
# while preloading the real library works.
_PRELOAD = "/usr/lib/libgtk4-layer-shell.so"
_GUARD = "D2_OVERLAY_PRELOADED"


def ensure():
    """Re-exec with LD_PRELOAD set, unless that has already happened."""
    if os.environ.get(_GUARD):
        return
    if not os.path.exists(_PRELOAD):
        # Not fatal on its own: some builds link correctly without help. Warn
        # rather than exit, so the failure mode is a visible message and not a
        # mysteriously ordinary window.
        print(
            f"warning: {_PRELOAD} not found; layer-shell may not work",
            file=sys.stderr,
        )
        return

    existing = os.environ.get("LD_PRELOAD", "")
    os.environ["LD_PRELOAD"] = f"{_PRELOAD}:{existing}" if existing else _PRELOAD
    os.environ[_GUARD] = "1"
    os.execv(sys.executable, [sys.executable] + sys.argv)
