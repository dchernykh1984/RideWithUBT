"""Fetching workouts from Garmin Connect.

The rider's own account, from the rider's own machine. The client is injected
rather than built here, so everything above it is tested against a fake and the
real one is created in exactly one place.

Garmin returns a workout's steps only when asked for that workout specifically -
the list gives names and ids and nothing to ride - so an import is one call for
the list and one per workout.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from app.workout.garmin_format import parse_workout
from app.workout.model import Workout, WorkoutError
from app.workout.schedule import Schedule, ScheduledRide

DEFAULT_LIMIT = 20


class GarminClient(Protocol):
    """The part of `garminconnect` this needs."""

    def get_workouts(self, start: int, end: int) -> list[dict[str, Any]]: ...

    def get_workout_by_id(self, workout_id: str) -> dict[str, Any]: ...

    def get_scheduled_workouts(self, *args: Any, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class WorkoutSummary:
    """A workout as the list shows it: enough to choose from, not to ride."""

    id: str
    name: str

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> WorkoutSummary | None:
        workout_id = raw.get("workoutId")
        if workout_id is None:
            return None
        return cls(id=str(workout_id), name=str(raw.get("workoutName") or "Workout"))


#: Where a scheduled entry might keep the date and the workout it points at.
#: Garmin has moved these around between versions of its own API, and a plan that
#: half-loads is worse than one that says which days it could not read - so each
#: is looked for in the places it has been, and an entry giving up none of them
#: is skipped rather than guessed at.
DATE_FIELDS = ("calendarDate", "date", "scheduleDate")
WORKOUT_FIELDS = ("workout", "workoutDTO", "workoutSummary")
NAME_FIELDS = ("workoutName", "name", "title")


def scheduled_entry(raw: dict[str, Any]) -> ScheduledRide | None:
    """Read one day of a plan, or None if this entry does not say enough."""
    day = _first(raw, DATE_FIELDS)
    workout = next(
        (raw[field] for field in WORKOUT_FIELDS if isinstance(raw.get(field), dict)),
        raw,
    )
    name = _first(workout, NAME_FIELDS) or _first(raw, NAME_FIELDS)
    if not day or not name:
        return None
    try:
        on = date.fromisoformat(str(day)[:10])
    except ValueError:
        return None
    identifier = workout.get("workoutId") or raw.get("workoutId") or ""
    return ScheduledRide(on=on, workout_name=str(name), source_id=str(identifier))


def _first(raw: dict[str, Any], fields: tuple[str, ...]) -> Any:
    return next((raw[field] for field in fields if raw.get(field)), None)


@dataclass
class GarminWorkouts:
    """Reading workouts out of one Garmin Connect account."""

    client: GarminClient

    def summaries(self, limit: int = DEFAULT_LIMIT) -> list[WorkoutSummary]:
        """The account's workouts, names and ids only.

        Not called `list`: inside a class that would shadow the builtin, and
        every `list[...]` annotation in the class body would resolve to this
        method instead of the type.
        """
        raw = self.client.get_workouts(0, limit)
        found = (WorkoutSummary.from_raw(item) for item in raw)
        return [item for item in found if item is not None]

    def fetch(self, workout_id: str) -> Workout:
        return parse_workout(
            self.client.get_workout_by_id(workout_id), source=f"garmin:{workout_id}"
        )

    def schedule(self, start: date, end: date) -> tuple[Schedule, list[str]]:
        """The plan between two dates, and the entries that could not be read."""
        raw = self.client.get_scheduled_workouts(start.isoformat(), end.isoformat())
        entries = raw if isinstance(raw, list) else raw.get("calendarItems", [])
        rides, skipped = [], []
        for item in entries:
            ride = scheduled_entry(item) if isinstance(item, dict) else None
            if ride is None:
                skipped.append(str(item)[:80])
                continue
            rides.append(ride)
        return Schedule.of(rides), skipped

    def download(
        self, summaries: Sequence[WorkoutSummary]
    ) -> Iterator[tuple[WorkoutSummary, Workout | None, str]]:
        """Fetch each workout, reporting the ones that could not be read.

        One workout Garmin will not give us - a running workout with a step this
        app does not know, say - must not stop the rest of the import.
        """
        for summary in summaries:
            try:
                yield summary, self.fetch(summary.id), ""
            except (WorkoutError, KeyError, ValueError) as error:
                yield summary, None, str(error)
