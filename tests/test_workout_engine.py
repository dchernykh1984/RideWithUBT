from __future__ import annotations

from pathlib import Path

import pytest

from app.workout.engine import WorkoutEngine
from app.workout.model import (
    DurationKind,
    Repeat,
    Step,
    StepKind,
    Target,
    TargetKind,
    Workout,
)
from app.workout.plan_format import load_workout

EXAMPLE = Path(__file__).parent / "data" / "cycling_intervals.json"


def timed(seconds: float, name: str = "", low: float = 200, high: float = 240) -> Step:
    return Step(
        kind=StepKind.INTERVAL,
        name=name,
        duration=seconds,
        targets=(Target(TargetKind.POWER, low, high),),
    )


def simple() -> Workout:
    return Workout(
        name="Two steps",
        steps=(
            timed(60, "First"),
            Step(kind=StepKind.REST, duration=30, name="Second"),
        ),
    )


def test_a_workout_starts_on_its_first_step() -> None:
    engine = WorkoutEngine(simple())

    progress = engine.progress()

    assert progress.step is not None
    assert progress.step.step.name == "First"
    assert progress.step.next_step is not None
    assert progress.steps_total == 2
    assert not progress.finished


def test_time_moves_through_a_step() -> None:
    engine = WorkoutEngine(simple())

    progress = engine.update(seconds=15.0)

    assert progress.step is not None
    assert progress.step.elapsed_s == 15.0
    assert progress.step.remaining == 45.0
    assert progress.step.fraction == pytest.approx(0.25)


def test_a_step_that_runs_out_hands_the_rest_to_the_next_one() -> None:
    """Throwing the overshoot away drifts a workout by a frame every interval."""
    engine = WorkoutEngine(simple())

    progress = engine.update(seconds=75.0)

    assert progress.step is not None
    assert progress.step.step.name == "Second"
    assert progress.step.elapsed_s == pytest.approx(15.0)


def test_one_update_can_cross_several_steps() -> None:
    engine = WorkoutEngine(simple())

    progress = engine.update(seconds=1000.0)

    assert progress.finished
    assert progress.step is None
    assert progress.steps_done == 2
    assert progress.steps_left == 0


def test_a_finished_workout_stays_finished() -> None:
    engine = WorkoutEngine(simple())
    engine.update(seconds=1000.0)

    progress = engine.update(seconds=10.0)

    assert progress.finished
    assert engine.current is None


def test_distance_steps_count_metres_not_seconds() -> None:
    workout = Workout(
        name="Build",
        steps=(
            Step(
                kind=StepKind.INTERVAL,
                name="1km",
                duration_kind=DurationKind.DISTANCE,
                duration=1000.0,
            ),
            Step(kind=StepKind.REST, duration=60),
        ),
    )
    engine = WorkoutEngine(workout)

    engine.update(seconds=300.0, metres=400.0)

    assert engine.current is not None
    assert engine.current.name == "1km"
    progress = engine.progress()
    assert progress.step is not None
    assert progress.step.remaining == 600.0

    engine.update(seconds=10.0, metres=650.0)
    assert engine.current is not None
    assert engine.current.kind is StepKind.REST


def test_an_open_step_never_ends_on_its_own() -> None:
    workout = Workout(
        name="Open",
        steps=(
            Step(kind=StepKind.REST, name="Recover", duration_kind=DurationKind.OPEN),
            timed(60, "After"),
        ),
    )
    engine = WorkoutEngine(workout)

    progress = engine.update(seconds=3600.0, metres=20000.0)

    assert progress.step is not None
    assert progress.step.step.name == "Recover"
    assert progress.step.remaining is None
    assert progress.step.fraction is None, "there is no fraction of an unknown length"
    assert progress.step.elapsed_s == 3600.0


def test_the_rider_ends_an_open_step_themselves() -> None:
    workout = Workout(
        name="Open",
        steps=(
            Step(kind=StepKind.REST, name="Recover", duration_kind=DurationKind.OPEN),
            timed(60, "After"),
        ),
    )
    engine = WorkoutEngine(workout)
    engine.update(seconds=120.0)

    engine.advance()

    assert engine.current is not None
    assert engine.current.name == "After"


def test_advancing_past_the_end_is_harmless() -> None:
    engine = WorkoutEngine(simple())
    engine.update(seconds=1000.0)

    engine.advance()

    assert engine.finished


def test_holding_the_target_is_reported() -> None:
    engine = WorkoutEngine(simple())

    inside = engine.update(seconds=1.0, power_w=220.0)
    outside = engine.update(seconds=1.0, power_w=150.0)

    assert inside.step is not None and inside.step.on_target
    assert outside.step is not None and outside.step.on_target is False


def test_with_no_power_there_is_nothing_to_judge() -> None:
    """A rider with no power meter is not failing the target; it is unknown."""
    engine = WorkoutEngine(simple())

    progress = engine.update(seconds=1.0, power_w=None)

    assert progress.step is not None
    assert progress.step.on_target is None


def test_a_step_with_no_power_target_is_never_off_target() -> None:
    workout = Workout(
        name="Free",
        steps=(Step(kind=StepKind.WARMUP, duration=300),),
    )

    progress = WorkoutEngine(workout).update(seconds=1.0, power_w=400.0)

    assert progress.step is not None
    assert progress.step.on_target is None


def test_repeats_are_ridden_one_at_a_time() -> None:
    workout = Workout(
        name="Intervals",
        steps=(Repeat(count=3, steps=(timed(30, "On"), timed(30, "Off"))),),
    )
    engine = WorkoutEngine(workout)

    assert engine.progress().steps_total == 6

    engine.update(seconds=45.0)
    assert engine.current is not None and engine.current.name == "Off"
    engine.update(seconds=30.0)
    assert engine.current is not None and engine.current.name == "On"


def test_the_total_elapsed_time_is_the_whole_workout() -> None:
    engine = WorkoutEngine(simple())

    engine.update(seconds=20.0)
    engine.update(seconds=20.0)

    assert engine.progress().total_elapsed_s == pytest.approx(40.0)


def test_a_real_generated_plan_rides_from_start_to_finish() -> None:
    """The example plan has a distance step and an open recovery in it."""
    engine = WorkoutEngine(load_workout(EXAMPLE))

    for _ in range(4000):
        if engine.finished:
            break
        progress = engine.update(seconds=1.0, metres=9.0, power_w=270.0)
        if progress.step is not None and progress.step.step.is_open:
            engine.advance()  # the rider ends each recovery after a second

    assert engine.finished
