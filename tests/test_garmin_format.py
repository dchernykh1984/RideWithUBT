"""Reading Garmin's own workout JSON.

The fixtures are built in the shape Garmin's API returns and
`training_plan_generator` writes - enumerated values wrapped in objects, steps
either executable or a repeat group - so a change in the reader that drifts from
that shape is caught here."""

from __future__ import annotations

from typing import Any

import pytest

from app.workout.garmin_format import parse_workout
from app.workout.model import DurationKind, Repeat, StepKind, TargetKind, WorkoutError


def step(
    kind: str = "interval",
    seconds: float | None = 300.0,
    condition: str = "time",
    name: str = "",
    target: tuple[str, float, float] | None = ("power.zone", 260, 300),
    second_target: tuple[str, float, float] | None = None,
) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "type": "ExecutableStepDTO",
        "stepOrder": 1,
        "stepType": {"stepTypeId": 3, "stepTypeKey": kind},
        "endCondition": {"conditionTypeKey": condition},
        "endConditionValue": seconds,
    }
    if name:
        raw["stepDescription"] = name
    if target is None:
        raw["targetType"] = {"workoutTargetTypeKey": "no.target"}
    else:
        key, low, high = target
        raw["targetType"] = {"workoutTargetTypeKey": key}
        raw["targetValueOne"] = low
        raw["targetValueTwo"] = high
    if second_target is not None:
        key, low, high = second_target
        raw["secondaryTargetType"] = {"workoutTargetTypeKey": key}
        raw["secondaryTargetValueOne"] = low
        raw["secondaryTargetValueTwo"] = high
    return raw


def workout(*steps: dict[str, Any], name: str = "Threshold") -> dict[str, Any]:
    return {
        "workoutName": name,
        "sportType": {"sportTypeId": 2, "sportTypeKey": "cycling"},
        "workoutSegments": [{"segmentOrder": 1, "workoutSteps": list(steps)}],
    }


def test_a_downloaded_workout_becomes_the_app_model() -> None:
    parsed = parse_workout(workout(step(kind="warmup", seconds=600.0)))

    assert parsed.name == "Threshold"
    assert parsed.sport == "cycling"
    assert parsed.source == "garmin"
    (only,) = parsed.ridden_steps
    assert only.kind is StepKind.WARMUP
    assert only.duration == 600.0


def test_a_step_description_becomes_its_name() -> None:
    parsed = parse_workout(workout(step(name="8min Effort")))

    assert parsed.ridden_steps[0].name == "8min Effort"


def test_the_lap_button_is_what_garmin_calls_an_open_step() -> None:
    """A name that does not say what it means, so it is read rather than trusted."""
    parsed = parse_workout(
        workout(step(kind="rest", condition="lap.button", seconds=None))
    )

    recovery = parsed.ridden_steps[0]
    assert recovery.duration_kind is DurationKind.OPEN
    assert recovery.duration is None


def test_a_distance_step_keeps_its_metres() -> None:
    parsed = parse_workout(workout(step(condition="distance", seconds=1000.0)))

    build = parsed.ridden_steps[0]
    assert build.duration_kind is DurationKind.DISTANCE
    assert build.duration == 1000.0


def test_both_of_garmins_two_target_slots_are_read() -> None:
    parsed = parse_workout(
        workout(
            step(target=("power.zone", 260, 300), second_target=("cadence", 88, 92))
        )
    )

    kinds = {target.kind for target in parsed.ridden_steps[0].targets}
    assert kinds == {TargetKind.POWER, TargetKind.CADENCE}


def test_a_step_with_nothing_to_hold_has_no_targets() -> None:
    parsed = parse_workout(workout(step(target=None)))

    assert parsed.ridden_steps[0].targets == ()


def test_a_half_written_target_is_left_out_rather_than_guessed() -> None:
    raw = step()
    del raw["targetValueTwo"]

    assert parse_workout(workout(raw)).ridden_steps[0].targets == ()


def test_a_repeat_group_expands() -> None:
    group = {
        "type": "RepeatGroupDTO",
        "stepOrder": 2,
        "numberOfIterations": 3,
        "endCondition": {"conditionTypeKey": "iterations"},
        "endConditionValue": 3.0,
        "workoutSteps": [step(seconds=480.0), step(kind="rest", seconds=240.0)],
    }

    parsed = parse_workout(workout(step(kind="warmup", seconds=600.0), group))

    assert isinstance(parsed.steps[1], Repeat)
    assert len(parsed.ridden_steps) == 1 + 3 * 2


def test_steps_from_every_segment_are_kept() -> None:
    raw = workout(step())
    raw["workoutSegments"].append({"segmentOrder": 2, "workoutSteps": [step()]})

    assert len(parse_workout(raw).ridden_steps) == 2


def test_an_unknown_step_type_is_refused_rather_than_guessed() -> None:
    with pytest.raises(WorkoutError, match="unknown Garmin step type"):
        parse_workout(workout(step(kind="swim.drill")))


def test_a_timed_step_with_no_duration_is_refused() -> None:
    with pytest.raises(WorkoutError, match="no time to run for"):
        parse_workout(workout(step(seconds=None)))


def test_a_workout_with_no_steps_is_not_a_workout() -> None:
    with pytest.raises(WorkoutError, match="no steps in it"):
        parse_workout(workout())


def test_defaults_for_a_sparse_workout() -> None:
    parsed = parse_workout({"workoutSegments": [{"workoutSteps": [step()]}]})

    assert parsed.name == "Garmin workout"
    assert parsed.sport == "cycling"
