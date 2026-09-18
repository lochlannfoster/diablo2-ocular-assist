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


def test_difficulty_is_remembered_across_blank_reads():
    r = Recognizer()
    r.feed("Cold Plains", "hell")
    assert r.difficulty == "hell"
    r.feed(None, None)
    assert r.difficulty == "hell"


def test_misses_count_consecutive_unreadable_frames():
    r = Recognizer(agree=1)
    r.feed("Cold Plains")
    assert r.misses == 0
    r.feed(None); r.feed(None)
    assert r.misses == 2 and r.area == "Cold Plains"
    r.feed("Cold Plains")
    assert r.misses == 0


def test_terror_zones_kept_until_refreshed():
    r = Recognizer(agree=1)
    r.feed("Cold Plains", terror_zones=("Cold Plains", "Stony Field"))
    assert r.terror_zones == ("Cold Plains", "Stony Field")
    r.feed("Cold Plains")                       # purple pass skipped this frame
    assert r.terror_zones == ("Cold Plains", "Stony Field")
    r.feed("Cold Plains", terror_zones=())      # ran, nothing listed
    assert r.terror_zones == ()
    r.frozen = True
    r.feed("Cold Plains", terror_zones=("Pit Level 1",))
    assert r.terror_zones == ()                 # frozen means frozen
