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
from dataclasses import dataclass, field, replace

from PIL import Image, ImageChops

# Below this similarity the best candidate is just the closest wrong answer.
MIN_SCORE = 0.75

# Lines that can never be an area name; skipping them saves a fuzzy pass and
# stops "Difficulty: Normal" from ever competing with a real name.
_SKIP = re.compile(r"difficulty|^\s*game\b|^\W*\d{1,2}:\d{2}|^\s*$|^\W*[A-Za-z]+:", re.IGNORECASE)
_NOISE = re.compile(r"[^A-Za-z0-9' ]+")

# Tesseract's usual misreads of a lone digit after "Level". Only applied in
# that position: elsewhere a stray "i" is far more likely to be a letter.
_DIGIT_FIXES = {"i": "1", "l": "1", "|": "1", "!": "1", "z": "2", "s": "5",
                "b": "6", "g": "9", "o": "0"}


_DIFFICULTY_NAMES = ("normal", "nightmare", "hell")


@dataclass(frozen=True)
class Reading:
    raw: str          # what tesseract returned, all lines
    area: str | None  # best matching area name, or None
    score: float      # similarity of that match (0..1)
    difficulty: str | None = None  # "normal" | "nightmare" | "hell"
    # What tesseract was actually shown (masked + upscaled), for the settings
    # window's OCR detail view. Not part of equality.
    processed: Image.Image | None = field(default=None, compare=False, repr=False)
    # Terror zones read off the purple list. None = the purple pass did not
    # run this frame (keep what we knew); () = it ran and found nothing.
    terror_zones: tuple[str, ...] | None = None
    tz_raw: str = ""


LOWCONF_BELOW = 0.85   # matches under this are worth keeping a crop of


def has_text(raw: str) -> bool:
    """Did tesseract see anything word-like at all (map on, text present)?"""
    return len(re.findall(r"[A-Za-z]", raw)) >= 3


def should_save_lowconf(reading: Reading) -> bool:
    """A frame worth keeping for later: there was text, but it either did
    not match any area or only just did. Blank frames (map off) are not
    interesting; confident reads are not either."""
    if not has_text(reading.raw):
        return False
    return reading.area is None or reading.score < LOWCONF_BELOW


def line_scores(raw: str, names: list[str]) -> list[tuple[str, str | None, float, bool]]:
    """Per OCR line: (line, best candidate, score, skipped). For the OCR
    detail view -- shows exactly why a frame did or did not match."""
    out = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        if _SKIP.search(line):
            out.append((line, None, 0.0, True))
            continue
        candidate, score = match(line, names)
        out.append((line, candidate, score, False))
    return out


def read_difficulty(raw: str) -> str | None:
    """The difficulty line, fuzzy-matched the same way as area names: both
    the label ("DifFrFicuLTY") and the value ("NIGHTITIARE") come out of
    tesseract mangled, so neither is matched literally."""
    for line in raw.splitlines():
        words = line.split()
        for i, label in enumerate(words):
            label = _NOISE.sub("", label).lower()
            if difflib.SequenceMatcher(None, label, "difficulty").ratio() < 0.7:
                continue
            word = normalise(" ".join(words[i + 1:]))
            best, best_score = None, 0.0
            for name in _DIFFICULTY_NAMES:
                score = difflib.SequenceMatcher(None, word, name).ratio()
                if score > best_score:
                    best, best_score = name, score
            if best_score >= 0.6:
                return best
    return None


def gold_only(image: Image.Image) -> Image.Image:
    """Keep the game's gold text, black out everything else.

    The current area is drawn in gold (roughly 220,190,120). Terror zones are
    listed in the same block in purple (150,60,220), and the matcher would
    happily pick one of those -- they are real area names. Gold has
    red > green > blue; purple has blue > green. Masking on that alone drops
    the purple lines (and their anti-aliased edges) before OCR ever sees them.
    """
    r, g, b = image.convert("RGB").split()
    # subtract() clamps at 0, so g-r == 0 <=> r >= g and g-b > 0 <=> g > b.
    return _mask(image, [
        r.point(lambda v: _on(v >= 90)),
        g.point(lambda v: _on(v >= 60)),
        ImageChops.subtract(g, r).point(lambda v: _on(v == 0)),
        ImageChops.subtract(g, b).point(lambda v: _on(v > 0)),
    ])


