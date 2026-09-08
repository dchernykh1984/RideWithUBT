from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.trainer import catalog
from app.trainer.estimate import PowerEstimator
from app.trainer.power import NotEnoughDataError, PowerCurve
from app.trainer.recording import ProfileRecorder, describe_wheel
from app.trainer.wheels import Wheel

WHEEL = Wheel(size_id="700c", width_id="25")
TRUTH = PowerCurve(coefficient=0.35, exponent=3.0)


def recorder(**overrides: object) -> ProfileRecorder:
    fields: dict[str, object] = {
        "trainer": catalog.catalogue().get("generic-fluid"),
        "wheel": WHEEL,
        "resistance_setting": "level 3",
        "tyre_pressure_bar": 6.5,
    }
    fields.update(overrides)
    return ProfileRecorder(**fields)  # type: ignore[arg-type]


def ride(recording: ProfileRecorder, noise_w: float = 0.0, count: int = 40) -> None:
    """Feed a sweep from a slow warm-up to a hard effort."""
    for step in range(count):
        speed = 3.0 + 0.25 * step
        offset = noise_w if step % 2 else -noise_w
        recording.add(speed, TRUTH.power_w(speed) + offset)


# The forward direction: wheel and trainer give watts.


def test_an_uncalibrated_trainer_says_so_with_its_watts() -> None:
    estimator = PowerEstimator(WHEEL, catalog.catalogue().get("generic-fluid"))

    estimate = estimator.from_speed(30 / 3.6)

    assert estimate is not None
    assert 150 < estimate.watts < 250
    assert not estimate.calibrated


def test_a_smart_trainer_declines_to_be_estimated() -> None:
    estimator = PowerEstimator(WHEEL, catalog.catalogue().get("generic-smart-ftms"))

    assert not estimator.available
    assert estimator.from_speed(8.0) is None


def test_revolutions_become_watts_through_the_rollout() -> None:
    estimator = PowerEstimator(Wheel(measured_rollout_mm=2000.0), _fluid())

    by_revolutions = estimator.from_wheel_revolutions(4.0)
    by_speed = estimator.from_speed(8.0)

    assert by_revolutions == by_speed


def _fluid() -> catalog.Trainer:
    return catalog.catalogue().get("generic-fluid")


# The reverse direction: watts and speed give a curve.


def test_a_clean_recording_recovers_the_trainer_curve() -> None:
    recording = recorder()
    ride(recording)

    fit = recording.fit()

    assert fit.curve.exponent == pytest.approx(3.0, abs=0.01)
    assert recording.can_publish()


def test_a_short_recording_cannot_be_published_yet() -> None:
    recording = recorder()
    ride(recording, count=5)

    assert not recording.can_publish()
    with pytest.raises(NotEnoughDataError):
        recording.fit()


def test_a_recording_that_wandered_is_not_offered_for_contribution() -> None:
    """Someone who moved the resistance lever mid-ride measured two trainers."""
    recording = recorder()
    ride(recording, noise_w=80.0)

    assert not recording.can_publish()


def test_the_profile_carries_what_makes_it_reusable() -> None:
    recording = recorder()
    ride(recording)

    profile = recording.build(
        contributor="rider", recorded_at=datetime(2026, 9, 8, tzinfo=UTC)
    )

    assert profile.resistance_setting == "level 3"
    assert profile.tyre_pressure_bar == 6.5
    assert profile.wheel.startswith("700c x 25")
    assert profile.recorded_at == "2026-09-08"
    assert profile.contributor == "rider"
    assert profile.samples == 40


def test_the_recording_becomes_a_catalogue_file_that_loads_back(tmp_path: Path) -> None:
    """The contribution path end to end: record, write the file, read it as data."""
    recording = recorder()
    ride(recording)

    entry = recording.as_catalogue_entry(contributor="rider")
    path = tmp_path / f"{entry['id']}.json"
    path.write_text(json.dumps(entry, indent=2), encoding="utf-8")

    reloaded = catalog.load_catalogue(tmp_path).get("generic-fluid")
    assert reloaded.is_calibrated
    assert reloaded.profile is not None
    assert reloaded.profile.curve.exponent == pytest.approx(3.0, abs=0.01)
    assert reloaded.power_curve() is not None
    assert (
        reloaded.power_curve() != catalog.catalogue().get("generic-fluid").power_curve()
    )


def test_a_measured_wheel_is_described_by_its_rollout() -> None:
    assert describe_wheel(Wheel(measured_rollout_mm=2088.0)) == (
        "measured rollout 2088 mm"
    )
