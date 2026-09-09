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
from typing import Any, Protocol

from app.workout.garmin_format import parse_workout
from app.workout.model import Workout, WorkoutError

DEFAULT_LIMIT = 20


class GarminClient(Protocol):
    """The part of `garminconnect` this needs."""

    def get_workouts(self, start: int, end: int) -> list[dict[str, Any]]: ...

    def get_workout_by_id(self, workout_id: str) -> dict[str, Any]: ...


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


@dataclass
class GarminWorkouts:
    """Reading workouts out of one Garmin Connect account."""

    client: GarminClient

    def list(self, limit: int = DEFAULT_LIMIT) -> list[WorkoutSummary]:
        raw = self.client.get_workouts(0, limit)
        found = (WorkoutSummary.from_raw(item) for item in raw)
        return [item for item in found if item is not None]

    def fetch(self, workout_id: str) -> Workout:
        return parse_workout(
            self.client.get_workout_by_id(workout_id), source=f"garmin:{workout_id}"
        )

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
