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


def test_value_colour_ramps_grey_to_green_on_a_log_scale():
    low, high = 0.0008, 3.5
    assert markup.value_colour(low, low, high) == markup.DIM
    assert markup.value_colour(high, low, high) == markup.GOOD
    assert markup.value_colour(0.0001, low, high) == markup.DIM      # clamped below
    mid = markup.value_colour(0.05, low, high)                        # roughly halfway in log terms
    assert mid not in (markup.DIM, markup.GOOD) and mid.startswith("#")
    assert markup.tier("El  ", "normal") == f'<span foreground="{markup.TIER_COLOURS["normal"]}">El  </span>'
