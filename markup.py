"""Pango-markup builders for the overlay text.

Kept free of GTK so the strings can be unit-tested: everything here returns
plain str containing Pango markup. overlay.py only glues these onto labels.
"""

from __future__ import annotations

from xml.sax.saxutils import escape as _xml_escape

# One accent colour per section: the header word is drawn in it, the body
# text stays neutral (overlay.css .hint) so the eye finds the section by
# colour and reads the tip in one shade.
SECTION_COLOURS = {
    "wp": "#7fc8ff",
    "next": "#9be59b",
    "farm": "#f2a65a",
    "quest": "#e8c46a",
    "exp": "#c9d6d1",
    "drops": "#c7a3ff",
    "notes": "#8fd3d3",
    "uniques": "#d4a24c",
    "immune": "#ff8080",
    "runes": "#e8c46a",     # rune helper box header
    "gems": "#c7a3ff",      # gem helper box header
}
# Rune names by the lowest difficulty that drops them (runes.tier).
TIER_COLOURS = {"normal": "#9aa5a1", "nightmare": "#f2a65a", "hell": "#c7a3ff"}
DIM = "#8a9a94"           # parentheticals: "(from waypoint)", "still ok"
GOOD = "#00ff9c"          # the recommended clvl band
NORULE = "#ff9f5f"        # "no accepted rule" direction
DIRECTION = "#ffffff"

# A big glyph in front of the direction word: the direction is the one thing
# you read mid-fight, so it gets the most ink.
ARROWS = {
    "left": "←", "straight": "↑", "right": "→", "back": "↓",
    "corner": "◇", "edge": "▭", "opposite": "⇄",
    "near": "◎", "inside": "⊙", "path": "⤳",
    "fixed": "▣", "random": "?", "none": "·",
}


def esc(text: str) -> str:
    return _xml_escape(str(text))


def head(word: str, key: str) -> str:
    """Bold section header word in the section's accent colour."""
    return f'<span foreground="{SECTION_COLOURS[key]}" weight="bold">{esc(word)}</span>'


def dim(text: str) -> str:
    return f'<span foreground="{DIM}">{esc(text)}</span>'


def direction(hint) -> str:
    """'← TURN LEFT': big arrow + bold direction word; orange for 'no rule'."""
    colour = NORULE if hint.no_rule else DIRECTION
    arrow = ARROWS.get(hint.dir, "")
    glyph = f'<span size="x-large">{esc(arrow)}</span> ' if arrow else ""
    return f'<span foreground="{colour}" weight="bold">{glyph}{esc(hint.label)}</span>'


def tier(text: str, difficulty: str) -> str:
    """A rune name in its drop-tier colour: grey, orange or purple."""
    return f'<span foreground="{TIER_COLOURS[difficulty]}">{text}</span>'


def _hex(colour: str) -> tuple[int, int, int]:
    return tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))


def value_colour(value: float, low: float, high: float) -> str:
    """Grey at `low` blending to bright green at `high`, on a log scale, so
    a column of trade values reads as a heat map: Ber glows, El is dull."""
    import math
    if high <= low or value <= low:
        t = 0.0
    else:
        t = min(1.0, math.log(value / low) / math.log(high / low))
    a, b = _hex(DIM), _hex(GOOD)
    r, g, bl = (round(x + (y - x) * t) for x, y in zip(a, b))
    return f"#{r:02x}{g:02x}{bl:02x}"


def valued(text: str, value: float, low: float, high: float) -> str:
    return f'<span foreground="{value_colour(value, low, high)}">{text}</span>'


def band(levels: str, label: str, colour: str = GOOD) -> str:
    """'45–55 recommended': a clvl range, coloured, then its label."""
    return f'<span foreground="{colour}" weight="bold">{esc(levels)}</span> {esc(label)}'


def rng(pair) -> str:
    low, high = pair
    return f"{low}" if low == high else f"{low}–{high}"
