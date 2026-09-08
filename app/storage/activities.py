"""The activity store: one static directory, one file per ride.

Deliberately dull. Rides are named after the moment they started, in a sortable
form, so the directory reads in order and two rides cannot collide unless they
began in the same second - and then the later one is given a suffix rather than
overwriting the earlier.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app import paths

SUFFIX = ".fit"
NAME_FORMAT = "%Y%m%dT%H%M%S"
MAX_COLLISIONS = 100


def file_name(started_at: datetime) -> str:
    return f"{started_at.strftime(NAME_FORMAT)}{SUFFIX}"


def free_path(started_at: datetime, directory: Path | None = None) -> Path:
    """A path for a new ride that does not already exist."""
    folder = directory or paths.activities_dir()
    candidate = folder / file_name(started_at)
    if not candidate.exists():
        return candidate
    stem = started_at.strftime(NAME_FORMAT)
    for number in range(2, MAX_COLLISIONS):
        candidate = folder / f"{stem}-{number}{SUFFIX}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"too many rides already start at {stem}")


def save(data: bytes, started_at: datetime, directory: Path | None = None) -> Path:
    """Write a ride into the store and return where it went."""
    folder = directory or paths.activities_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = free_path(started_at, folder)
    path.write_bytes(data)
    return path


def rides(directory: Path | None = None) -> list[Path]:
    """Every recorded ride, oldest first."""
    folder = directory or paths.activities_dir()
    if not folder.is_dir():
        return []
    return sorted(folder.glob(f"*{SUFFIX}"))
