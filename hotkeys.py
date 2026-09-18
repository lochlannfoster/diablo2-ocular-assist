"""Global hotkeys by reading input devices directly.

Wayland does not let applications grab global hotkeys, and KDE's config-file
route needs a full re-login to take effect. Reading /dev/input works
immediately, needs no compositor cooperation, and never touches the game: these
are *your* keyboards, not the game's process, so there is nothing here for an
anti-cheat to object to.

That access is broad, though -- an open input device sees every keystroke on the
machine, including passwords typed into other windows. Three rules follow, and
they are the reason this module is shaped the way it is:

  1. Devices are only open while the game is running (see GameWatcher).
  2. Only the configured chords are ever acted on.
  3. Nothing is logged, stored, or forwarded. Key codes are matched and dropped.

Events are *observed*, never swallowed -- reading an evdev device is passive, so
the keystroke still reaches whatever has focus. Chords must therefore be ones
the game does not need. Ctrl+F-keys are used because D2R binds nothing to them by
default.
"""

from __future__ import annotations

import os

try:
    import evdev
    from evdev import ecodes
except ImportError:  # pragma: no cover - reported by the caller
    evdev = None
    ecodes = None

# Key name -> command. Names rather than raw codes so this reads as a keymap.
CHORDS = {
    "KEY_F9": "hide",
    "KEY_F10": "freeze",
    "KEY_F11": "quit",
    # Marks the current area's rule as wrong in the log, so bad entries in
    # data/areas.toml can be fixed in a batch after the session.
    "KEY_F12": "flag",
}

CTRL_KEYS = ("KEY_LEFTCTRL", "KEY_RIGHTCTRL")

# evdev event values.
KEY_UP_VALUE, KEY_DOWN_VALUE, KEY_HELD_VALUE = 0, 1, 2

# How the D2R process shows up under Proton.
GAME_PATTERNS = ("D2R.exe", "D2R")


class Matcher:
    """Turns a stream of key events into commands.

    Modifier state is tracked across devices, so a Ctrl held on one keyboard
    still combines with an arrow pressed on another. Pure and synchronous, which
    is what makes the interesting behaviour testable without a real device.
    """

    def __init__(self, chords=None, ctrl_keys=CTRL_KEYS):
        self.chords = dict(chords or CHORDS)
        self.ctrl_keys = set(ctrl_keys)
        self._ctrl_down: set[str] = set()

    @property
    def ctrl_held(self) -> bool:
        return bool(self._ctrl_down)

    def feed(self, key_name: str, value: int) -> str | None:
        """Feed one key event. Returns a command name, or None.

        Only key-down fires a command: auto-repeat (value 2) would otherwise
        stream commands while a key is held, and key-up would fire everything
        twice.
        """
        if key_name in self.ctrl_keys:
            if value == KEY_UP_VALUE:
                self._ctrl_down.discard(key_name)
            else:
                self._ctrl_down.add(key_name)
            return None

        if value != KEY_DOWN_VALUE or not self._ctrl_down:
            return None
        return self.chords.get(key_name)

    def reset(self):
        """Forget modifier state.

        Called when devices close: a Ctrl held as the game exits would otherwise
        look held forever, and the next arrow press would fire a command.
        """
        self._ctrl_down.clear()


def key_name(code: int) -> str | None:
    """Map an evdev key code to its name, or None if it has no single name."""
    if ecodes is None:
        return None
    name = ecodes.KEY.get(code)
    if isinstance(name, (list, tuple)):  # some codes have aliases
        name = name[0]
    return name


def iter_process_names():
    """Yield (pid, argv0-basename) for every process we can see.

    Reads /proc rather than shelling out to pgrep: this runs every couple of
    seconds while a game is on screen, and spawning two processes each time to
    ask a question we can answer by reading a few files is exactly the kind of
    thing not to do during a match.
    """
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        try:
            with open(f"/proc/{entry.name}/cmdline", "rb") as handle:
                argv0 = handle.read(4096).split(b"\0")[0]
        except OSError:
            continue  # exited between scandir and open; normal
        if argv0:
            yield int(entry.name), basename(argv0.decode("utf-8", "replace"))


