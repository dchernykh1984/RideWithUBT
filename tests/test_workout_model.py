from __future__ import annotations

import pytest

from app.workout.model import (
    DurationKind,
    Repeat,
    Step,
    StepKind,
    Target,
    TargetKind,
    Workout,
    WorkoutError,
    WorkoutLibrary,
    flatten,
)


def effort(seconds: float = 300.0, low: float = 260.0, high: float = 300.0) -> Step:
    return Step(
        kind=StepKind.INTERVAL,
        name="Effort",
        duration=seconds,
        targets=(Target(TargetKind.POWER, low, high),),
    )


def test_a_target_says_what_holds_it() -> None:
    target = Target(TargetKind.POWER, 260, 300)

    assert target.holds(280)
    assert target.holds(260) and target.holds(300)
    assert not target.holds(259.9)
    assert target.middle == 280


def test_a_backwards_target_is_refused() -> None:
    with pytest.raises(WorkoutError, match="backwards"):
        Target(TargetKind.POWER, 300, 260)


def test_a_step_finds_its_targets_by_kind() -> None:
    step = Step(
        kind=StepKind.INTERVAL,
        duration=60,
        targets=(
            Target(TargetKind.POWER, 200, 240),
            Target(TargetKind.CADENCE, 85, 95),
        ),
    )

    assert step.power == Target(TargetKind.POWER, 200, 240)
    assert step.target(TargetKind.CADENCE) is not None
    assert step.target(TargetKind.HEART_RATE) is None


def test_a_timed_step_needs_a_time() -> None:
    with pytest.raises(WorkoutError, match="how long"):
        Step(kind=StepKind.INTERVAL, name="Effort")


def test_an_open_step_needs_nothing_else() -> None:
    step = Step(kind=StepKind.REST, duration_kind=DurationKind.OPEN)

    assert step.is_open
    assert step.duration is None


def test_a_step_without_a_name_is_still_labelled() -> None:
    assert Step(kind=StepKind.COOLDOWN, duration=60).label == "Cooldown"
    assert Step(kind=StepKind.COOLDOWN, duration=60, name="Spin down").label == (
        "Spin down"
    )


def test_repeats_expand_into_the_steps_actually_ridden() -> None:
    work, rest = effort(), Step(kind=StepKind.REST, duration=120)

    steps = list(flatten([Repeat(count=3, steps=(work, rest))]))

    assert steps == [work, rest, work, rest, work, rest]


def test_repeats_nest() -> None:
    inner = Repeat(count=2, steps=(effort(60),))
    outer = Repeat(count=2, steps=(inner, Step(kind=StepKind.REST, duration=30)))

    assert len(list(flatten([outer]))) == 6


def test_a_repeat_has_to_happen_and_has_to_contain_something() -> None:
    with pytest.raises(WorkoutError, match="at least once"):
        Repeat(count=0, steps=(effort(),))
    with pytest.raises(WorkoutError, match="repeats nothing"):
        Repeat(count=3, steps=())


def test_a_workout_totals_the_time_it_takes() -> None:
    workout = Workout(
        name="Threshold",
        steps=(
            Step(kind=StepKind.WARMUP, duration=600),
            Repeat(
                count=2, steps=(effort(480), Step(kind=StepKind.REST, duration=240))
            ),
            Step(kind=StepKind.COOLDOWN, duration=300),
        ),
    )

    assert len(workout.ridden_steps) == 6
    assert workout.total_time_s == 600 + 2 * (480 + 240) + 300
    assert not workout.has_open_steps


def test_a_workout_with_an_open_step_has_no_total_time() -> None:
    """It lasts as long as the rider takes, so quoting a duration would be a lie."""
    workout = Workout(
        name="Open",
        steps=(effort(), Step(kind=StepKind.REST, duration_kind=DurationKind.OPEN)),
    )

    assert workout.has_open_steps
    assert workout.total_time_s is None


def test_a_workout_needs_steps() -> None:
    with pytest.raises(WorkoutError, match="no steps"):
        Workout(name="Empty", steps=())


def test_a_library_finds_workouts_by_name() -> None:
    workout = Workout(name="Threshold", steps=(effort(),))
    library = WorkoutLibrary((workout,))

    assert len(library) == 1
    assert list(library) == [workout]
    assert library.named("Threshold") is workout
    with pytest.raises(WorkoutError, match="no workout named"):
        library.named("Nonesuch")
