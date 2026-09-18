"""config.toml: defaults, loading and writing.

The stdlib has `tomllib` for reading but nothing for writing, and the schema
here is tiny and flat (scalars in four tables), so the writer is a template
rather than a general TOML serialiser. Comments are regenerated from the
template every save; the settings window is the editor, not a text editor.
"""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path

from native import config_dir  # noqa: E402

CONFIG_PATH = config_dir() / "config.toml"

ANCHORS = ("top-left", "top-right", "bottom-left", "bottom-right")

# Section key -> label shown in the settings window, in overlay order.
SECTIONS = {
    "waypoint": "Waypoint",
    "next": "Next area",
    "farm": "Farm routes",
    "quests": "Quests",
    "exp": "Exp ranges",
    "drops": "Drops",
    "notes": "Notes",
    "uniques": "Superuniques",
}

DEFAULTS = {
    "capture": {
        "backend": "xwayland",
        "display": ":1",
        "interval": 1.0,
        "region": {"x": 0.84, "y": 0.02, "w": 0.155, "h": 0.09},
    },
    "overlay": {
        "output": "",
        "anchor": "top-right",
        "margin_x": 12,
        "margin_y": 122,
        "font_size": 15,
        "width": 60,
        "hotkeys": True,
        "follow_focus": True,
        "hide_unread": True,
        "sections": {key: True for key in SECTIONS},
    },
}

TEMPLATE = """\
# diablo2-overlay configuration. Edited by the settings window; comments are
# regenerated on every save.

[capture]
backend = {backend}          # only backend so far; D2R under Proton is an X client
display = {display}          # Xwayland display (check: echo $DISPLAY)
interval = {interval}        # seconds between reads

# Where the area name is, as fractions of the game window (the clock / area /
# difficulty block in the top-right corner).
[capture.region]
x = {rx}
y = {ry}
w = {rw}
h = {rh}

[overlay]
output = {output}            # monitor the game is on, by connector; "" = compositor default
anchor = {anchor}            # top-left | top-right | bottom-left | bottom-right
margin_x = {margin_x}        # logical (scaled) pixels from the side edge
margin_y = {margin_y}        # logical pixels from the top/bottom edge
font_size = {font_size}
width = {width}              # minimum characters per line; long tips wrap
hotkeys = {hotkeys}          # read /dev/input for Ctrl+F9..F12 while D2R runs
follow_focus = {follow_focus}  # show the overlay only while the game window is focused
hide_unread = {hide_unread}   # hide it while the area name cannot be read (map off, menus)

[overlay.sections]
{sections}
"""


class ConfigError(Exception):
    pass


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load(path: Path = CONFIG_PATH) -> dict:
    """Read the file and fill in anything missing from DEFAULTS."""
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        data = {}
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path.name}: {exc}")
    config = _merge(DEFAULTS, data)
    if config["overlay"]["anchor"] not in ANCHORS:
        raise ConfigError(f"anchor must be one of {', '.join(ANCHORS)}")
    return config


def _toml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"


def dumps(config: dict) -> str:
    cap, ov = config["capture"], config["overlay"]
    region = cap["region"]
    sections = "\n".join(
        f"{key} = {_toml_bool(bool(ov['sections'].get(key, True)))}" for key in SECTIONS
    )
    return TEMPLATE.format(
        backend=_toml_str(str(cap["backend"])),
        display=_toml_str(str(cap["display"])),
        interval=float(cap["interval"]),
        rx=round(float(region["x"]), 4), ry=round(float(region["y"]), 4),
        rw=round(float(region["w"]), 4), rh=round(float(region["h"]), 4),
        output=_toml_str(str(ov["output"])),
        anchor=_toml_str(str(ov["anchor"])),
        margin_x=int(ov["margin_x"]), margin_y=int(ov["margin_y"]),
        font_size=int(ov["font_size"]), width=int(ov["width"]),
        hotkeys=_toml_bool(bool(ov["hotkeys"])),
        follow_focus=_toml_bool(bool(ov.get("follow_focus", True))),
        hide_unread=_toml_bool(bool(ov.get("hide_unread", True))),
        sections=sections,
    )


def save(config: dict, path: Path = CONFIG_PATH) -> None:
    """Write atomically: a crash mid-write must not leave a half file."""
    text = dumps(config)
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(text)
    tmp.replace(path)
