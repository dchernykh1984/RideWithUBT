"""Measuring a trainer from live readings.

The failure this guards against is not a crash: it is a plausible-looking curve
fitted from the wrong numbers, which would then be contributed and used by
somebody else."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.sensors.types import MetricValue, RideSnapshot
from app.trainer import catalog
from app.trainer.capture import MIN_SAMPLE_GAP_S, TrainerCapture
from app.trainer.power import MIN_FIT_SAMPLES, PowerCurve
from app.trainer.wheels import Wheel

TRUTH = PowerCurve(coefficient=0.35, exponent=3.0)
WHEEL = Wheel(size_id="700c", width_id="25")


def capture(**overrides: object) -> TrainerCapture:
    fields: dict[str, object] = {
        "trainer": catalog.catalogue().get("generic-fluid"),
        "wheel": WHEEL,
        "resistance_setting": "level 3",
        "tyre_pressure_bar": 6.5,
    }
    fields.update(overrides)
    return TrainerCapture(**fields)  # type: ignore[arg-type]


def snapshot(
    at: float,
    speed_ms: float | None = 8.0,
    power_w: float | None = None,
    speed_estimated: bool = False,
    power_estimated: bool = False,
) -> RideSnapshot:
    watts = TRUTH.power_w(speed_ms) if power_w is None and speed_ms else power_w
    return RideSnapshot(
        at=at,
        speed=None
        if speed_ms is None
        else MetricValue(speed_ms, "sensor", 0.0, speed_estimated),
        power=None
        if watts is None
        else MetricValue(watts, "meter", 0.0, power_estimated),
    )


def sweep(recording: TrainerCapture, count: int = 40, noise_w: float = 0.0) -> None:
    """Ride from a slow warm-up to a hard effort, a sample a second."""
    for step in range(count):
        speed = 3.0 + 0.25 * step
        offset = noise_w if step % 2 else -noise_w
        recording.observe(
            snapshot(
                at=float(step), speed_ms=speed, power_w=TRUTH.power_w(speed) + offset
            )
        )


def test_a_new_capture_has_measured_nothing() -> None:
    recording = capture()

    report = recording.report()
    assert recording.samples == 0
    assert not report.publishable
    assert report.progress == 0.0


def test_riding_the_range_produces_a_publishable_curve() -> None:
    recording = capture()

    sweep(recording)

    report = recording.report()
    assert report.samples == 40
    assert report.publishable
    assert report.rms_error_w is not None and report.rms_error_w < 1.0
    assert report.speed_range_kmh is not None
    assert report.progress == 1.0


def test_the_wheel_speed_is_what_is_fitted_not_the_ride_speed() -> None:
    """The screen's speed is the course's; the trainer only knows its own roller.

    Fitting the ride's speed would describe the virtual world, and would look
    entirely plausible.
    """
    recording = capture()
    sweep(recording)

    fit = recording.recorder.fit()

    assert fit.curve.exponent == pytest.approx(TRUTH.exponent, abs=0.01)
    assert fit.curve.coefficient == pytest.approx(TRUTH.coefficient, rel=0.01)


def test_an_estimated_power_is_never_fitted() -> None:
    """It came from a trainer curve, so fitting it rediscovers that curve."""
    recording = capture()

    taken = recording.observe(snapshot(at=1.0, power_estimated=True))

    assert not taken
    assert recording.samples == 0


def test_an_estimated_speed_is_never_fitted() -> None:
    recording = capture()

    assert not recording.observe(snapshot(at=1.0, speed_estimated=True))


@pytest.mark.parametrize(
    ("has_speed", "has_power"), [(False, True), (True, False), (False, False)]
)
def test_a_reading_that_is_missing_half_of_what_is_needed(
    has_speed: bool, has_power: bool
) -> None:
    """Both halves are needed, so a sensor that dropped out contributes nothing."""
    recording = capture()
    incomplete = RideSnapshot(
        at=1.0,
        speed=MetricValue(8.0, "sensor", 0.0, False) if has_speed else None,
        power=MetricValue(200.0, "meter", 0.0, False) if has_power else None,
    )

    assert not recording.observe(incomplete)


def test_samples_are_not_taken_faster_than_a_trainer_changes() -> None:
    """A thousand near-identical points make a fit look better than it is."""
    recording = capture()

    recording.observe(snapshot(at=1.0))
    too_soon = recording.observe(snapshot(at=1.0 + MIN_SAMPLE_GAP_S / 2))
    later = recording.observe(snapshot(at=1.0 + MIN_SAMPLE_GAP_S))

    assert not too_soon
    assert later
    assert recording.samples == 2


def test_a_short_recording_says_what_is_missing() -> None:
    recording = capture()
    sweep(recording, count=MIN_FIT_SAMPLES - 2)

    report = recording.report()

    assert not report.publishable
    assert "usable samples" in report.reason
    assert 0.0 < report.progress < 1.0


def test_a_recording_that_wandered_is_not_offered() -> None:
    """Somebody who moved the resistance lever measured two trainers."""
    recording = capture()
    sweep(recording, noise_w=80.0)

    report = recording.report()

    assert not report.publishable
    assert "ride it again" in report.reason


def test_what_is_written_is_a_catalogue_file_that_loads_back(tmp_path: Path) -> None:
    recording = capture()
    sweep(recording)

    path = recording.write_contribution(tmp_path / "contributions", contributor="rider")

    assert path.name == "generic-fluid.json"
    reloaded = catalog.load_catalogue(path.parent).get("generic-fluid")
    assert reloaded.is_calibrated
    assert reloaded.profile is not None
    assert reloaded.profile.resistance_setting == "level 3"
    assert reloaded.profile.tyre_pressure_bar == 6.5
    assert reloaded.profile.contributor == "rider"
    assert json.loads(path.read_text(encoding="utf-8"))["id"] == "generic-fluid"
