import tomllib

import config


def test_round_trip(tmp_path):
    path = tmp_path / "config.toml"
    cfg = config.load(path)                      # no file -> defaults
    assert cfg == config.DEFAULTS
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
    assert cfg["overlay"]["output"] == "DP-1"
