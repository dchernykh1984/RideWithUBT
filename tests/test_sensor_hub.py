from __future__ import annotations

import pytest

from app.sensors.hub import SensorHub
from app.sensors.types import Metric, Reading
from app.trainer import catalog
from app.trainer.estimate import PowerEstimator
from app.trainer.wheels import Wheel


def reading(
    metric: Metric,
    value: float,
    at: float,
    source: str = "meter",
    estimated: bool = False,
) -> Reading:
    return Reading(
        metric=metric, value=value, at=at, source=source, estimated=estimated
    )


def test_an_empty_hub_knows_nothing() -> None:
    snapshot = SensorHub().snapshot(now=10.0)

    assert snapshot.power is None
    assert snapshot.cadence is None
    assert snapshot.speed is None
    assert snapshot.heart_rate is None
    assert not snapshot.has_power


def test_a_reading_shows_up_with_its_source_and_age() -> None:
    hub = SensorHub()
    hub.submit(reading(Metric.POWER, 210.0, at=9.0, source="left-crank"))

    power = hub.snapshot(now=10.0).power

    assert power is not None
    assert power.value == 210.0
    assert power.source == "left-crank"
    assert power.age_s == pytest.approx(1.0)
    assert not power.estimated


def test_the_newest_reading_from_a_device_replaces_the_last() -> None:
    hub = SensorHub()
    hub.submit(reading(Metric.CADENCE, 80.0, at=9.0))
    hub.submit(reading(Metric.CADENCE, 92.0, at=10.0))

    cadence = hub.snapshot(now=10.0).cadence

    assert cadence is not None
    assert cadence.value == 92.0


def test_a_device_that_goes_quiet_stops_being_believed() -> None:
    """Silence means the device dropped out, not that the value is holding."""
    hub = SensorHub(stale_after_s=4.0)
    hub.submit(reading(Metric.HEART_RATE, 150.0, at=10.0))

    assert hub.snapshot(now=13.9).heart_rate is not None
    assert hub.snapshot(now=14.1).heart_rate is None


def test_between_two_devices_the_newest_wins() -> None:
    hub = SensorHub()
    hub.submit(reading(Metric.HEART_RATE, 140.0, at=9.0, source="strap"))
    hub.submit(reading(Metric.HEART_RATE, 146.0, at=9.5, source="watch"))

    heart_rate = hub.snapshot(now=10.0).heart_rate

    assert heart_rate is not None
    assert heart_rate.source == "watch"


def test_a_measurement_beats_an_estimate_even_when_older() -> None:
    hub = SensorHub()
    hub.submit(reading(Metric.POWER, 200.0, at=9.0, source="meter"))
    hub.submit(reading(Metric.POWER, 260.0, at=9.9, source="guess", estimated=True))

    power = hub.snapshot(now=10.0).power

    assert power is not None
    assert power.source == "meter"
    assert not power.estimated


def test_a_pinned_device_wins_over_both() -> None:
    """A rider with two straps gets to say which one is theirs."""
    hub = SensorHub()
    hub.prefer(Metric.HEART_RATE, "strap")
    hub.submit(reading(Metric.HEART_RATE, 140.0, at=9.0, source="strap"))
    hub.submit(reading(Metric.HEART_RATE, 199.0, at=9.9, source="someone-else"))

    heart_rate = hub.snapshot(now=10.0).heart_rate

    assert heart_rate is not None
    assert heart_rate.source == "strap"


def test_a_pinned_device_that_goes_quiet_falls_back_to_the_others() -> None:
    hub = SensorHub(stale_after_s=4.0)
    hub.prefer(Metric.HEART_RATE, "strap")
    hub.submit(reading(Metric.HEART_RATE, 140.0, at=1.0, source="strap"))
    hub.submit(reading(Metric.HEART_RATE, 145.0, at=9.5, source="watch"))

    heart_rate = hub.snapshot(now=10.0).heart_rate

    assert heart_rate is not None
    assert heart_rate.source == "watch"


def test_forgetting_a_device_removes_all_of_its_metrics() -> None:
    hub = SensorHub()
    hub.submit(reading(Metric.POWER, 200.0, at=10.0, source="trainer"))
    hub.submit(reading(Metric.SPEED, 8.0, at=10.0, source="trainer"))
    hub.submit(reading(Metric.HEART_RATE, 150.0, at=10.0, source="strap"))

    hub.forget("trainer")

    snapshot = hub.snapshot(now=10.0)
    assert snapshot.power is None
    assert snapshot.speed is None
    assert snapshot.heart_rate is not None


def test_sources_lists_what_is_offering_a_metric() -> None:
    hub = SensorHub()
    hub.submit(reading(Metric.POWER, 200.0, at=10.0, source="trainer"))
    hub.submit(reading(Metric.POWER, 205.0, at=10.0, source="pedals"))

    assert hub.sources(Metric.POWER) == ["pedals", "trainer"]
    assert hub.sources(Metric.CADENCE) == []


def estimator() -> PowerEstimator:
    return PowerEstimator(
        wheel=Wheel(size_id="700c", width_id="25"),
        trainer=catalog.catalogue().get("generic-fluid"),
    )


def test_wheel_speed_fills_in_power_when_nothing_measures_it() -> None:
    hub = SensorHub(estimator=estimator())
    hub.submit(reading(Metric.SPEED, 30 / 3.6, at=10.0, source="speed-sensor"))

    power = hub.snapshot(now=10.0).power

    assert power is not None
    assert 150 < power.value < 250
    assert power.estimated
    assert power.source == "generic-fluid"


def test_a_real_power_meter_is_never_overridden_by_the_estimate() -> None:
    hub = SensorHub(estimator=estimator())
    hub.submit(reading(Metric.SPEED, 30 / 3.6, at=10.0, source="speed-sensor"))
    hub.submit(reading(Metric.POWER, 173.0, at=10.0, source="pedals"))

    power = hub.snapshot(now=10.0).power

    assert power is not None
    assert power.value == 173.0
    assert not power.estimated


def test_no_estimator_means_no_invented_power() -> None:
    hub = SensorHub()
    hub.submit(reading(Metric.SPEED, 8.0, at=10.0))

    assert hub.snapshot(now=10.0).power is None


def test_a_smart_trainer_is_not_estimated_from_its_own_wheel_speed() -> None:
    hub = SensorHub(
        estimator=PowerEstimator(
            wheel=Wheel(size_id="700c", width_id="25"),
            trainer=catalog.catalogue().get("generic-smart-ftms"),
        )
    )
    hub.submit(reading(Metric.SPEED, 8.0, at=10.0))

    assert hub.snapshot(now=10.0).power is None


def test_a_snapshot_can_be_read_by_metric() -> None:
    hub = SensorHub()
    hub.submit(reading(Metric.SPEED, 8.0, at=10.0))

    snapshot = hub.snapshot(now=10.0)

    assert snapshot.get(Metric.SPEED) is snapshot.speed
    assert snapshot.get(Metric.POWER) is None
