"""Where a frozen build put its own files, and how to tell Panda3D.

A packaged application is not the application. PyInstaller rearranges
everything, and libraries that work out where they live by looking at
themselves stop being able to.

Panda3D is one of those. It finds its display modules - the code that actually
opens a window - through a `plugin-path` that defaults to `<auto>`, meaning
"deduce it from where my own libraries are". Inside a frozen bundle that
deduction fails. The library is present and perfectly loadable; Panda3D simply
does not look where it is.

The symptom is not a missing file. It is `No graphics pipe is available!` on a
build that passed every test, and on macOS it looks like nothing at all: the
icon appears in the dock for a second and goes away, because a double-clicked
app has nowhere to print a traceback to.

Nothing here imports Panda3D. Working out where a file is does not need a
graphics engine, and keeping it out means this can be tested.
"""

from __future__ import annotations

import sys
from pathlib import Path

#: The display modules Panda3D loads to open a window, named without the
#: extension because that differs on every platform this ships to.
DISPLAY_MODULES = ("libpandagl", "libp3tinydisplay")


def bundled_root() -> Path | None:
    """Where a frozen build unpacked itself, or None when running from source.

    A one-file build extracts to a temporary directory and says so in
    `sys._MEIPASS`. A directory build (the macOS app bundle) sets it too, to
    the folder its libraries are in.
    """
    if not getattr(sys, "frozen", False):
        return None
    unpacked = getattr(sys, "_MEIPASS", None)
    return Path(unpacked) if unpacked else Path(sys.executable).parent


def panda_plugin_dir(root: Path | None = None) -> Path | None:
    """The directory holding Panda3D's display modules, if this is a build.

    Looked for rather than assumed: PyInstaller has moved these between the
    root and a `panda3d` folder before, and a wrong guess here is an
    application that does not open.
    """
    root = root if root is not None else bundled_root()
    if root is None:
        return None
    for candidate in (root / "panda3d", root):
        if any(_display_modules_in(candidate)):
            return candidate
    return None


def panda_config_dir(root: Path | None = None) -> Path | None:
    """The directory holding Panda3D's own `.prc` files, if this is a build.

    Panda3D finds these the same way it finds its plugins, and fails the same
    way: `unable to auto-locate config files in directory named by "<auto>etc"`.
    Without them nothing is configured to open a window at all, which is a
    different fault from the plugin path and has to be fixed separately - the
    first one hides the second.
    """
    root = root if root is not None else bundled_root()
    if root is None:
        return None
    for candidate in (root / "panda3d" / "etc", root / "etc"):
        if candidate.is_dir() and any(candidate.glob("*.prc")):
            return candidate
    return None


def _display_modules_in(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return [
        found
        for module in DISPLAY_MODULES
        for found in directory.glob(f"{module}.*")
        if found.is_file()
    ]
