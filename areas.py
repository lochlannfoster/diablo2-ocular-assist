"""Load and validate the area rules in data/areas.toml.

Validation is strict on load so a typo in the data file shows up as one clear
message in the overlay rather than as a hint that silently never appears.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DATA_PATH = Path(__file__).parent / "data" / "areas.toml"

# dir value -> glyph shown in the overlay. See the header of data/areas.toml
# for what each value means.
GLYPHS = {
    # character-relative, from the entrance (or the waypoint)
    "left": "↰",
    "straight": "⇧",
    "right": "↱",
    "back": "⇩",
    # compass on the automap
    "n": "↑", "ne": "↗", "e": "→", "se": "↘",
    "s": "↓", "sw": "↙", "w": "←", "nw": "↖",
    # outdoor shape rules
    "corner": "◇",
    "edge": "▭",
    "opposite": "↔",
    "near": "◎",
    "inside": "◌",
    "path": "⤳",
    # layout classes
    "fixed": "▣",
    "random": "??",
    "none": "-",
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

    @property
    def no_rule(self) -> bool:
        """The sources explicitly say there is no rule here."""
        return self.dir == "random"


@dataclass(frozen=True)
class Area:
    name: str
    act: int
    next: str
    has_waypoint: bool
    to_waypoint: Hint
    to_next: Hint
    confidence: str
    source: str = ""
    ocr_name: str = ""   # on-screen name when it differs from the key

    @property
    def screen_name(self) -> str:
        return self.ocr_name or self.name


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
            source = str(raw.get("source", ""))
            ocr_name = str(raw.get("ocr_name", ""))
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
            source=source,
            ocr_name=ocr_name,
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


def screen_names(areas: dict[str, Area]) -> list[str]:
    """Distinct names as they appear on screen -- the OCR vocabulary."""
    return sorted({area.screen_name for area in areas.values()})


def resolve(areas: dict[str, Area], screen_name: str, last_act: int | None) -> Area:
    """The area behind an on-screen name.

    Act 2 and Act 3 both have "Sewers Level 1/2". When a name is ambiguous,
    prefer the entry in the act the player was last seen in; failing that the
    lowest act.
    """
    candidates = [a for a in areas.values() if a.screen_name == screen_name]
    if not candidates:
        raise KeyError(screen_name)
    for area in candidates:
        if area.act == last_act:
            return area
    return min(candidates, key=lambda a: a.act)
