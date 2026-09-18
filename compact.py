"""Shortening tips for the overlay's compact mode.

The overlay never ellipsises: a compact line is the first sentence of the
tip, cut back to a clause boundary if that is still too long. Whatever is
left is a complete phrase, not a truncated one.
"""

from __future__ import annotations

import re

_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+")
_CLAUSE_SEPS = (", ", "; ", ": ", " - ", " -- ", " — ", " (")
_TRAILING = " ,;:-—(."


def terse(text: str, limit: int = 48) -> str:
    """First sentence of `text`, cut at a clause boundary if longer than
    `limit`. Never appends an ellipsis; never ends on punctuation."""
    text = " ".join(str(text).split())
    if not text:
        return ""
    first = _SENTENCE_END.split(text, 1)[0].rstrip(_TRAILING)
    if len(first) <= limit:
        return first
    # Right-most clause separator that keeps the line within the limit, as
    # long as it leaves at least half a line -- "Randomly" alone helps nobody.
    cut = max((first.rfind(sep, 0, limit + 1) for sep in _CLAUSE_SEPS), default=-1)
    if cut < limit // 2:
        cut = first.rfind(" ", 0, limit + 1)
    if cut <= 0:
        cut = limit
    return first[:cut].rstrip(_TRAILING)
