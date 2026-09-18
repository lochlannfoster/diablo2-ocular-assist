import ast
import sys
from pathlib import Path

import native


def test_backend_matches_platform():
    assert native.IS_WINDOWS == sys.platform.startswith("win")
    assert callable(native.capture_backend)
    assert native.config_dir().is_dir()


def test_both_backends_implement_the_interface():
    """The Windows backend can't be imported on Linux (ctypes.windll), so
    check the interface by parsing: every name __init__ re-exports must be
    defined at module level in both files."""
    init = (Path(native.__file__)).read_text()
    wanted = {
        line.split(" = ")[1].split(".")[1].strip()
        for line in init.splitlines()
        if line.startswith(("init", "prepare", "on_", "set_", "monitor", "capture", "hotkey",
                            "game", "tesseract", "config", "HAS_")) and " = impl." in line
    }
    assert wanted, "nothing to check"
    for backend in ("linux.py", "windows.py"):
        tree = ast.parse((Path(native.__file__).parent / backend).read_text())
        defined = {
            node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        } | {
            target.id for node in tree.body if isinstance(node, ast.Assign)
            for target in node.targets if isinstance(target, ast.Name)
        }
        missing = wanted - defined - {"impl"}
        assert not missing, f"{backend} lacks {sorted(missing)}"
        assert "list_monitors" in defined, backend
