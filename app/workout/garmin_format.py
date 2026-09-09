"""Reading the workout format Garmin Connect stores.

Garmin's own JSON, as its API returns it: a workout holds segments, a segment
holds steps, and a step is either something to do (`ExecutableStepDTO`) or a
group to repeat (`RepeatGroupDTO`). Every enumerated value arrives as a small
object rather than a string, so the parsing is mostly reaching one key deeper
than looks necessary.

Two of Garmin's names do not say what they mean, and both are read here rather
than trusted:

* an open-ended step's end condition is called **`lap.button`** - it ends when
  the rider presses the lap button, which is our open duration;
* a power target's type is **`power.zone`** whether the values are watts or a
  zone number. The values are taken as given, which is what they are when the
  workout was written with watts.
"""

from __future__ import annotations

from typing import Any

from app.workout.model import (
    DurationKind,
    Element,
    Repeat,
    Step,
    StepKind,
    Target,
    TargetKind,
    Workout,
    WorkoutError,
)

REPEAT_TYPE = "RepeatGroupDTO"
EXECUTABLE_TYPE = "ExecutableStepDTO"

STEP_KINDS = {
    "warmup": StepKind.WARMUP,
    "cooldown": StepKind.COOLDOWN,
    "interval": StepKind.INTERVAL,
    "rest": StepKind.REST,
    "recovery": StepKind.REST,
}
DURATION_KINDS = {
    "time": DurationKind.TIME,
    "distance": DurationKind.DISTANCE,
    "lap.button": DurationKind.OPEN,
    "iterations": DurationKind.OPEN,
}
TARGET_KINDS = {
    "power.zone": TargetKind.POWER,
    "heart.rate.zone": TargetKind.HEART_RATE,
    "cadence": TargetKind.CADENCE,
}
NO_TARGET = "no.target"


def _key(raw: dict[str, Any] | None, name: str) -> str:
    """Garmin wraps every enumerated value in an object with a key beside it."""
    if not raw:
        return ""
    return str(raw.get(name, ""))


def parse_targets(raw: dict[str, Any]) -> tuple[Target, ...]:
    """A step's targets. Garmin carries at most two, in named slots."""
    targets = []
    for prefix in ("target", "secondaryTarget"):
        kind_key = _key(raw.get(f"{prefix}Type"), "workoutTargetTypeKey")
        if not kind_key or kind_key == NO_TARGET:
            continue
        kind = TARGET_KINDS.get(kind_key)
        low, high = raw.get(f"{prefix}ValueOne"), raw.get(f"{prefix}ValueTwo")
        if kind is None or low is None or high is None:
            continue
        targets.append(Target(kind=kind, low=float(low), high=float(high)))
    return tuple(targets)


def parse_step(raw: dict[str, Any]) -> Element:
    if raw.get("type") == REPEAT_TYPE:
        return Repeat(
            count=int(raw.get("numberOfIterations", 1)),
            steps=tuple(parse_step(item) for item in raw.get("workoutSteps", ())),
        )
    kind_key = _key(raw.get("stepType"), "stepTypeKey")
    kind = STEP_KINDS.get(kind_key)
    if kind is None:
        raise WorkoutError(f"unknown Garmin step type {kind_key!r}")
    duration_key = _key(raw.get("endCondition"), "conditionTypeKey")
    duration_kind = DURATION_KINDS.get(duration_key, DurationKind.TIME)
    value = raw.get("endConditionValue")
    if duration_kind is DurationKind.OPEN:
        duration = None
    elif value is None:
        raise WorkoutError(f"Garmin step {kind_key!r} has no {duration_key} to run for")
    else:
        duration = float(value)
    return Step(
        kind=kind,
        name=str(raw.get("stepDescription") or ""),
        duration_kind=duration_kind,
        duration=duration,
        targets=parse_targets(raw),
    )


def parse_workout(raw: dict[str, Any], source: str = "garmin") -> Workout:
    """Turn one downloaded Garmin workout into the app's own model."""
    segments = raw.get("workoutSegments") or []
    steps: list[Element] = []
    for segment in segments:
        steps.extend(parse_step(item) for item in segment.get("workoutSteps", ()))
    if not steps:
        raise WorkoutError(
            f"Garmin workout {raw.get('workoutName', '')!r} has no steps in it"
        )
    return Workout(
        name=str(raw.get("workoutName") or "Garmin workout"),
        description=str(raw.get("description") or ""),
        sport=_key(raw.get("sportType"), "sportTypeKey") or "cycling",
        steps=tuple(steps),
        source=source,
    )