def purple_only(image: Image.Image) -> Image.Image:
    """Keep the purple terror-zone list, black out everything else -- the
    complement of gold_only. Measured purple is (162,82,252) in the core and
    (110,56,172) on anti-aliased edges; blue dominates both, and gold's blue
    is always below its green."""
    r, g, b = image.convert("RGB").split()
    return _mask(image, [
        r.point(lambda v: _on(v >= 90)),
        b.point(lambda v: _on(v >= 120)),
        ImageChops.subtract(b, g).point(lambda v: _on(v > 0)),   # b > g
    ])


def _on(cond) -> int:
    return 255 if cond else 0


def _mask(image: Image.Image, tests: list[Image.Image]) -> Image.Image:
    keep = tests[0]
    for m in tests[1:]:
        keep = ImageChops.darker(keep, m)
    # convert("L") is the same 299/587/114 luma; multiply zeroes masked pixels.
    return ImageChops.multiply(image.convert("L"), keep)


def preprocess(image: Image.Image, scale: int = 2, mask=gold_only) -> Image.Image:
    """Colour-mask, then upscale. No thresholding: it produced *more* errors on
    a real frame than leaving the anti-aliasing alone."""
    gray = mask(image)
    if scale != 1:
        gray = gray.resize((gray.width * scale, gray.height * scale), Image.LANCZOS)
    return gray


def run_tesseract(image: Image.Image, timeout: float = 5.0) -> str:
    """OCR one image via the tesseract CLI (stdin -> stdout)."""
    import io

    import native

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    try:
        result = subprocess.run(
            [*native.tesseract_command(), "stdin", "stdout", "--psm", "6", "-l", "eng"],
            input=buffer.getvalue(), capture_output=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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


# D2R's small-caps font: every letter is a capital, so lowercase letters in
# the OCR output are misreads. The worst offender is the dotted "O" glyph,
# which tesseract calls "e" ("BLeeD [Meer" for Blood Moor).
_SMALL_CAPS_E = re.compile(r"(?<=[A-Za-z])e|e(?=[A-Za-z])")


def _variants(text: str) -> list[str]:
    fixed = _SMALL_CAPS_E.sub("O", text.replace("[", "").replace("]", ""))
    return [text, fixed] if fixed != text else [text]


def match(text: str, names: list[str]) -> tuple[str | None, float]:
    """Best area name for one OCR line, with its similarity score. The line
    is scored as read and with the small-caps fix applied; the better wins."""
    best, best_score = None, 0.0
    for variant in _variants(text):
        cleaned = normalise(variant)
        if not cleaned:
            continue
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
    # The game only prints a "Difficulty:" line in Nightmare and Hell. It sits
    # between the clock and the area name, so a readable area name with no
    # such line means Normal -- otherwise the last difficulty would stick
    # after starting a new game on Normal.
    return Reading(raw, best, best_score, difficulty or "normal")


def read_area(image: Image.Image, names: list[str]) -> Reading:
    """Capture crop in, Reading out."""
    processed = preprocess(image)
    return replace(recognise(run_tesseract(processed), names), processed=processed)


def read_terror_zones(raw: str, names: list[str]) -> tuple[str, ...]:
    """Area names in the purple list, top to bottom, deduplicated. A header
    line or clock spill never reaches MIN_SCORE against a real name."""
    found = []
    for line in raw.splitlines():
        if not line.strip() or _SKIP.search(line):
            continue
        candidate, score = match(line, names)
        if candidate and score >= MIN_SCORE and candidate not in found:
            found.append(candidate)
    return tuple(found)


def with_terror_zones(image: Image.Image, reading: Reading, names: list[str]) -> Reading:
    """Second tesseract pass over the purple text; the gold pass is reused."""
    raw = run_tesseract(preprocess(image, mask=purple_only))
    return replace(reading, terror_zones=read_terror_zones(raw, names), tz_raw=raw)
