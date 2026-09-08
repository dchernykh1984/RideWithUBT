"""The workouts a rider has to choose from.

Whatever has been imported, sitting as plan-format JSON in the static data tree.
A workout that fails to read is skipped rather than taking the library down with
it: one bad file should not stop a rider from starting any of the others.
"""

from __future__ import annotations

from pathlib import Path

from app import paths
from app.workout.model import Workout, WorkoutError, WorkoutLibrary
from app.workout.plan_format import load_workout

SUFFIX = ".json"


def load_library(directory: Path | None = None) -> WorkoutLibrary:
    folder = directory or paths.workouts_dir()
    if not folder.is_dir():
        return WorkoutLibrary()
    workouts = []
    for path in sorted(folder.glob(f"*{SUFFIX}")):
        try:
            workouts.append(load_workout(path))
        except WorkoutError, ValueError:
            continue
    return WorkoutLibrary(tuple(workouts))


def unreadable(directory: Path | None = None) -> list[Path]:
    """The files in the library that could not be read, so they can be reported."""
    folder = directory or paths.workouts_dir()
    if not folder.is_dir():
        return []
    broken = []
    for path in sorted(folder.glob(f"*{SUFFIX}")):
        try:
            load_workout(path)
        except WorkoutError, ValueError:
            broken.append(path)
    return broken


def find(reference: str, directory: Path | None = None) -> Workout:
    """A workout by file path, or by name from the library."""
    path = Path(reference)
    if path.is_file():
        return load_workout(path)
    return load_library(directory).named(reference)
