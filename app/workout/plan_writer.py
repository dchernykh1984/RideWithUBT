"""Writing a workout back out in the plan format.

Whatever a workout was imported from, it is stored in one format - the one
`training_plan_generator` writes and this app reads - so the library has a single
shape and a workout can be looked at, edited or shared as a file.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.workout.model import DurationKind, Element, Repeat, Step, Workout


def describe_target(target: Any) -> dict[str, Any]:
    return {"type": str(target.kind), "low": target.low, "high": target.high}


def describe_step(element: Element) -> dict[str, Any]:
    if isinstance(element, Repeat):
        return {
            "type": "repeat",
            "count": element.count,
            "steps": [describe_step(item) for item in element.steps],
        }
    return _describe_executable(element)


def _describe_executable(step: Step) -> dict[str, Any]:
    raw: dict[str, Any] = {"type": str(step.kind)}
    if step.name:
        raw["name"] = step.name
    if step.duration_kind is not DurationKind.TIME:
        raw["duration_type"] = str(step.duration_kind)
    if step.duration is not None:
        # The field is called duration_seconds whatever it measures - metres for
        # a distance step - because that is what the format calls it.
        raw["duration_seconds"] = step.duration
    if step.targets:
        raw["targets"] = [describe_target(target) for target in step.targets]
    return raw


def describe_workout(workout: Workout) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "name": workout.name,
        "sport": workout.sport,
        "steps": [describe_step(item) for item in workout.steps],
    }
    if workout.description:
        raw["description"] = workout.description
    if workout.ftp_watts is not None:
        raw["ftp_watts"] = workout.ftp_watts
    return raw


def describe_all(workouts: Sequence[Workout]) -> list[dict[str, Any]]:
    return [describe_workout(workout) for workout in workouts]
