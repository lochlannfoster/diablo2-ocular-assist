"""Load and validate the area rules in data/areas.toml.

Validation is strict on load so a typo in the data file shows up as one clear
message in the overlay rather than as a hint that silently never appears.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DATA_PATH = Path(__file__).parent / "data" / "areas.toml"

# dir value -> glyph shown in the overlay.
GLYPHS = {
    "cw": "↻",
    "ccw": "↺",
    "opposite": "↔",
    "up": "↑",
    "down": "↓",
    "left": "←",
    "right": "→",
    "outer-wall": "⟳",
    "linear": "→→",
    "dead-end": "⊗",
    "none": "?",
}

CONFIDENCE = ("high", "medium", "low")


class AreaError(Exception):
    pass


@dataclass(frozen=True)
class Hint:
    dir: str
    tip: str

    @property
    def glyph(self) -> str:
        return GLYPHS[self.dir]


@dataclass(frozen=True)
class Area:
    name: str
    act: int
    next: str
    has_waypoint: bool
    to_waypoint: Hint
    to_next: Hint
    confidence: str


def _hint(name: str, field: str, raw) -> Hint:
    if not isinstance(raw, dict):
        raise AreaError(f"{name}: {field} must be a table with dir and tip")
    direction = raw.get("dir")
    tip = raw.get("tip", "")
    if direction not in GLYPHS:
        raise AreaError(
            f"{name}: {field}.dir is {direction!r}; expected one of {', '.join(GLYPHS)}"
        )
    if not isinstance(tip, str):
        raise AreaError(f"{name}: {field}.tip must be a string")
    return Hint(direction, tip)


def parse(data: dict) -> dict[str, Area]:
    raw_areas = data.get("area")
    if not isinstance(raw_areas, dict) or not raw_areas:
        raise AreaError("no [area.*] tables found")
    areas: dict[str, Area] = {}
    for name, raw in raw_areas.items():
        try:
            act = int(raw["act"])
            next_name = str(raw.get("next", ""))
            has_waypoint = bool(raw.get("has_waypoint", False))
            confidence = str(raw.get("confidence", "low"))
        except (KeyError, TypeError, ValueError) as exc:
            raise AreaError(f"{name}: {exc}")
        if not 1 <= act <= 5:
            raise AreaError(f"{name}: act must be 1-5, got {act}")
        if confidence not in CONFIDENCE:
            raise AreaError(f"{name}: confidence must be one of {', '.join(CONFIDENCE)}")
        areas[name] = Area(
            name=name,
            act=act,
            next=next_name,
            has_waypoint=has_waypoint,
            to_waypoint=_hint(name, "to_waypoint", raw.get("to_waypoint")),
            to_next=_hint(name, "to_next", raw.get("to_next")),
            confidence=confidence,
        )
    # Every `next` must be a real area, otherwise the overlay would happily
    # point at a place that does not exist.
    for area in areas.values():
        if area.next and area.next not in areas:
            raise AreaError(f"{area.name}: next area {area.next!r} is not defined")
    return areas


def load(path: Path = DATA_PATH) -> dict[str, Area]:
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except OSError as exc:
        raise AreaError(f"cannot read {path}: {exc}")
    except tomllib.TOMLDecodeError as exc:
        raise AreaError(f"{path.name}: {exc}")
    return parse(data)
