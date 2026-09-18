import areas
from compact import terse


def test_first_sentence_only():
    assert terse("Follow the dirt path from the camp; it runs straight to Cold Plains. More.") \
        == "Follow the dirt path from the camp"
    assert terse("Town, fixed layout.") == "Town, fixed layout"


def test_cuts_at_clause_boundary_when_long():
    assert terse("Right next to where you come in from Blood Moor, in the corner.") \
        == "Right next to where you come in from Blood Moor"


def test_falls_back_to_word_boundary_then_hard_cut():
    words = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo"
    out = terse(words, 30)
    assert out == "alpha bravo charlie delta echo" and len(out) <= 30
    assert terse("A" * 100, 48) == "A" * 48


def test_never_ellipsis_never_trailing_punctuation_idempotent():
    for area in areas.load().values():
        for tip in (area.to_waypoint.tip, area.to_next.tip, *area.farm):
            out = terse(tip)
            assert "…" not in out and not out.endswith("...")
            assert not out or out[-1] not in " ,;:-—(."
            assert len(out) <= 48
            assert terse(out) == out


def test_empty():
    assert terse("") == "" and terse("   ") == ""
