"""Recognition state: turns a stream of noisy OCR readings into a stable
"you are in X".

Pure Python, no GTK, so the debounce rules are testable on their own.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Recognizer:
    """Commits an area only after `agree` consecutive identical readings.

    A single misread mid-fight would otherwise flash a wrong hint for a second.
    Blank readings (menus, loading screens, the corner covered by a panel) do
    not clear the committed area: you are still where you were, so the overlay
    keeps the last hint and merely dims it.
    """

    agree: int = 2
    area: str | None = None       # committed
    visible: bool = False         # was the last reading readable?
    frozen: bool = False          # Ctrl+F10: stop updating
    difficulty: str = "normal"    # last difficulty read; Normal until the
                                  # "Difficulty:" line has been seen
    _candidate: str | None = field(default=None, repr=False)
    _streak: int = field(default=0, repr=False)

    def feed(self, reading: str | None, difficulty: str | None = None) -> bool:
        """Feed one reading. Returns True if the committed area changed."""
        if self.frozen:
            return False
        if difficulty:
            self.difficulty = difficulty
        self.visible = reading is not None
        if reading is None:
            self._candidate, self._streak = None, 0
            return False
        if reading == self.area:
            self._candidate, self._streak = None, 0
            return False
        if reading == self._candidate:
            self._streak += 1
        else:
            self._candidate, self._streak = reading, 1
        if self._streak >= self.agree:
            self.area = reading
            self._candidate, self._streak = None, 0
            return True
        return False

    def toggle_frozen(self) -> bool:
        self.frozen = not self.frozen
        return self.frozen
