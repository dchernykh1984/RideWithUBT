"""The workouts a rider has to choose from.

Whatever has been imported, sitting as plan-format JSON in the static data tree.
A workout that fails to read is skipped rather than taking the library down with
it: one bad file should not stop a rider from starting any of the others.
"""

from __future__ import annotations

import json
from pathlib import Path

from app import paths
from app.workout.model import Workout, WorkoutError, WorkoutLibrary
from app.workout.plan_format import load_workout
from app.workout.plan_writer import describe_workout

SUFFIX = ".json"


def load_library(directory: Path | None = None) -> WorkoutLibrary:
    folder = directory or paths.workouts_dir()
    if not folder.is_dir():
        return WorkoutLibrary()
    workouts = []
    for path in sorted(folder.glob(f"*{SUFFIX}")):
        try:
            workouts.append(load_workout(path))
        except WorkoutError, ValueError, OSError:
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
        except WorkoutError, ValueError, OSError:
            broken.append(path)
    return broken


def file_name_for(workout: Workout) -> str:
    """A file name from a workout's own name, safe on every platform."""
    kept = [
        character if character.isalnum() or character in " -_" else "-"
        for character in workout.name
    ]
    slug = "".join(kept).strip().replace(" ", "-").lower()
    while "--" in slug:
        slug = slug.replace("--", "-")
    return f"{slug or 'workout'}{SUFFIX}"


def save(workout: Workout, directory: Path | None = None) -> Path:
    """Write a workout into the library, in the one format it stores."""
    folder = directory or paths.workouts_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / file_name_for(workout)
    path.write_text(
        json.dumps(describe_workout(workout), indent=2) + "\n", encoding="utf-8"
    )
    return path


def find(reference: str, directory: Path | None = None) -> Workout:
    """A workout by file path, or by name from the library."""
    path = Path(reference)
    if path.is_file():
        return load_workout(path)
    return load_library(directory).named(reference)
