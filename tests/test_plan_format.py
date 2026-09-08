"""Read against a real file from `training_plan_generator`, not a made-up one:
the point of this reader is that plans that project already writes can be
ridden here."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.workout.model import DurationKind, Repeat, StepKind, TargetKind, WorkoutError
from app.workout.plan_format import load_workout, parse_workout

EXAMPLE = Path(__file__).parent / "data" / "cycling_intervals.json"


def test_a_real_generated_plan_reads() -> None:
    workout = load_workout(EXAMPLE)

    assert workout.name == "3x8 Cycling Intervals"
    assert workout.sport == "cycling"
    assert workout.ftp_watts == 260
    assert workout.source.endswith("cycling_intervals.json")


def test_its_repeats_expand_the_way_the_plan_intends() -> None:
    workout = load_workout(EXAMPLE)

    # Warm-up, a 1 km build, then three efforts each followed by a recovery,
    # then the cool-down.
    assert len(workout.ridden_steps) == 2 + 3 * 2 + 1
    assert isinstance(workout.steps[2], Repeat)


def test_a_distance_step_is_read_as_metres_not_seconds() -> None:
    """The field is called duration_seconds whatever it measures.

    Reading it as seconds would turn a one kilometre effort into a seventeen
    minute one, and nothing would look wrong until the rider was still going.
    """
    build = load_workout(EXAMPLE).ridden_steps[1]

    assert build.name == "1km Build"
    assert build.duration_kind is DurationKind.DISTANCE
    assert build.duration == 1000.0


def test_an_open_recovery_has_no_duration_at_all() -> None:
    recovery = load_workout(EXAMPLE).ridden_steps[3]

    assert recovery.kind is StepKind.REST
    assert recovery.is_open
    assert recovery.duration is None


def test_several_targets_on_one_step_all_survive() -> None:
    effort = load_workout(EXAMPLE).ridden_steps[2]

    assert effort.name == "8min Effort"
    assert effort.duration == 480.0
    assert {target.kind for target in effort.targets} == {
        TargetKind.POWER,
        TargetKind.CADENCE,
        TargetKind.HEART_RATE,
    }
    power = effort.power
    assert power is not None
    assert (power.low, power.high) == (260.0, 300.0)


def test_the_whole_plan_has_no_total_time_because_a_step_is_open() -> None:
    assert load_workout(EXAMPLE).total_time_s is None


def test_a_workout_without_steps_says_so() -> None:
    with pytest.raises(WorkoutError, match="missing 'steps'"):
        parse_workout({"name": "Nothing"})


def test_an_unknown_step_type_is_refused_rather_than_skipped() -> None:
    """Skipping it would ride a different workout than the one that was written."""
    raw = {"name": "W", "steps": [{"type": "sprint", "duration_seconds": 30}]}

    with pytest.raises(WorkoutError, match="unknown step type 'sprint'"):
        parse_workout(raw)


def test_an_unknown_target_is_refused() -> None:
    raw = {
        "name": "W",
        "steps": [
            {
                "type": "interval",
                "duration_seconds": 30,
                "targets": [{"type": "vibes", "low": 1, "high": 2}],
            }
        ],
    }

    with pytest.raises(WorkoutError, match="unknown target 'vibes'"):
        parse_workout(raw)


def test_a_timed_step_with_no_duration_is_refused() -> None:
    raw = {"name": "W", "steps": [{"type": "interval", "name": "Effort"}]}

    with pytest.raises(WorkoutError, match="no duration"):
        parse_workout(raw)


def test_defaults_fill_in_for_a_minimal_plan() -> None:
    workout = parse_workout({"steps": [{"type": "interval", "duration_seconds": 60}]})

    assert workout.name == "Workout"
    assert workout.sport == "cycling"
    assert workout.ftp_watts is None
    assert workout.ridden_steps[0].duration_kind is DurationKind.TIME


def test_a_plan_written_out_and_read_back(tmp_path: Path) -> None:
    raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    copy = tmp_path / "copy.json"
    copy.write_text(json.dumps(raw), encoding="utf-8")

    assert load_workout(copy).ridden_steps == load_workout(EXAMPLE).ridden_steps
