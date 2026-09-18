import areas
import markup


def test_direction_has_arrow_and_bold_word():
    out = markup.direction(areas.Hint("left", "tip"))
    assert "←" in out and "TURN LEFT" in out and 'weight="bold"' in out
    assert markup.DIRECTION in out


def test_no_rule_direction_is_orange():
    out = markup.direction(areas.Hint("random", "no accepted rule"))
    assert markup.NORULE in out and "NO RULE" in out


def test_every_dir_has_an_arrow():
    assert set(markup.ARROWS) == set(areas.LABELS)


def test_head_uses_section_colour_and_escapes():
    out = markup.head("A&B", "farm")
    assert markup.SECTION_COLOURS["farm"] in out and "A&amp;B" in out


def test_rng():
    assert markup.rng((45, 55)) == "45–55" and markup.rng((3, 3)) == "3"