def basename(path: str) -> str:
    """Last path component, splitting on both separators.

    Proton reports the game with a Windows argv[0] --
    `S:\\steamapps\\common\\Diablo II Resurrected\\D2R.exe` -- and os.path.basename on
    Linux does not treat a backslash as a separator, so it hands back the whole
    string and nothing ever matches.
    """
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def game_is_running(patterns=GAME_PATTERNS) -> bool:
    """Is Diablo II: Resurrected running?

    Matches argv[0]'s basename only. Matching the whole command line -- what
    `pgrep -f` does -- also matches any shell, editor or grep that merely
    mentions the game, which during testing meant the listener saw a game that
    was not there.

    Process presence rather than window focus: KWin on Wayland exposes no way to
    query the focused window (`queryWindowInfo` is interactive, and there is no
    active-window property), so focus gating would need a loaded KWin script
    reporting back over D-Bus. Process gating still keeps the devices closed
    whenever you are not playing, which is the point.
    """
    own = os.getpid()
    for pid, name in iter_process_names():
        if pid == own:
            continue
        if any(name == pattern or name.startswith(pattern) for pattern in patterns):
            return True
    return False


def keyboards() -> list:
    """Every readable device that reports key presses.

    Includes more than the main keyboard -- media keys and some mice expose key
    capabilities too -- which is why the matcher filters by chord rather than
    trusting the device list.
    """
    if evdev is None:
        return []
    found = []
    for path in evdev.list_devices():
        try:
            device = evdev.InputDevice(path)
        except OSError:
            continue  # disappeared or not readable; not our problem
        capabilities = device.capabilities()
        keys = capabilities.get(ecodes.EV_KEY, [])
        # A real keyboard has letter keys. This filters out mice, which report
        # EV_KEY for their buttons but cannot produce our chords.
        if ecodes.KEY_A in keys and ecodes.KEY_Z in keys:
            found.append(device)
        else:
            device.close()
    return found


class Listener:
    """Opens keyboards while the game runs, and closes them the moment it stops.

    Integrates with a GLib main loop through `attach`/`detach` callbacks rather
    than importing GTK, so this module stays testable on its own.
    """

    def __init__(self, on_command, attach, detach, matcher=None):
        self.on_command = on_command
        self._attach = attach
        self._detach = detach
        self.matcher = matcher or Matcher()
        self.devices: dict[int, object] = {}   # fd -> device
        self._sources: dict[int, object] = {}  # fd -> main-loop source
        self.open = False

    def poll_game(self) -> bool:
        """Open or close devices to match whether the game is running."""
        running = game_is_running()
        if running and not self.open:
            self.open_devices()
        elif not running and self.open:
            self.close_devices()
        return running

    def open_devices(self):
        devices = keyboards()
        if not devices:
            print("hotkeys: no readable keyboards; is your user in the 'input'"
                  " group?", flush=True)
            return
        for device in devices:
            fd = device.fd
            self.devices[fd] = device
            self._sources[fd] = self._attach(fd, self._on_readable)
        self.open = True
        print(f"hotkeys: listening on {len(devices)} keyboard(s) while the game"
              " runs", flush=True)

    def close_devices(self):
        for fd, source in self._sources.items():
            self._detach(source)
        for device in self.devices.values():
            try:
                device.close()
            except OSError:
                pass
        self.devices.clear()
        self._sources.clear()
        self.matcher.reset()
        self.open = False
        print("hotkeys: game closed, input devices released", flush=True)

    def _on_readable(self, fd):
        """Drain pending events from one device."""
        device = self.devices.get(fd)
        if device is None:
            return False
        try:
            events = list(device.read())
        except (OSError, BlockingIOError):
            # Unplugged mid-session. Drop it rather than spinning on a dead fd.
            self._drop(fd)
            return False
        for event in events:
            if event.type != ecodes.EV_KEY:
                continue
            name = key_name(event.code)
            if name is None:
                continue
            command = self.matcher.feed(name, event.value)
            if command:
                self.on_command(command)
        return True

    def _drop(self, fd):
        source = self._sources.pop(fd, None)
        if source is not None:
            self._detach(source)
        device = self.devices.pop(fd, None)
        if device is not None:
            try:
                device.close()
            except OSError:
                pass
        if not self.devices:
            self.open = False


def available() -> tuple[bool, str]:
    """Can hotkeys work at all? Returns (ok, explanation)."""
    if evdev is None:
        return False, "python-evdev is not installed (pacman -S python-evdev)"
    if not os.path.exists("/dev/input"):
        return False, "/dev/input does not exist"
    if not evdev.list_devices():
        return False, ("no readable input devices; add your user to the 'input'"
                       " group and log back in")
    return True, "ok"
