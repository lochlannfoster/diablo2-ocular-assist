from pathlib import Path

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
    # Normal has no difficulty line at all: a clean area name alone means Normal.
    reading = ocr.recognise("@7:34 AM\nROGUE ENCAMPMENT", ["Rogue Encampment"])
    assert (reading.area, reading.difficulty) == ("Rogue Encampment", "normal")
    assert ocr.recognise("@7:34 AM\nGARBLE", ["Rogue Encampment"]).difficulty is None
    reading = ocr.recognise("[1:25 AT\nSPIDER F®REST\nDIFFICULTY: HELL\n", NAMES)
    assert (reading.area, reading.difficulty) == ("Spider Forest", "hell")


def test_leading_the_is_ignored():
    assert ocr.match("THE CAVE LEVEL 1", NAMES) == ("Cave Level 1", 1.0)
    assert ocr.match("PANDEMONIUM FORTRESS", NAMES) == ("The Pandemonium Fortress", 1.0)


def test_gold_mask_drops_purple_terror_zone_text():
    from PIL import Image

    img = Image.new("RGB", (40, 20), (12, 14, 10))          # dark terrain
    img.paste((222, 190, 120), (2, 2, 18, 8))                # gold: current area
    img.paste((150, 60, 220), (2, 12, 18, 18))               # purple: terror zone
    img.paste((90, 90, 90), (22, 2, 38, 8))                  # grey: neither
    out = ocr.gold_only(img)
    assert out.mode == "L"
    assert out.getpixel((8, 4)) > 150                         # gold kept
    assert out.getpixel((8, 14)) == 0                         # purple dropped
    assert out.getpixel((30, 4)) == 0                         # grey dropped
    assert out.getpixel((38, 18)) == 0                        # background dropped


def test_game_name_line_is_skipped():
    raw = "@4:13 PITI\nGAIME: HBT\nROeGUE ENCAMPMENT\n"
    assert ocr.recognise(raw, NAMES).area == "Rogue Encampment"
    assert ocr.recognise("GAME: CRYPT\n", NAMES).area is None


def test_small_caps_o_read_as_e_still_matches():
    # Real frame: tesseract reads D2R's dotted O as "e" and adds a stray "[".
    raw = "@7:14 P\n\nGame: RASI\n\nBLeopD [Meer\nDifFrFicuLTY: NIGHTMARE\n"
    reading = ocr.recognise(raw, NAMES)
    assert reading.area == "Blood Moor" and reading.difficulty == "nightmare"
    assert ocr.match("BLeeD [Meer", NAMES)[0] == "Blood Moor"
    # Genuine E's are unaffected: the unfixed variant still scores 1.0.
    assert ocr.match("DEN OF EVIL", NAMES) == ("Den of Evil", 1.0)


def test_lowconf_predicate():
    from ocr import Reading, should_save_lowconf
    assert not should_save_lowconf(Reading("", None, 0.0))                       # blank: map off
    assert not should_save_lowconf(Reading("@4:13 PM\n", None, 0.3))            # no letters worth it
    assert should_save_lowconf(Reading("BLeopD [Meer", None, 0.66))              # text, no match
    assert should_save_lowconf(Reading("BLeopD [Meer", "Blood Moor", 0.80))      # barely matched
    assert not should_save_lowconf(Reading("BLACK MARSH", "Black Marsh", 1.0))


def test_line_scores_marks_skipped_lines():
    rows = ocr.line_scores("@7:14 P\nGame: RASI\nBLeeD [Meer\nDifFrFicuLTY: NIGHTMARE\n", NAMES)
    by_line = {line: (cand, skipped) for line, cand, score, skipped in rows}
    assert by_line["Game: RASI"][1] and by_line["@7:14 P"][1]
    assert by_line["BLeeD [Meer"] == ("Blood Moor", False)


def test_purple_mask_keeps_purple_drops_gold():
    from PIL import Image
    img = Image.new("RGB", (40, 20), (12, 14, 10))
    img.paste((222, 190, 120), (2, 2, 18, 8))        # gold
    img.paste((162, 82, 252), (2, 12, 18, 18))       # purple core
    img.paste((110, 56, 172), (22, 12, 38, 18))      # purple anti-aliased edge
    out = ocr.purple_only(img)
    assert out.getpixel((8, 4)) == 0                 # gold dropped
    assert out.getpixel((8, 14)) > 80                # purple kept
    assert out.getpixel((30, 14)) > 0                # edge kept
    assert out.getpixel((38, 1)) == 0                # background dropped
    gold = ocr.gold_only(img)
    assert gold.getpixel((8, 14)) == 0 and gold.getpixel((8, 4)) > 150


FIXTURE_CROP = Path(__file__).parent / "tests" / "fixtures" / "crop.png"   # real D2R frame


def test_masks_are_disjoint_on_saved_crop():
    from PIL import Image, ImageChops
    img = Image.open(FIXTURE_CROP)
    both = ImageChops.multiply(ocr.gold_only(img).point(lambda v: 255 if v else 0),
                               ocr.purple_only(img).point(lambda v: 255 if v else 0))
    assert both.getbbox() is None


def test_read_terror_zones_matches_lines():
    raw = "TERROR ZONES\nBUTER STEPPES\nPLaiNs ©F DESPAIR\nPLaiNs ©F DESPAIR\nDIFFICULTY: HELL\n"
    assert ocr.read_terror_zones(raw, NAMES) == ("Outer Steppes", "Plains of Despair")
    assert ocr.read_terror_zones("", NAMES) == ()
    assert ocr.read_terror_zones("@4:13 PM\nPRESS ESC\n", NAMES) == ()


def test_reading_tz_defaults_to_none():
    assert ocr.Reading("", None, 0.0).terror_zones is None


def test_real_crop_reads_area_and_terror_zones():
    import shutil

    import pytest
    from PIL import Image
    if shutil.which("tesseract") is None:
        pytest.skip("tesseract not installed")
    img = Image.open(FIXTURE_CROP)
    reading = ocr.with_terror_zones(img, ocr.read_area(img, NAMES), NAMES)
    assert reading.area == "Rogue Encampment"
    assert reading.terror_zones == ("Outer Steppes", "Plains of Despair")
