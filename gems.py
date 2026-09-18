"""The seven gem types and five grades, for the gem helper overlay.

Traderie only prices Perfect gems (the lower grades never trade on their
own), so those are the snapshot and the rest are derived from the Horadric
Cube's 3:1 upgrade -- each grade is worth a third of the one above it.
"""

from __future__ import annotations

from decimal import Decimal

GEMS = ("Amethyst", "Diamond", "Emerald", "Ruby", "Sapphire", "Topaz", "Skull")
# Ascending, as the cube upgrades them. In-game a plain gem has no prefix;
# "Normal" is the community's name for it.
GRADES = ("Chipped", "Flawed", "Normal", "Flawless", "Perfect")
GRADE_SHORT = {"Chipped": "Chip", "Flawed": "Flwd", "Normal": "Norm",
               "Flawless": "Flwls", "Perfect": "Perf"}
UPGRADE_RATIO = 3   # cube: 3 of a grade -> 1 of the next

# Perfect gems in Traderie's "High Rune Value" unit (HR), as for runes.
# Snapshot of https://traderie.com/api/diablo2resurrected/items/values taken
# 2026-09-19 (tools/traderie_values.py prints the current figures).
VALUES_UNIT = "HR"
VALUES_SOURCE = "traderie.com, Sep 2026"
PERFECT_VALUES = {
    "Amethyst": 0.0027,
    "Diamond": 0.0008, "Emerald": 0.0008, "Ruby": 0.0008, "Sapphire": 0.0008,
    "Topaz": 0.0008, "Skull": 0.0008,
}

MIN_COLUMNS, MAX_COLUMNS = 1, 7
SORTS = ("name", "value")


def name(gem: str, grade: str = "Perfect") -> str:
    """In-game item name: "Perfect Ruby", "Ruby", "Chipped Ruby"."""
    return gem if grade == "Normal" else f"{grade} {gem}"


def value(gem: str, grade: str = "Perfect") -> float:
    """Trade value in HR. Lower grades are a third per step below Perfect."""
    steps = len(GRADES) - 1 - GRADES.index(grade)
    return PERFECT_VALUES[gem] / UPGRADE_RATIO ** steps


def format_value(hr: float) -> str:
    """Shorthand HR like runes.format_value, but to two significant figures
    however small: a chipped gem is worth so little that four decimals would
    print as nothing."""
    text = format(Decimal(f"{hr:.2g}"), "f").rstrip("0").rstrip(".")
    return text[1:] if text.startswith("0.") else text


def ordered(sort: str = "name") -> list[str]:
    """Gems in list order, or most valuable first (ties keep list order)."""
    if sort == "value":
        return sorted(GEMS, key=lambda g: -PERFECT_VALUES[g])
    return list(GEMS)


def table(columns: int = 2, values: bool = False, sort: str = "name") -> list[str]:
    """Perfect gems only: "Name   val" cells down each column then across,
    like the rune table."""
    columns = max(MIN_COLUMNS, min(MAX_COLUMNS, int(columns)))
    names = ordered(sort)
    rows = -(-len(names) // columns)
    width = max(len(g) for g in GEMS)
    texts = {g: format_value(PERFECT_VALUES[g]) for g in GEMS}
    vwidth = max(len(t) for t in texts.values())
    lines = []
    for row in range(rows):
        cells = []
        for col in range(columns):
            index = col * rows + row
            if index < len(names):
                gem = names[index]
                cell = f"{gem:<{width}}"
                if values:
                    cell += f" {texts[gem]:>{vwidth}}"
                cells.append(cell)
        lines.append("   ".join(cells).rstrip())
    return lines


def grade_table(values: bool = True, sort: str = "name") -> list[str]:
    """Every grade: one row per gem, one column per grade (Chipped ...
    Perfect), a header row of grade names on top. With values each cell is
    that gem's HR; without, the header alone says the order."""
    names = ordered(sort)
    width = max(len(g) for g in GEMS)
    cells = {(g, gr): format_value(value(g, gr)) for g in GEMS for gr in GRADES}
    col = max(max(len(t) for t in cells.values()), max(len(s) for s in GRADE_SHORT.values()))
    header = " " * width + "".join(f"  {GRADE_SHORT[gr]:>{col}}" for gr in GRADES)
    lines = [header]
    for gem in names:
        line = f"{gem:<{width}}"
        if values:
            line += "".join(f"  {cells[gem, gr]:>{col}}" for gr in GRADES)
        lines.append(line.rstrip())
    return lines
