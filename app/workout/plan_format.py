"""Reading the workout format `training_plan_generator` writes.

That generator already exists and already produces plans, so its JSON is the
first thing this app can import. One quirk is worth stating plainly, because it
is the kind of thing that silently rides the wrong workout:

**`duration_seconds` is not always seconds.** When a step says
`"duration_type": "distance"`, the same field holds metres; when it says
`"open"`, it holds nothing and the step runs until the rider ends it. The field
is read according to the type beside it, never on its own.
"""

from __future__ import annotations

import json
from pathlib import Path
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

REPEAT_TYPE = "repeat"
# The generator writes durations in this one field whatever they measure.
DURATION_FIELD = "duration_seconds"


def parse_target(raw: dict[str, Any]) -> Target:
    try:
        kind = TargetKind(str(raw["type"]))
    except (KeyError, ValueError) as error:
        raise WorkoutError(f"unknown target {raw.get('type')!r}") from error
    return Target(kind=kind, low=float(raw["low"]), high=float(raw["high"]))


def parse_duration(raw: dict[str, Any]) -> tuple[DurationKind, float | None]:
    """Read the duration and what it measures, together."""
    kind = DurationKind(str(raw.get("duration_type", "time")))
    if kind is DurationKind.OPEN:
        return kind, None
    value = raw.get(DURATION_FIELD)
    if value is None:
        raise WorkoutError(f"step {raw.get('name', '')!r} has no duration")
    return kind, float(value)


def parse_step(raw: dict[str, Any]) -> Element:
    kind_name = str(raw.get("type", ""))
    if kind_name == REPEAT_TYPE:
        return Repeat(
            count=int(raw["count"]),
            steps=tuple(parse_step(item) for item in raw.get("steps", ())),
        )
    try:
        kind = StepKind(kind_name)
    except ValueError as error:
        raise WorkoutError(f"unknown step type {kind_name!r}") from error
    duration_kind, duration = parse_duration(raw)
    return Step(
        kind=kind,
        name=str(raw.get("name", "")),
        duration_kind=duration_kind,
        duration=duration,
        targets=tuple(parse_target(item) for item in raw.get("targets", ())),
    )


def parse_workout(raw: dict[str, Any], source: str = "") -> Workout:
    try:
        steps = tuple(parse_step(item) for item in raw["steps"])
    except KeyError as error:
        raise WorkoutError(f"workout is missing {error.args[0]!r}") from None
    ftp = raw.get("ftp_watts")
    return Workout(
        name=str(raw.get("name", "Workout")),
        description=str(raw.get("description", "")),
        sport=str(raw.get("sport", "cycling")),
        ftp_watts=int(ftp) if ftp is not None else None,
        steps=steps,
        source=source,
    )


def load_workout(path: Path) -> Workout:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return parse_workout(raw, source=str(path))
