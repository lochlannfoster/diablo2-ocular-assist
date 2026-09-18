from state import Recognizer


def test_commits_after_two_agreeing_reads():
    r = Recognizer()
    assert r.feed("Cold Plains") is False
    assert r.area is None
    assert r.feed("Cold Plains") is True
    assert r.area == "Cold Plains"


def test_single_misread_does_not_commit():
    r = Recognizer()
    r.feed("Cold Plains"); r.feed("Cold Plains")
    assert r.feed("Far Oasis") is False
    assert r.feed("Cold Plains") is False
    assert r.area == "Cold Plains"


def test_blank_keeps_area_but_marks_stale():
    r = Recognizer()
    r.feed("Cold Plains"); r.feed("Cold Plains")
    assert r.feed(None) is False
    assert r.area == "Cold Plains"
    assert r.visible is False
    r.feed("Cold Plains")
    assert r.visible is True


def test_frozen_ignores_input():
    r = Recognizer()
    r.feed("Cold Plains"); r.feed("Cold Plains")
    r.toggle_frozen()
    r.feed("Stony Field"); r.feed("Stony Field")
    assert r.area == "Cold Plains"
    r.toggle_frozen()
    r.feed("Stony Field"); r.feed("Stony Field")
    assert r.area == "Stony Field"
