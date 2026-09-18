"""The 33 runes in game order, for the rune helper overlay.

The number is what people mean by "a #23 rune" and what rune-word guides sort
by; the overlay is just this table laid out in columns, optionally with each
rune's trade value next to it.
"""

from __future__ import annotations

RUNES = (
    "El", "Eld", "Tir", "Nef", "Eth", "Ith", "Tal", "Ral", "Ort", "Thul", "Amn",
    "Sol", "Shael", "Dol", "Hel", "Io", "Lum", "Ko", "Fal", "Lem", "Pul", "Um",
    "Mal", "Ist", "Gul", "Vex", "Ohm", "Lo", "Sur", "Ber", "Jah", "Cham", "Zod",
)

# Trade values in Traderie's "High Rune Value" unit (HR), one figure per rune
# regardless of ladder/mode. Community-maintained, so they drift; snapshot of
# https://traderie.com/diablo2resurrected/values taken 2026-09-19.
VALUES_UNIT = "HR"
VALUES_SOURCE = "traderie.com, Sep 2026"
VALUES = {
    "El": 0.0008, "Eld": 0.0008, "Tir": 0.0008, "Nef": 0.0008, "Eth": 0.0008,
    "Ith": 0.0008, "Tal": 0.0008, "Ral": 0.0008, "Ort": 0.0008, "Thul": 0.0008,
    "Amn": 0.0008, "Sol": 0.0008, "Shael": 0.0008, "Dol": 0.0008,
    "Hel": 0.0016, "Io": 0.0016,
    "Lum": 0.01, "Ko": 0.01, "Fal": 0.01,
    "Lem": 0.02, "Pul": 0.04, "Um": 0.06, "Mal": 0.1, "Ist": 0.16, "Gul": 0.25,
    "Vex": 0.5, "Ohm": 0.75, "Lo": 1.25, "Sur": 1.75, "Ber": 3.5, "Jah": 3,
    "Cham": 0.4, "Zod": 0.9,
}

# Highest difficulty you have to be in for the rune to drop at all (from
# monsters and chests; the Hellforge and Countess have their own tables).
# Act 5 Normal tops out at Dol, Act 5 Nightmare at Ist, Hell goes to Zod.
TIERS = (("normal", "Dol"), ("nightmare", "Ist"), ("hell", "Zod"))

MIN_COLUMNS, MAX_COLUMNS = 1, 6
SORTS = ("number", "value")


def number(name: str) -> int:
    """1-based position of a rune, by name (case-insensitive)."""
    return [r.lower() for r in RUNES].index(name.strip().lower()) + 1


def value(name: str) -> float:
    """Trade value of a rune in HR, by name (case-insensitive)."""
    return VALUES[RUNES[number(name) - 1]]


def tier(name: str) -> str:
    """'normal' | 'nightmare' | 'hell': the lowest difficulty that drops it."""
    n = number(name)
    for difficulty, top in TIERS:
        if n <= number(top):
            return difficulty
    raise ValueError(name)


def format_value(hr: float) -> str:
    """Shorthand HR: "3.5", "3", ".16", ".0008" -- no leading zero, no
    trailing zeros, so a column of them stays narrow."""
    text = f"{hr:.4f}".rstrip("0").rstrip(".")
    return text[1:] if text.startswith("0.") else text


def ordered(sort: str = "number") -> list[str]:
    """Runes by number, or most valuable first (ties keep number order)."""
    if sort == "value":
        return sorted(RUNES, key=lambda r: -VALUES[r])
    return list(RUNES)


def table(columns: int = 3, values: bool = False, sort: str = "number",
          style=None) -> list[str]:
    """Lines of "nn Name" cells (or "nn Name   val" with values), laid down
    each column then across, so the list reads top-to-bottom like the game's
    own ordering -- or, sorted by value, from Ber down to El.

    `style(name, field, text)` may wrap the padded name ("name") or value
    ("value") text of a rune in markup; padding is done before it is called
    so the columns still line up."""
    style = style or (lambda name, field, text: text)
    columns = max(MIN_COLUMNS, min(MAX_COLUMNS, int(columns)))
    names = ordered(sort)
    rows = -(-len(RUNES) // columns)
    width = max(len(r) for r in RUNES)
    # Values line up on the decimal point: "3.5 " over " .16" over "1.25".
    parts = [format_value(v).partition(".") for v in VALUES.values()]
    whole = max(len(w) for w, _, _ in parts)
    frac = max(len(d + f) for _, d, f in parts)
    lines = []
    for row in range(rows):
        cells = []
        for col in range(columns):
            index = col * rows + row
            if index < len(names):
                name = names[index]
                cell = f"{number(name):>2} {style(name, 'name', f'{name:<{width}}')}"
                if values:
                    w, dot, f = format_value(VALUES[name]).partition(".")
                    cell += " " + style(name, "value", f"{w:>{whole}}{dot + f:<{frac}}")
                cells.append(cell)
        lines.append("   ".join(cells).rstrip())
    return lines
