"""config.toml: defaults, loading and writing.

The stdlib has `tomllib` for reading but nothing for writing, and the schema
here is tiny and flat (scalars in four tables), so the writer is a template
rather than a general TOML serialiser. Comments are regenerated from the
template every save; the settings window is the editor, not a text editor.
"""

from __future__ import annotations

import copy
import sys
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
    "exp": "Recommended clvl",
    "drops": "Drops",
    "notes": "Notes",
    "uniques": "Superuniques",
}

# Section presets. "all" and "custom" ([overlay.sections]) always exist;
# these two are written into a new config.toml and can be edited or deleted.
BUILTIN_PROFILES = ("all", "custom")
DEFAULT_PROFILES = {
    "speedrun": ["waypoint", "next", "quests"],
    "farming": ["farm", "drops", "uniques", "exp"],
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
        "font": "Hack",
        "opacity": 0.82,
        "padding": 12,
        "width": 60,
        "hotkeys": True,
        "follow_focus": True,
        "hide_unread": True,
        "compact": False,
        "profile": "all",
        "sections": {key: True for key in SECTIONS},
        "profiles": {},
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
font = {font}                # monospace family; falls back to any monospace
opacity = {opacity}          # background scrim alpha, 0.2-1.0
padding = {padding}          # px inside the box
width = {width}              # minimum characters per line; long tips wrap
hotkeys = {hotkeys}          # read /dev/input for Ctrl+F9..F12 while D2R runs
follow_focus = {follow_focus}  # show the overlay only while the game window is focused
hide_unread = {hide_unread}   # hide it while the area name cannot be read (map off, menus)
compact = {compact}          # one terse line per section (Ctrl+Shift+F9)
profile = {profile}          # all | custom | a name from [overlay.profiles] (Ctrl+Shift+F10)

[overlay.sections]           # the "custom" profile
{sections}

# Named section sets, cycled with Ctrl+Shift+F10. "all" and "custom" (the
# block above) always exist; add, edit or delete entries freely.
[overlay.profiles]
{profiles}
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
    ov = config["overlay"]
    if "profiles" not in data.get("overlay", {}):
        # Seed only when the table is absent, so a deleted default stays deleted.
        ov["profiles"] = copy.deepcopy(DEFAULT_PROFILES)
    for name, keys in ov["profiles"].items():
        if name in BUILTIN_PROFILES:
            raise ConfigError(f"[overlay.profiles] {name!r} is a built-in profile name")
        if not isinstance(keys, list) or any(k not in SECTIONS for k in keys):
            raise ConfigError(f"[overlay.profiles] {name} must be a list of: {', '.join(SECTIONS)}")
    if ov["profile"] not in profile_names(ov):
        print(f"warning: unknown profile {ov['profile']!r}; using 'all'", file=sys.stderr)
        ov["profile"] = "all"
    return config


# -- profiles ---------------------------------------------------------------

def profile_names(ov: dict) -> list[str]:
    return [*BUILTIN_PROFILES, *sorted(ov.get("profiles", {}))]


def active_sections(ov: dict) -> dict[str, bool]:
    """Which sections the current profile shows, as key -> bool."""
    name = ov.get("profile", "all")
    if name == "all":
        return {key: True for key in SECTIONS}
    if name in ov.get("profiles", {}):
        chosen = set(ov["profiles"][name])
        return {key: key in chosen for key in SECTIONS}
    return {key: bool(ov["sections"].get(key, True)) for key in SECTIONS}   # custom / unknown


def next_profile(ov: dict) -> str:
    names = profile_names(ov)
    current = ov.get("profile", "all")
    index = names.index(current) if current in names else -1
    return names[(index + 1) % len(names)]


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
    profiles = "\n".join(
        f"{_toml_str(name)} = [{', '.join(_toml_str(k) for k in keys)}]"
        for name, keys in sorted(ov.get("profiles", {}).items())
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
        font=_toml_str(str(ov.get("font", "Hack"))),
        opacity=round(float(ov.get("opacity", 0.82)), 2),
        padding=int(ov.get("padding", 12)),
        hotkeys=_toml_bool(bool(ov["hotkeys"])),
        follow_focus=_toml_bool(bool(ov.get("follow_focus", True))),
        hide_unread=_toml_bool(bool(ov.get("hide_unread", True))),
        sections=sections,
        profiles=profiles,
        compact=_toml_bool(bool(ov.get("compact", False))),
        profile=_toml_str(str(ov.get("profile", "all"))),
    )


def save(config: dict, path: Path = CONFIG_PATH) -> None:
    """Write atomically: a crash mid-write must not leave a half file."""
    text = dumps(config)
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(text)
    tmp.replace(path)
