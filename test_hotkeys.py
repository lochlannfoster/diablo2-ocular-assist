"""Tests for hotkey matching and device lifecycle. Touches no real devices."""

import pytest

from hotkeys import KEY_DOWN_VALUE, KEY_HELD_VALUE, KEY_UP_VALUE, Listener, Matcher

CTRL = "KEY_LEFTCTRL"


@pytest.fixture
def matcher():
    return Matcher()


def press(matcher, *keys):
    """Press keys in order, returning the commands they produced."""
    return [matcher.feed(k, KEY_DOWN_VALUE) for k in keys]


class TestMatcher:
    def test_chord_fires(self, matcher):
        matcher.feed(CTRL, KEY_DOWN_VALUE)
        assert matcher.feed("KEY_F10", KEY_DOWN_VALUE) == "freeze"

    def test_all_chords(self, matcher):
        matcher.feed(CTRL, KEY_DOWN_VALUE)
        assert press(matcher, "KEY_F9", "KEY_F10", "KEY_F11",
                     "KEY_F12") == ["hide", "freeze", "quit", "flag"]

    def test_shift_chords(self, matcher):
        matcher.feed(CTRL, KEY_DOWN_VALUE)
        matcher.feed("KEY_LEFTSHIFT", KEY_DOWN_VALUE)
        assert press(matcher, "KEY_F9", "KEY_F10", "KEY_F11") == ["compact", "profile", "edit"]
        assert matcher.feed("KEY_F12", KEY_DOWN_VALUE) is None     # no Ctrl+Shift+F12 chord
        matcher.feed("KEY_LEFTSHIFT", KEY_UP_VALUE)
        assert matcher.feed("KEY_F9", KEY_DOWN_VALUE) == "hide"    # back to the plain chord

    def test_shift_alone_does_nothing(self, matcher):
        matcher.feed("KEY_RIGHTSHIFT", KEY_DOWN_VALUE)
        assert matcher.feed("KEY_F9", KEY_DOWN_VALUE) is None

    def test_reset_clears_shift(self, matcher):
        matcher.feed(CTRL, KEY_DOWN_VALUE)
        matcher.feed("KEY_LEFTSHIFT", KEY_DOWN_VALUE)
        matcher.reset()
        matcher.feed(CTRL, KEY_DOWN_VALUE)
        assert matcher.feed("KEY_F9", KEY_DOWN_VALUE) == "hide"

    def test_without_ctrl_nothing_fires(self, matcher):
        # The whole point: bare arrows must reach the game's map scrolling.
        assert press(matcher, "KEY_F9", "KEY_F10", "KEY_F11") == [None] * 3

    def test_ctrl_release_stops_matching(self, matcher):
        matcher.feed(CTRL, KEY_DOWN_VALUE)
        matcher.feed(CTRL, KEY_UP_VALUE)
        assert matcher.feed("KEY_F9", KEY_DOWN_VALUE) is None

    def test_right_ctrl_works_too(self, matcher):
        matcher.feed("KEY_RIGHTCTRL", KEY_DOWN_VALUE)
        assert matcher.feed("KEY_F9", KEY_DOWN_VALUE) == "hide"

    def test_either_ctrl_keeps_it_held(self, matcher):
        matcher.feed(CTRL, KEY_DOWN_VALUE)
        matcher.feed("KEY_RIGHTCTRL", KEY_DOWN_VALUE)
        matcher.feed(CTRL, KEY_UP_VALUE)
        assert matcher.feed("KEY_F9", KEY_DOWN_VALUE) == "hide"

    def test_key_up_does_not_fire(self, matcher):
        matcher.feed(CTRL, KEY_DOWN_VALUE)
        assert matcher.feed("KEY_F9", KEY_UP_VALUE) is None

    def test_autorepeat_does_not_fire(self, matcher):
        # Holding Ctrl+Right must not stream 'next' at the repeat rate.
        matcher.feed(CTRL, KEY_DOWN_VALUE)
        assert matcher.feed("KEY_F10", KEY_DOWN_VALUE) == "freeze"
        assert matcher.feed("KEY_F10", KEY_HELD_VALUE) is None
        assert matcher.feed("KEY_F10", KEY_HELD_VALUE) is None

    def test_unmapped_keys_ignored(self, matcher):
        matcher.feed(CTRL, KEY_DOWN_VALUE)
        # Ctrl+C, Ctrl+A and friends must pass through untouched.
        assert press(matcher, "KEY_C", "KEY_A", "KEY_V") == [None] * 3

    def test_ctrl_is_not_itself_a_command(self, matcher):
        assert matcher.feed(CTRL, KEY_DOWN_VALUE) is None

    def test_reset_clears_stuck_modifier(self, matcher):
        matcher.feed(CTRL, KEY_DOWN_VALUE)
        assert matcher.ctrl_held
        matcher.reset()
        assert not matcher.ctrl_held
        assert matcher.feed("KEY_F9", KEY_DOWN_VALUE) is None

    def test_custom_chords(self):
        matcher = Matcher(chords={"KEY_P": "pause"})
        matcher.feed(CTRL, KEY_DOWN_VALUE)
        assert matcher.feed("KEY_P", KEY_DOWN_VALUE) == "pause"
        assert matcher.feed("KEY_F9", KEY_DOWN_VALUE) is None


