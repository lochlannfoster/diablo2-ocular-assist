# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Windows build (run from an MSYS2 MINGW64 shell).

Produces dist/diablo2-ocular-assist/ with overlay.exe, the GTK runtime, tesseract
and the data files. See .github/workflows/build.yml.
"""

import os
from pathlib import Path

MINGW = Path(os.environ.get("MINGW_PREFIX", "C:/msys64/mingw64"))

datas = [
    ("overlay.css", "."),
    ("data/areas.toml", "data"),
    ("data/superuniques.toml", "data"),
    (str(MINGW / "share/tessdata/eng.traineddata"), "tessdata"),
]
# Listing tesseract.exe as a binary makes PyInstaller pull in the DLLs it
# links against (leptonica, libtesseract, ...) next to it.
binaries = [(str(MINGW / "bin/tesseract.exe"), ".")]

a = Analysis(
    ["overlay.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=["settings", "native.windows", "gi.repository.Gtk", "gi.repository.Gdk",
                   "gi.repository.GLib", "gi.repository.Pango", "gi.repository.GdkPixbuf",
                   "PIL.ImageGrab"],
    hookspath=[],
    excludes=["Xlib", "evdev", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="overlay",
    debug=False,
    strip=False,
    upx=False,
    console=False,       # no console window; native/windows.py redirects output to overlay.log
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="diablo2-ocular-assist",
)
