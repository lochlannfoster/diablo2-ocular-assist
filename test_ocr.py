import areas
import ocr

NAMES = areas.screen_names(areas.load())


def test_exact_and_garbled_names_match():
    cases = {
        "SPIDER F®REST": "Spider Forest",
        "C0ld P1ains": "Cold Plains",
        "Stony  Fie1d": "Stony Field",
        "BLack [TTARSH": "Black Marsh",
        "R®GUE ENCAMPMENT": "Rogue Encampment",
        "The W0rldstone Keep Leve1 2": "The Worldstone Keep Level 2",
    }
    for text, expected in cases.items():
        assert ocr.match(text, NAMES)[0] == expected, text


def test_level_numbers_are_distinguished():
    for n in (1, 2, 3, 4):
        assert ocr.match(f"CATACOMBS LEVEL {n}", NAMES) == (f"Catacombs Level {n}", 1.0)
    assert ocr.match("CATACOMBS LEVEL l", NAMES)[0] == "Catacombs Level 1"
    assert ocr.match("TOWER CELLAR LEVEL S", NAMES)[0] == "Tower Cellar Level 5"


def test_recognise_picks_the_area_line():
    raw = "[1:25 AT\nSPIDER F®REST\nDIFFICULTY: NIGHTMARE\n"
    reading = ocr.recognise(raw, NAMES)
    assert reading.area == "Spider Forest"
    assert reading.score > 0.9


def test_recognise_rejects_junk():
    assert ocr.recognise("", NAMES).area is None
    assert ocr.recognise("[1:25 AT\nDIFFICULTY: NIGHTMARE\n", NAMES).area is None
    assert ocr.recognise("PRESS ESC TO CANCEL\n", NAMES).area is None


def test_difficulty_is_read_despite_ocr_noise():
    assert ocr.read_difficulty("DIFFICULTY: NIGHTITIARE") == "nightmare"
    assert ocr.read_difficulty("X SDIFFICULTY: NIGHTMARE") == "nightmare"
    assert ocr.read_difficulty("DIFFICULTY: N®RMAL") == "normal"
    assert ocr.read_difficulty("DIFFICULTY: HELL") == "hell"
    assert ocr.read_difficulty("SPIDER FOREST") is None
    reading = ocr.recognise("[1:25 AT\nSPIDER F®REST\nDIFFICULTY: HELL\n", NAMES)
    assert (reading.area, reading.difficulty) == ("Spider Forest", "hell")


def test_leading_the_is_ignored():
    assert ocr.match("THE CAVE LEVEL 1", NAMES) == ("Cave Level 1", 1.0)
    assert ocr.match("PANDEMONIUM FORTRESS", NAMES) == ("The Pandemonium Fortress", 1.0)