class FakeDevice:
    def __init__(self, fd):
        self.fd = fd
        self.closed = False

    def close(self):
        self.closed = True


class TestListenerLifecycle:
    def _listener(self, monkeypatch, running, devices):
        attached, detached = [], []
        monkeypatch.setattr("hotkeys.game_is_running", lambda *a, **k: running())
        monkeypatch.setattr("hotkeys.keyboards", lambda: list(devices))
        listener = Listener(
            on_command=lambda c: None,
            attach=lambda fd, cb: attached.append(fd) or f"src{fd}",
            detach=lambda src: detached.append(src),
        )
        return listener, attached, detached

    def test_opens_when_game_starts(self, monkeypatch):
        devices = [FakeDevice(3), FakeDevice(4)]
        listener, attached, _ = self._listener(monkeypatch, lambda: True, devices)
        listener.poll_game()
        assert listener.open
        assert attached == [3, 4]

    def test_closes_when_game_stops(self, monkeypatch):
        devices = [FakeDevice(3)]
        running = [True]
        listener, _, detached = self._listener(
            monkeypatch, lambda: running[0], devices)
        listener.poll_game()
        running[0] = False
        listener.poll_game()
        assert not listener.open
        assert detached == ["src3"]
        assert devices[0].closed, "device must actually be released"

    def test_stays_closed_while_game_absent(self, monkeypatch):
        listener, attached, _ = self._listener(
            monkeypatch, lambda: False, [FakeDevice(3)])
        listener.poll_game()
        listener.poll_game()
        assert not listener.open
        assert attached == []

    def test_repeated_polls_do_not_reopen(self, monkeypatch):
        listener, attached, _ = self._listener(
            monkeypatch, lambda: True, [FakeDevice(3)])
        listener.poll_game()
        listener.poll_game()
        listener.poll_game()
        assert attached == [3], "devices opened once, not once per poll"

    def test_no_devices_available_stays_closed(self, monkeypatch):
        listener, _, _ = self._listener(monkeypatch, lambda: True, [])
        listener.poll_game()
        assert not listener.open

    def test_closing_clears_modifier_state(self, monkeypatch):
        devices = [FakeDevice(3)]
        running = [True]
        listener, _, _ = self._listener(monkeypatch, lambda: running[0], devices)
        listener.poll_game()
        listener.matcher.feed(CTRL, KEY_DOWN_VALUE)
        running[0] = False
        listener.poll_game()
        assert not listener.matcher.ctrl_held


class TestBasename:
    """Proton reports argv[0] as a Windows path; os.path.basename misses it."""

    def test_proton_windows_path(self):
        from hotkeys import basename
        assert basename(r"S:\steamapps\common\D2R\D2R.exe") == "D2R.exe"

    def test_unix_path(self):
        from hotkeys import basename
        assert basename("/usr/bin/python3") == "python3"

    def test_bare_name(self):
        from hotkeys import basename
        assert basename("D2R.exe") == "D2R.exe"

    def test_mixed_separators(self):
        from hotkeys import basename
        assert basename("/mnt/games/S:\\common\\D2R.exe") == "D2R.exe"


class TestGameDetection:
    def test_matches_proton_windows_argv0(self, monkeypatch):
        import hotkeys
        monkeypatch.setattr(hotkeys, "iter_process_names",
                            lambda: [(1, "systemd"), (2, "D2R.exe")])
        assert hotkeys.game_is_running()

    def test_no_match_when_absent(self, monkeypatch):
        import hotkeys
        monkeypatch.setattr(hotkeys, "iter_process_names",
                            lambda: [(1, "systemd"), (2, "firefox")])
        assert not hotkeys.game_is_running()

    def test_mentioning_the_game_is_not_running_it(self, monkeypatch):
        import hotkeys
        # `pgrep -f` matched shells like this one; argv[0] matching must not.
        monkeypatch.setattr(hotkeys, "iter_process_names",
                            lambda: [(1, "bash"), (2, "grep"), (3, "nvim")])
        assert not hotkeys.game_is_running()
