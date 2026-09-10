"""The one and only place RideWithUBT keeps user data.

Recorded rides, settings and downloaded world data all live under a single
directory chosen per platform. It is deliberately static: there are no profiles,
no per-world folders scattered around the disk and no server-side copy, so a
backup of one directory is a backup of everything the app knows.

Set ``RIDEWITHUBT_HOME`` to move the whole tree, which is what the tests do.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "RideWithUBT"
HOME_ENV_VAR = "RIDEWITHUBT_HOME"


def packaged(*parts: str) -> Path:
    """A file that ships inside the application, not one a rider owns.

    The worlds, the catalogues, the icon. Distinct from `data_root`, which is
    where a rider's own settings and rides live.
    """
    return Path(__file__).resolve().parent / "data" / Path(*parts)


def data_root() -> Path:
    """Return the root of the user data tree, creating nothing."""
    override = os.environ.get(HOME_ENV_VAR)
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_DIR_NAME
        return Path.home() / "AppData" / "Roaming" / APP_DIR_NAME
    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base) / APP_DIR_NAME
    return Path.home() / ".local" / "share" / APP_DIR_NAME


def activities_dir() -> Path:
    """Where finished rides are written, as FIT files."""
    return data_root() / "activities"


def worlds_dir() -> Path:
    """Where generated world meshes are cached after a build."""
    return data_root() / "worlds"


def workouts_dir() -> Path:
    """Where imported workouts are kept, as the plan format's JSON."""
    return data_root() / "workouts"


def contributions_dir() -> Path:
    """Where measured trainer profiles are written, ready to be contributed."""
    return data_root() / "contributions"


def settings_file() -> Path:
    return data_root() / "settings.json"


def ensure_data_tree() -> Path:
    """Create the data tree if it is missing and return its root."""
    root = data_root()
    for path in (root, activities_dir(), worlds_dir(), workouts_dir()):
        path.mkdir(parents=True, exist_ok=True)
    return root
