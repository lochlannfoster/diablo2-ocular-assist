"""Load and validate the area rules in data/areas.toml.

Validation is strict on load so a typo in the data file shows up as one clear
message in the overlay rather than as a hint that silently never appears.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DATA_PATH = Path(__file__).parent / "data" / "areas.toml"

# dir value -> label shown in the overlay. See the header of data/areas.toml
# for what each value means.
LABELS = {
    # relative to how your character faces on arriving (or at the waypoint)
    "left": "TURN LEFT",
    "straight": "STRAIGHT",
    "right": "TURN RIGHT",
    "back": "TURN BACK",
    # outdoor shape rules
    "corner": "A CORNER",
    "edge": "AN EDGE",
    "opposite": "OPPOSITE",
    "near": "RIGHT HERE",
    "inside": "INSIDE",
    "path": "FOLLOW PATH",
    # layout classes
    "fixed": "FIXED MAP",
    "random": "NO RULE",
    "none": "-",
}
GLYPHS = LABELS  # backwards-compatible name

CONFIDENCE = ("high", "medium", "low")
DIFFICULTIES = {"normal": 0, "nightmare": 1, "hell": 2}


class AreaError(Exception):
    pass


@dataclass(frozen=True)
class Hint:
    dir: str
    tip: str

    @property
    def label(self) -> str:
        return LABELS[self.dir]

    glyph = label

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
    levels: tuple[int, int, int] = (0, 0, 0)   # Normal, Nightmare, Hell; 0 = town
    quests: tuple[str, ...] = ()
    uniques: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def level(self, difficulty: str | None) -> int | None:
        """Area level for a difficulty name, or None if unknown / town."""
        index = DIFFICULTIES.get(difficulty or "")
        if index is None:
            return None
        return self.levels[index] or None

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
            levels = tuple(int(x) for x in raw.get("levels", (0, 0, 0)))
            quests = tuple(str(q) for q in raw.get("quests", ()))
            uniques = tuple(str(q) for q in raw.get("uniques", ()))
            notes = tuple(str(q) for q in raw.get("notes", ()))
        except (KeyError, TypeError, ValueError) as exc:
            raise AreaError(f"{name}: {exc}")
        if len(levels) != 3:
            raise AreaError(f"{name}: levels must be [normal, nightmare, hell]")
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
            levels=levels,
            quests=quests,
            uniques=uniques,
            notes=notes,
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


# Highest rune tier each act's "Good" treasure class reaches, per difficulty
# (purediablo rune-farming table). Monsters whose level is high enough get
# upgraded to later acts' tables, which is why Hell alvl 78+ can drop Zod
# anywhere; those thresholds are handled in drop_note().
_RUNE_TIERS = {
    "normal":    (None, "Nef", "Ral", "Sol", "Dol"),
    "nightmare": ("Io", "Ko", "Lem", "Um", "Ist"),
    "hell":      ("Vex", "Lo", "Ber", "Cham", "Zod"),
}


def drop_note(act: int, difficulty: str, alvl: int | None) -> str | None:
    """One line on what can drop here in this difficulty, or None for towns.

    Hell thresholds: TC 87 (every item) needs mlvl 87 = a champion in an
    alvl 85 area; Zod needs unique mlvl 81 (alvl 78), champion (79) or a
    regular monster (81+).
    """
    if not alvl:
        return None
    if difficulty == "hell":
        if alvl >= 85:
            return f"Hell alvl {alvl}: every item and rune in the game can drop here."
        if alvl >= 81:
            return f"Hell alvl {alvl}: any rune incl. Zod; TC87 items need alvl 85."
        if alvl >= 78:
            return f"Hell alvl {alvl}: Zod from uniques/champions only; TC87 items need alvl 85."
    top = _RUNE_TIERS[difficulty][act - 1]
    runes = f"runes up to {top}" if top else "no runes from regular monsters"
    return (f"{difficulty.capitalize()} alvl {alvl}: items up to qlvl {alvl} "
            f"(uniques {alvl + 3}); {runes} for act {act} {difficulty}.")


def exp_bands(alvl: int) -> dict[str, tuple[int, int]]:
    """Recommended character-level bands for an area level.

    Diablo II pays 100% experience while clvl is within 5 of the monster
    level (alvl in Nightmare/Hell), then 81/62/43/24% at a difference of
    6/7/8/9 and 5% from 10 on. From clvl 25 monsters *above* you scale by
    clvl/mlvl instead, which is milder -- but that far below the area level
    you have other problems, so the bands are kept symmetric.
    """
    return {
        "good": (max(1, alvl - 5), min(99, alvl + 5)),
        "avg_low": (max(1, alvl - 8), max(1, alvl - 6)),
        "avg_high": (min(99, alvl + 6), min(99, alvl + 8)),
        "bad_low": (1, max(1, alvl - 9)),
        "bad_high": (min(99, alvl + 9), 99),
    }


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
