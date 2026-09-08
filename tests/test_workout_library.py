from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import paths
from app.workout import library
from app.workout.model import WorkoutError

EXAMPLE = Path(__file__).parent / "data" / "cycling_intervals.json"


def put(directory: Path, name: str, raw: object) -> Path:
    path = directory / f"{name}.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def example_raw() -> dict[str, object]:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_an_empty_library_is_not_an_error() -> None:
    assert len(library.load_library()) == 0
    assert library.unreadable() == []


def test_workouts_are_read_from_the_static_tree() -> None:
    paths.ensure_data_tree()
    put(paths.workouts_dir(), "intervals", example_raw())

    loaded = library.load_library()

    assert len(loaded) == 1
    assert loaded.named("3x8 Cycling Intervals").ftp_watts == 260


def test_one_broken_file_does_not_take_the_library_down(tmp_path: Path) -> None:
    """A rider with a bad file should still be able to start any of the others."""
    put(tmp_path, "good", example_raw())
    put(tmp_path, "bad", {"name": "Broken", "steps": [{"type": "sprint"}]})

    loaded = library.load_library(tmp_path)

    assert [workout.name for workout in loaded] == ["3x8 Cycling Intervals"]


def test_the_broken_files_can_still_be_named(tmp_path: Path) -> None:
    """Skipping quietly would leave a rider wondering where their workout went."""
    put(tmp_path, "bad", {"name": "Broken", "steps": [{"type": "sprint"}]})

    assert [path.name for path in library.unreadable(tmp_path)] == ["bad.json"]


def test_a_workout_is_found_by_file_path() -> None:
    assert library.find(str(EXAMPLE)).name == "3x8 Cycling Intervals"


def test_a_workout_is_found_by_name_in_the_library(tmp_path: Path) -> None:
    put(tmp_path, "intervals", example_raw())

    assert library.find("3x8 Cycling Intervals", tmp_path).ftp_watts == 260


def test_a_workout_that_is_neither_a_file_nor_in_the_library(tmp_path: Path) -> None:
    with pytest.raises(WorkoutError, match="no workout named"):
        library.find("Nonesuch", tmp_path)


def test_the_workouts_directory_is_part_of_the_one_data_tree() -> None:
    paths.ensure_data_tree()

    assert paths.workouts_dir().is_dir()
    assert paths.workouts_dir().parent == paths.data_root()
