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
        assert len(area.next) + len("  (from entry)") <= 42, area.next


def test_unknown_next_is_rejected():
    data = {"area": {"A": {"act": 1, "next": "Nowhere", "has_waypoint": False,
                           "to_waypoint": {"dir": "none", "tip": ""},
                           "to_next": {"dir": "left", "tip": ""},
                           "confidence": "high"}}}
    with pytest.raises(areas.AreaError, match="Nowhere"):
        areas.parse(data)


def test_bad_dir_is_rejected():
    data = {"area": {"A": {"act": 1, "next": "", "has_waypoint": False,
                           "to_waypoint": {"dir": "sideways", "tip": ""},
                           "to_next": {"dir": "left", "tip": ""},
                           "confidence": "high"}}}
    with pytest.raises(areas.AreaError, match="sideways"):
        areas.parse(data)


def test_every_dir_has_a_glyph():
    for area in areas.load().values():
        assert area.to_waypoint.glyph
        assert area.to_next.glyph


def test_every_entry_cites_a_source():
    for area in areas.load().values():
        assert area.source, area.name


def test_no_rule_entries_say_so():
    for area in areas.load().values():
        for hint in (area.to_waypoint, area.to_next):
            if hint.no_rule:
                assert "no accepted rule" in hint.tip, (area.name, hint)


def test_shared_names_resolve_by_act():
    rules = areas.load()
    assert "Sewers Level 1" in areas.screen_names(rules)
    assert "Kurast Sewers Level 1" not in areas.screen_names(rules)
    assert areas.resolve(rules, "Sewers Level 1", 3).name == "Kurast Sewers Level 1"
    assert areas.resolve(rules, "Sewers Level 1", 2).name == "Sewers Level 1"
    assert areas.resolve(rules, "Sewers Level 1", None).act == 2
    assert areas.resolve(rules, "Cold Plains", 5).name == "Cold Plains"
