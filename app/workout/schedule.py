"""What the rider is meant to do, and when.

A training plan in Garmin Connect is a calendar: workouts placed on dates. This
app does not run the plan - it has no opinion about periodisation and no business
having one - it just knows which workout today's ride is supposed to be, so the
rider does not have to look it up on their phone before getting on the bike.

The schedule is stored beside everything else in the one data tree, and it names
workouts rather than containing them: the workouts themselves live in the
library, where a workout imported from a plan and one written by hand are the
same thing.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app import paths

FILE_NAME = "schedule.json"


class ScheduleError(ValueError):
    """A schedule that cannot be read."""


@dataclass(frozen=True)
class ScheduledRide:
    """One workout, on one day."""

    on: date
    workout_name: str
    source_id: str = ""

    @property
    def is_past(self) -> bool:
        return self.on < date.today()

    def as_dict(self) -> dict[str, str]:
        return {
            "date": self.on.isoformat(),
            "workout": self.workout_name,
            "source_id": self.source_id,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, str]) -> ScheduledRide:
        try:
            return cls(
                on=date.fromisoformat(str(raw["date"])),
                workout_name=str(raw["workout"]),
                source_id=str(raw.get("source_id", "")),
            )
        except (KeyError, ValueError) as error:
            raise ScheduleError(f"unreadable entry: {raw}") from error


@dataclass(frozen=True)
class Schedule:
    """Everything the plan says, in date order."""

    rides: tuple[ScheduledRide, ...] = ()

    def __iter__(self) -> Iterator[ScheduledRide]:
        return iter(self.rides)

    def __len__(self) -> int:
        return len(self.rides)

    @classmethod
    def of(cls, rides: Sequence[ScheduledRide]) -> Schedule:
        return cls(tuple(sorted(rides, key=lambda ride: (ride.on, ride.workout_name))))

    def on(self, day: date) -> tuple[ScheduledRide, ...]:
        """Everything scheduled for a day. A plan may put two rides on one."""
        return tuple(ride for ride in self.rides if ride.on == day)

    def today(self) -> tuple[ScheduledRide, ...]:
        return self.on(date.today())

    def next_ride(self, after: date | None = None) -> ScheduledRide | None:
        """The next thing due, for a rider who missed a day or two."""
        from_day = after or date.today()
        upcoming = [ride for ride in self.rides if ride.on >= from_day]
        return upcoming[0] if upcoming else None

    @classmethod
    def load(cls, directory: Path | None = None) -> Schedule:
        path = _path(directory)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return cls()
        if not isinstance(raw, list):
            return cls()
        rides = []
        for item in raw:
            try:
                rides.append(ScheduledRide.from_dict(item))
            except ScheduleError, TypeError:
                # One unreadable day must not lose the rest of the plan.
                continue
        return cls.of(rides)

    def save(self, directory: Path | None = None) -> Path:
        path = _path(directory)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([ride.as_dict() for ride in self.rides], indent=2) + "\n",
            encoding="utf-8",
        )
        return path


def _path(directory: Path | None) -> Path:
    return (directory or paths.data_root()) / FILE_NAME
