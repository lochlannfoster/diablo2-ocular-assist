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


def test_tips_are_sentences():
    # Tips wrap in the overlay, so no length cap -- but they should read as
    # prose and never use compass words as the direction.
    for area in areas.load().values():
        for hint in (area.to_waypoint, area.to_next):
            assert hint.tip.endswith("."), (area.name, hint.tip)
            assert hint.dir in areas.LABELS


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
        assert area.to_waypoint.label
        assert area.to_next.label


def test_every_entry_cites_a_source():
    for area in areas.load().values():
        assert area.source, area.name


def test_no_rule_entries_say_so():
    for area in areas.load().values():
        for hint in (area.to_waypoint, area.to_next):
            if hint.no_rule:
                assert "no accepted rule" in hint.tip.lower(), (area.name, hint)


def test_shared_names_resolve_by_act():
    rules = areas.load()
    assert "Sewers Level 1" in areas.screen_names(rules)
    assert "Kurast Sewers Level 1" not in areas.screen_names(rules)
    assert areas.resolve(rules, "Sewers Level 1", 3).name == "Kurast Sewers Level 1"
    assert areas.resolve(rules, "Sewers Level 1", 2).name == "Sewers Level 1"
    assert areas.resolve(rules, "Sewers Level 1", None).act == 2
    assert areas.resolve(rules, "Cold Plains", 5).name == "Cold Plains"


def test_levels_and_quests():
    rules = areas.load()
    assert rules["Cold Plains"].levels == (2, 36, 68)
    assert rules["Cold Plains"].level("nightmare") == 36
    assert rules["Rogue Encampment"].level("hell") is None   # town
    assert rules["Cold Plains"].level(None) is None
    assert rules["Durance of Hate Level 3"].quests == ("The Guardian: Mephisto",)
    for area in rules.values():
        assert len(area.quests) <= 2, area.name
        for quest in area.quests:
            assert len(quest) <= 42, quest


def test_exp_bands():
    b = areas.exp_bands(50)
    assert b["good"] == (45, 55)
    assert b["avg_low"] == (42, 44) and b["avg_high"] == (56, 58)
    assert b["bad_low"] == (1, 41) and b["bad_high"] == (59, 99)
    assert areas.exp_bands(2)["good"] == (1, 7)
    assert areas.exp_bands(85)["bad_high"] == (94, 99)


def test_uniques_and_notes_load():
    rules = areas.load()
    assert "The Countess" in rules["Tower Cellar Level 5"].uniques
    assert len(rules["Throne of Destruction"].uniques) == 5
    assert rules["Pit Level 2"].levels[2] == 85   # gets the derived alvl-85 note
    for area in rules.values():
        for text in area.uniques + area.notes + area.farm:
            assert text.strip() == text


def test_farm_routes_load():
    rules = areas.load()
    assert any("Tower" in f for f in rules["Black Marsh"].farm)
    assert rules["Tower Cellar Level 3"].farm
    assert rules["Blood Moor"].farm == ()


def test_drop_note_per_difficulty():
    assert areas.drop_note(1, "normal", 0) is None                       # town
    assert "no runes" in areas.drop_note(1, "normal", 2)
    assert "up to Dol" in areas.drop_note(5, "normal", 33)
    assert "up to Ist" in areas.drop_note(5, "nightmare", 60)
    assert "up to Vex" in areas.drop_note(1, "hell", 67)
    assert "uniques/champions only" in areas.drop_note(1, "hell", 79)
    assert "incl. Zod" in areas.drop_note(2, "hell", 82)
    assert "every item" in areas.drop_note(1, "hell", 85)


def test_terror_notes():
    assert "96" in areas.terror_drop_note("hell") and "every item" in areas.terror_drop_note("hell")
    assert "45" in areas.terror_drop_note("normal") and "every item" not in areas.terror_drop_note("normal")
    assert "71" in areas.terror_exp_note("nightmare")
