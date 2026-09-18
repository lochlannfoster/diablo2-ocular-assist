import tomllib

import config


def test_round_trip(tmp_path):
    path = tmp_path / "config.toml"
    cfg = config.load(path)                      # no file -> defaults + seeded profiles
    expected = config._merge(config.DEFAULTS, {"overlay": {"profiles": config.DEFAULT_PROFILES}})
    assert cfg == expected
    cfg["overlay"]["margin_y"] = 99
    cfg["overlay"]["sections"]["notes"] = False
    cfg["capture"]["region"]["x"] = 0.8123
    config.save(cfg, path)
    again = config.load(path)
    assert again["overlay"]["margin_y"] == 99
    assert again["overlay"]["sections"]["notes"] is False
    assert again["capture"]["region"]["x"] == 0.8123
    assert again == cfg
    assert tomllib.loads(path.read_text())       # valid TOML


def test_missing_keys_get_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[overlay]\nmargin_x = 5\n')
    cfg = config.load(path)
    assert cfg["overlay"]["margin_x"] == 5
    assert cfg["overlay"]["anchor"] == "top-right"
    assert cfg["capture"]["region"]["w"] == 0.155
    assert all(cfg["overlay"]["sections"].values())


def test_strings_are_escaped(tmp_path):
    path = tmp_path / "config.toml"
    cfg = config.load(path)
    cfg["overlay"]["output"] = 'LG "HDR" 4K'
    config.save(cfg, path)
    assert config.load(path)["overlay"]["output"] == 'LG "HDR" 4K'


def test_current_config_loads():
    cfg = config.load()
    assert cfg["overlay"]["anchor"] in config.ANCHORS


def test_style_keys_round_trip_and_default(tmp_path):
    path = tmp_path / "config.toml"
    cfg = config.load(path)
    assert cfg["overlay"]["font"] == "Hack"
    assert cfg["overlay"]["opacity"] == 0.82 and cfg["overlay"]["padding"] == 12
    cfg["overlay"].update(font="DejaVu Sans Mono", opacity=0.5, padding=4)
    config.save(cfg, path)
    again = config.load(path)
    assert again["overlay"]["font"] == "DejaVu Sans Mono"
    assert again["overlay"]["opacity"] == 0.5 and again["overlay"]["padding"] == 4


def test_profiles_round_trip_seed_and_delete(tmp_path):
    path = tmp_path / "config.toml"
    cfg = config.load(path)
    assert set(cfg["overlay"]["profiles"]) == {"speedrun", "farming"}
    cfg["overlay"]["compact"] = True
    cfg["overlay"]["profile"] = "farming"
    cfg["overlay"]["profiles"]["boss"] = ["uniques", "drops"]
    del cfg["overlay"]["profiles"]["speedrun"]
    config.save(cfg, path)
    again = config.load(path)
    assert again["overlay"]["compact"] is True and again["overlay"]["profile"] == "farming"
    assert again["overlay"]["profiles"] == {"farming": config.DEFAULT_PROFILES["farming"],
                                            "boss": ["uniques", "drops"]}   # deleted stays deleted
    assert tomllib.loads(path.read_text())


def test_profile_helpers():
    ov = {"profile": "all", "sections": {"waypoint": False}, "profiles": {"boss": ["uniques"]}}
    assert config.profile_names(ov) == ["all", "custom", "boss"]
    assert all(config.active_sections(ov).values())
    ov["profile"] = "custom"
    assert config.active_sections(ov)["waypoint"] is False and config.active_sections(ov)["next"] is True
    ov["profile"] = "boss"
    active = config.active_sections(ov)
    assert active["uniques"] and not active["waypoint"]
    assert config.next_profile(ov) == "all" and config.next_profile({"profile": "all", "profiles": {}}) == "custom"


def test_profile_validation(tmp_path):
    import pytest
    path = tmp_path / "config.toml"
    path.write_text('[overlay.profiles]\nall = ["waypoint"]\n')
    with pytest.raises(config.ConfigError):
        config.load(path)
    path.write_text('[overlay.profiles]\nx = ["nope"]\n')
    with pytest.raises(config.ConfigError):
        config.load(path)
    path.write_text('[overlay]\nprofile = "ghost"\n')
    assert config.load(path)["overlay"]["profile"] == "all"
    path.write_text('[overlay.profiles]\n')                 # present but empty: no seeding
    assert config.load(path)["overlay"]["profiles"] == {}
