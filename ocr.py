"""Turn the top-right corner of the screen into an area name.

D2R draws three lines there: the in-game clock, the area name, and the
difficulty. Tesseract reads the raw crop well enough as-is (measured on a live
frame: "SPIDER F®REST"), and the vocabulary is closed -- every area name is
listed in data/areas.toml -- so recognition is a fuzzy match over ~150 strings
rather than a demand for perfect OCR. Anything under `MIN_SCORE` is treated as
"nothing readable", which is what the corner looks like on menus, loading
screens and the character select.
"""

from __future__ import annotations

import difflib
import re
import subprocess
from dataclasses import dataclass

from PIL import Image, ImageOps

# Below this similarity the best candidate is just the closest wrong answer.
MIN_SCORE = 0.75

# Lines that can never be an area name; skipping them saves a fuzzy pass and
# stops "Difficulty: Normal" from ever competing with a real name.
_SKIP = re.compile(r"difficulty|^\s*\d{1,2}:\d{2}|^\s*$", re.IGNORECASE)
_NOISE = re.compile(r"[^A-Za-z0-9' ]+")

# Tesseract's usual misreads of a lone digit after "Level". Only applied in
# that position: elsewhere a stray "i" is far more likely to be a letter.
_DIGIT_FIXES = {"i": "1", "l": "1", "|": "1", "!": "1", "z": "2", "s": "5",
                "b": "6", "g": "9", "o": "0"}


_DIFFICULTY = re.compile(r"difficulty\W*([^\n]+)", re.IGNORECASE)
_DIFFICULTY_NAMES = ("normal", "nightmare", "hell")


@dataclass(frozen=True)
class Reading:
    raw: str          # what tesseract returned, all lines
    area: str | None  # best matching area name, or None
    score: float      # similarity of that match (0..1)
    difficulty: str | None = None  # "normal" | "nightmare" | "hell"


def read_difficulty(raw: str) -> str | None:
    """The difficulty line, fuzzy-matched the same way as area names
    ("NIGHTITIARE" is what tesseract makes of the game's font)."""
    found = _DIFFICULTY.search(raw)
    if not found:
        return None
    word = normalise(found.group(1))
    best, best_score = None, 0.0
    for name in _DIFFICULTY_NAMES:
        score = difflib.SequenceMatcher(None, word, name).ratio()
        if score > best_score:
            best, best_score = name, score
    return best if best_score >= 0.6 else None


def preprocess(image: Image.Image, scale: int = 2) -> Image.Image:
    """Grayscale and upscale. Kept mild on purpose: thresholding the gold text
    against dark terrain produced *more* errors on a real frame than leaving
    the anti-aliasing alone."""
    gray = ImageOps.grayscale(image)
    if scale != 1:
        gray = gray.resize((gray.width * scale, gray.height * scale), Image.LANCZOS)
    return gray


def run_tesseract(image: Image.Image, timeout: float = 5.0) -> str:
    """OCR one image via the tesseract CLI (stdin -> stdout)."""
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    try:
        result = subprocess.run(
            ["tesseract", "stdin", "stdout", "--psm", "6", "-l", "eng"],
            input=buffer.getvalue(), capture_output=True, timeout=timeout,
        )
    except FileNotFoundError:
        raise RuntimeError("tesseract not installed (pacman -S tesseract tesseract-data-eng)")
    except subprocess.TimeoutExpired:
        return ""
    return result.stdout.decode("utf-8", "replace")


def normalise(text: str) -> str:
    words = _NOISE.sub(" ", text).lower().split()
    # The game prefixes some names with "The" inconsistently between the
    # on-screen label and the wikis; ignore it on both sides.
    if words and words[0] == "the":
        words = words[1:]
    for i in range(1, len(words)):
        if words[i - 1] == "level" and len(words[i]) == 1:
            words[i] = _DIGIT_FIXES.get(words[i], words[i])
    return " ".join(words)


def match(text: str, names: list[str]) -> tuple[str | None, float]:
    """Best area name for one OCR line, with its similarity score."""
    cleaned = normalise(text)
    if not cleaned:
        return None, 0.0
    best, best_score = None, 0.0
    for name in names:
        score = difflib.SequenceMatcher(None, cleaned, normalise(name)).ratio()
        if score > best_score:
            best, best_score = name, score
    return best, best_score


def recognise(raw: str, names: list[str]) -> Reading:
    """Pick the area name out of the whole OCR output."""
    best, best_score = None, 0.0
    for line in raw.splitlines():
        if _SKIP.search(line):
            continue
        candidate, score = match(line, names)
        if score > best_score:
            best, best_score = candidate, score
    difficulty = read_difficulty(raw)
    if best_score < MIN_SCORE:
        return Reading(raw, None, best_score, difficulty)
    return Reading(raw, best, best_score, difficulty)


def read_area(image: Image.Image, names: list[str]) -> Reading:
    """Capture crop in, Reading out."""
    return recognise(run_tesseract(preprocess(image)), names)
