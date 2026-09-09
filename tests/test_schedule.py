"""The plan's calendar: which workout today's ride is meant to be.

Garmin has moved the fields of a scheduled entry around between versions of its
own API, and this app cannot check against a real account in a test - so the
reading is deliberately forgiving about where a date lives and deliberately
unforgiving about inventing one that is not there."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from app import paths
from app.services.garmin import GarminWorkouts, scheduled_entry
from app.workout.schedule import Schedule, ScheduledRide, ScheduleError

TODAY = date.today()


def ride(days_from_now: int = 0, name: str = "Threshold") -> ScheduledRide:
    return ScheduledRide(on=TODAY + timedelta(days=days_from_now), workout_name=name)


# Reading a plan.


def test_an_empty_plan_is_not_an_error() -> None:
    assert len(Schedule.load()) == 0
    assert Schedule().today() == ()
    assert Schedule().next_ride() is None


def test_a_plan_is_kept_in_date_order_however_it_arrived() -> None:
    plan = Schedule.of([ride(5), ride(1), ride(3)])

    assert [entry.on for entry in plan] == [
        TODAY + timedelta(days=days) for days in (1, 3, 5)
    ]


def test_a_day_with_two_rides_gives_both() -> None:
    plan = Schedule.of([ride(0, "Morning"), ride(0, "Evening"), ride(1)])

    assert [entry.workout_name for entry in plan.today()] == ["Evening", "Morning"]


def test_the_next_ride_is_the_next_one_due() -> None:
    """A rider who missed Monday should be shown Wednesday, not Monday."""
    plan = Schedule.of([ride(-3), ride(-1), ride(2), ride(5)])

    upcoming = plan.next_ride()

    assert upcoming is not None
    assert upcoming.on == TODAY + timedelta(days=2)


def test_a_ride_knows_whether_it_has_been_and_gone() -> None:
    assert ride(-1).is_past
    assert not ride(0).is_past


def test_a_plan_survives_being_written_and_read() -> None:
    Schedule.of([ride(0, "Threshold"), ride(2, "Recovery")]).save()

    reloaded = Schedule.load()

    assert [entry.workout_name for entry in reloaded] == ["Threshold", "Recovery"]
    assert (paths.data_root() / "schedule.json").is_file()


def test_one_unreadable_day_does_not_lose_the_plan() -> None:
    import json

    paths.ensure_data_tree()
    (paths.data_root() / "schedule.json").write_text(
        json.dumps(
            [
                {"date": "not a date", "workout": "Broken"},
                {"date": TODAY.isoformat(), "workout": "Good"},
            ]
        ),
        encoding="utf-8",
    )

    plan = Schedule.load()

    assert [entry.workout_name for entry in plan] == ["Good"]


@pytest.mark.parametrize("content", ["not json", '{"not": "a list"}'])
def test_an_unusable_plan_file_reads_as_no_plan(content: str) -> None:
    paths.ensure_data_tree()
    (paths.data_root() / "schedule.json").write_text(content, encoding="utf-8")

    assert len(Schedule.load()) == 0


def test_an_entry_missing_its_date_is_refused() -> None:
    with pytest.raises(ScheduleError, match="unreadable entry"):
        ScheduledRide.from_dict({"workout": "Threshold"})


# Reading Garmin's calendar, whatever shape it arrives in.


@pytest.mark.parametrize("date_field", ["calendarDate", "date", "scheduleDate"])
def test_the_date_is_found_wherever_garmin_put_it(date_field: str) -> None:
    entry = scheduled_entry({date_field: "2026-09-09", "workoutName": "Threshold"})

    assert entry is not None
    assert entry.on == date(2026, 9, 9)


@pytest.mark.parametrize("holder", ["workout", "workoutDTO", "workoutSummary"])
def test_the_workout_is_found_wherever_it_is_nested(holder: str) -> None:
    entry = scheduled_entry(
        {
            "calendarDate": "2026-09-09",
            holder: {"workoutName": "Threshold", "workoutId": 7},
        }
    )

    assert entry is not None
    assert entry.workout_name == "Threshold"
    assert entry.source_id == "7"


def test_a_timestamp_is_read_as_the_day_it_falls_on() -> None:
    entry = scheduled_entry(
        {"calendarDate": "2026-09-09T00:00:00.000", "workoutName": "Threshold"}
    )

    assert entry is not None
    assert entry.on == date(2026, 9, 9)


@pytest.mark.parametrize(
    "raw",
    [
        {"workoutName": "No date"},
        {"calendarDate": "2026-09-09"},
        {"calendarDate": "the ninth", "workoutName": "Bad date"},
    ],
)
def test_an_entry_that_says_too_little_is_skipped_not_guessed(
    raw: dict[str, object],
) -> None:
    """A plan that half-loads is worse than one that says which days it could not
    read: the rider would ride the wrong thing and never know."""
    assert scheduled_entry(raw) is None


class FakeCalendar:
    def __init__(self, answer: object) -> None:
        self.answer = answer
        self.asked: list[tuple[str, str]] = []

    def get_scheduled_workouts(self, start: str, end: str) -> object:
        self.asked.append((start, end))
        return self.answer

    def get_workouts(self, start: int, end: int) -> list[dict[str, object]]:
        return []

    def get_workout_by_id(self, workout_id: str) -> dict[str, object]:
        return {}


def test_a_calendar_becomes_a_plan() -> None:
    client = FakeCalendar(
        [
            {"calendarDate": "2026-09-09", "workout": {"workoutName": "Threshold"}},
            {"calendarDate": "2026-09-11", "workout": {"workoutName": "Recovery"}},
        ]
    )

    plan, skipped = GarminWorkouts(client=client).schedule(
        date(2026, 9, 9), date(2026, 10, 7)
    )

    assert [entry.workout_name for entry in plan] == ["Threshold", "Recovery"]
    assert skipped == []
    assert client.asked == [("2026-09-09", "2026-10-07")]


def test_a_calendar_wrapped_in_an_object_is_read_too() -> None:
    """Garmin has returned both a bare list and one under `calendarItems`."""
    client = FakeCalendar(
        {"calendarItems": [{"date": "2026-09-09", "workoutName": "Threshold"}]}
    )

    plan, _ = GarminWorkouts(client=client).schedule(TODAY, TODAY)

    assert len(plan) == 1


def test_the_days_that_could_not_be_read_are_reported() -> None:
    client = FakeCalendar(
        [{"calendarDate": "2026-09-09", "workoutName": "Good"}, {"nothing": "useful"}]
    )

    plan, skipped = GarminWorkouts(client=client).schedule(TODAY, TODAY)

    assert len(plan) == 1
    assert len(skipped) == 1
    assert "nothing" in skipped[0]


def test_a_saved_plan_lands_in_the_one_data_tree(tmp_path: Path) -> None:
    path = Schedule.of([ride(0)]).save(tmp_path)

    assert path.parent == tmp_path
    assert Schedule.load(tmp_path).today()
