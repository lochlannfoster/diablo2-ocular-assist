import pytest

import areas


def test_data_file_loads_and_is_complete():
    rules = areas.load()
    assert len(rules) > 100
    for act in range(1, 6):
        assert any(a.act == act for a in rules.values()), f"act {act} missing"
    # Every act's town has a waypoint, and the mainline chains resolve.
    for town in ("Rogue Encampment", "Lut Gholein", "Kurast Docks",
                 "The Pandemonium Fortress", "Harrogath"):
        assert rules[town].has_waypoint


def test_mainline_chain_reaches_each_act_boss():
    rules = areas.load()
    for start, end in (("Rogue Encampment", "Catacombs Level 4"),
                       ("Kurast Docks", "Durance of Hate Level 3"),
                       ("Harrogath", "The Worldstone Chamber")):
        seen, name = set(), start
        while name and name not in seen:
            seen.add(name)
            name = rules[name].next
        assert end in seen


def test_tips_fit_fixed_width():
    # overlay lines are "      XX tip" in a 48-char box.
    for area in areas.load().values():
        for hint in (area.to_waypoint, area.to_next):
            assert len(hint.tip) <= 39, (area.name, hint.tip)
        assert len(area.next) <= 42, area.next


def test_unknown_next_is_rejected():
    data = {"area": {"A": {"act": 1, "next": "Nowhere", "has_waypoint": False,
                           "to_waypoint": {"dir": "none", "tip": ""},
                           "to_next": {"dir": "up", "tip": ""},
                           "confidence": "high"}}}
    with pytest.raises(areas.AreaError, match="Nowhere"):
        areas.parse(data)


def test_bad_dir_is_rejected():
    data = {"area": {"A": {"act": 1, "next": "", "has_waypoint": False,
                           "to_waypoint": {"dir": "sideways", "tip": ""},
                           "to_next": {"dir": "up", "tip": ""},
                           "confidence": "high"}}}
    with pytest.raises(areas.AreaError, match="sideways"):
        areas.parse(data)


def test_every_dir_has_a_glyph():
    for area in areas.load().values():
        assert area.to_waypoint.glyph
        assert area.to_next.glyph
