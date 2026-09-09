from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.services.credentials import Credential, CredentialsError, secret
from app.services.garmin import GarminWorkouts, WorkoutSummary
from app.workout import library
from tests.test_garmin_format import step, workout


class FakeGarmin:
    """The two calls this needs, and a record of how they were made."""

    def __init__(
        self,
        workouts: dict[str, dict[str, Any]],
        scheduled: list[dict[str, Any]] | None = None,
    ) -> None:
        self.workouts = workouts
        self.scheduled = scheduled or []
        self.listed: list[tuple[int, int]] = []

    def get_scheduled_workouts(self, start: str, end: str) -> list[dict[str, Any]]:
        return self.scheduled

    def get_workouts(self, start: int, end: int) -> list[dict[str, Any]]:
        self.listed.append((start, end))
        return [
            {"workoutId": key, "workoutName": raw["workoutName"]}
            for key, raw in self.workouts.items()
        ]

    def get_workout_by_id(self, workout_id: str) -> dict[str, Any]:
        return self.workouts[workout_id]


def account(**workouts: dict[str, Any]) -> GarminWorkouts:
    return GarminWorkouts(client=FakeGarmin(dict(workouts)))


def test_listing_asks_for_the_number_wanted() -> None:
    service = account(a=workout(step(), name="Threshold"))

    listed = service.summaries(limit=7)

    assert listed == [WorkoutSummary(id="a", name="Threshold")]
    assert service.client.listed == [(0, 7)]  # type: ignore[attr-defined]


def test_a_workout_without_an_id_is_skipped() -> None:
    """It could not be fetched, so offering it would only fail later."""
    service = GarminWorkouts(client=FakeGarmin({}))
    service.client.get_workouts = lambda start, end: [  # type: ignore[method-assign]
        {"workoutName": "Nameless"}
    ]

    assert service.summaries() == []


def test_fetching_gives_something_rideable() -> None:
    service = account(a=workout(step(seconds=600.0), name="Threshold"))

    fetched = service.fetch("a")

    assert fetched.name == "Threshold"
    assert fetched.source == "garmin:a"
    assert fetched.total_time_s == 600.0


def test_one_unreadable_workout_does_not_stop_the_import() -> None:
    """A running workout with a step we do not know must not lose the others."""
    service = account(
        good=workout(step(), name="Good"),
        bad=workout(step(kind="swim.drill"), name="Bad"),
    )

    results = list(service.download(service.summaries()))

    readable = [(summary.name, problem) for summary, got, problem in results if got]
    skipped = [(summary.name, problem) for summary, got, problem in results if not got]
    assert readable == [("Good", "")]
    assert skipped[0][0] == "Bad"
    assert "unknown Garmin step type" in skipped[0][1]


def test_an_imported_workout_lands_in_the_library(tmp_path: Path) -> None:
    """Whatever it came from, it is stored in the one format the library reads."""
    service = account(a=workout(step(seconds=600.0), name="3x8 Threshold"))
    _, fetched, _ = next(iter(service.download(service.summaries())))
    assert fetched is not None

    path = library.save(fetched, tmp_path)

    assert path.name == "3x8-threshold.json"
    assert library.load_library(tmp_path).named("3x8 Threshold").total_time_s == 600.0


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("3x8 Cycling Intervals", "3x8-cycling-intervals.json"),
        ("Sweet/Spot: 2 x 20", "sweet-spot-2-x-20.json"),
        ("   ", "workout.json"),
    ],
)
def test_a_name_becomes_a_file_name_that_works_everywhere(
    name: str, expected: str
) -> None:
    from app.workout.model import Step, StepKind, Workout

    made = Workout(name=name, steps=(Step(kind=StepKind.INTERVAL, duration=60),))

    assert library.file_name_for(made) == expected


# Credentials.


def test_the_environment_can_supply_a_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    credential = Credential(service="garmin", username="rider@example.com")
    monkeypatch.setenv(credential.env_var, "hunter2")

    assert secret(credential) == "hunter2"


def test_a_missing_credential_says_how_to_supply_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential = Credential(service="garmin", username="rider@example.com")
    monkeypatch.delenv(credential.env_var, raising=False)
    monkeypatch.setattr(
        "app.services.credentials._keyring",
        lambda: type("Empty", (), {"get_password": staticmethod(lambda *_: None)}),
    )

    with pytest.raises(CredentialsError, match="RIDEWITHUBT_GARMIN_SECRET"):
        secret(credential)


def test_a_credential_is_namespaced_to_this_app() -> None:
    """So it cannot be confused with another program's entry for the same service."""
    credential = Credential(service="strava", username="rider@example.com")

    assert credential.keyring_service == "RideWithUBT:strava"
    assert credential.env_var == "RIDEWITHUBT_STRAVA_SECRET"
