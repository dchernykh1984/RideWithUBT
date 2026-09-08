from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fitparse import FitFile

from app import paths
from app.core.recorder import RideRecorder
from app.core.session import RideSession, RideState
from app.sensors.hub import SensorHub
from app.sensors.types import Metric, Reading
from app.storage import activities
from app.storage.activity import EmptyRideError
from app.world.navigation import Navigator
from app.world.network import Point
from tests.worlds import loop_network

START = datetime(2026, 9, 9, 6, 30, tzinfo=UTC)


def state(elapsed_s: float, distance_m: float = 0.0, **overrides: float) -> RideState:
    fields: dict[str, object] = {
        "elapsed_s": elapsed_s,
        "distance_m": distance_m,
        "speed_ms": 9.0,
        "gradient": 0.0,
        "point": Point(0.0, 0.0, 610.0),
        "heading_rad": 0.0,
        "power_w": 200.0,
        "power_estimated": False,
        "cadence_rpm": 90.0,
        "heart_rate_bpm": 145.0,
    }
    fields.update(overrides)
    return RideState(**fields)  # type: ignore[arg-type]


# Sampling.


def test_a_new_recording_has_nothing_in_it() -> None:
    assert RideRecorder(START).is_empty


def test_it_samples_once_a_second_however_often_it_is_asked() -> None:
    """A renderer calls this sixty times a second; a FIT file wants one."""
    recorder = RideRecorder(START)

    for frame in range(300):  # five seconds at sixty frames a second
        recorder.observe(state(elapsed_s=frame / 60))

    assert len(recorder.samples) == 5


def test_sampling_follows_ride_time_not_wall_time() -> None:
    """A slow frame must not leave a gap in the recording."""
    recorder = RideRecorder(START)

    recorder.observe(state(elapsed_s=0.0))
    recorder.observe(state(elapsed_s=4.5))

    assert [sample.at for sample in recorder.samples] == [
        START,
        START + timedelta(seconds=4.5),
    ]


def test_a_sample_carries_what_the_ride_was_doing() -> None:
    recorder = RideRecorder(START)

    recorder.observe(state(elapsed_s=0.0, distance_m=125.0))

    (sample,) = recorder.samples
    assert sample.distance_m == 125.0
    assert sample.speed_ms == 9.0
    assert sample.power_w == 200.0
    assert sample.cadence_rpm == 90.0
    assert sample.heart_rate_bpm == 145.0
    assert sample.altitude_m == 610.0


def test_the_interval_is_adjustable() -> None:
    recorder = RideRecorder(START, interval_s=5.0)

    for second in range(20):
        recorder.observe(state(elapsed_s=float(second)))

    assert len(recorder.samples) == 4


# Writing it out.


def test_a_recording_becomes_a_file_that_reads_back() -> None:
    recorder = RideRecorder(START)
    for second in range(30):
        recorder.observe(state(elapsed_s=float(second), distance_m=9.0 * second))

    fit = FitFile(io.BytesIO(recorder.to_fit()), check_crc=True)
    fit.parse()

    records = list(fit.get_messages("record"))
    assert len(records) == 30
    assert records[0].get_value("power") == 200


def test_a_ride_nobody_rode_is_not_written() -> None:
    with pytest.raises(EmptyRideError):
        RideRecorder(START).to_fit()


def test_saving_puts_the_ride_in_the_one_store() -> None:
    recorder = RideRecorder(START)
    for second in range(10):
        recorder.observe(state(elapsed_s=float(second)))

    path = recorder.save()

    assert path.parent == paths.activities_dir()
    assert path.name == "20260909T063000.fit"
    assert activities.rides() == [path]


def test_a_whole_ride_from_sensors_to_file(tmp_path: Path) -> None:
    """The path a real ride takes: watts in, a readable file out."""
    hub = SensorHub()
    session = RideSession(Navigator(loop_network(), start_segment="north"), hub=hub)
    recorder = RideRecorder(START)

    now = 0.0
    for _ in range(120):  # a minute at half-second steps
        now += 0.5
        hub.submit(Reading(Metric.POWER, 230.0, at=now, source="meter"))
        recorder.observe(session.update(0.5, now=now))

    path = recorder.save(tmp_path)
    fit = FitFile(str(path), check_crc=True)
    fit.parse()

    (session_message,) = list(fit.get_messages("session"))
    assert session_message.get_value("sub_sport") == "virtual_activity"
    assert session_message.get_value("total_distance") > 200
    assert session_message.get_value("avg_power") == 230


# The store itself.


def test_rides_are_named_after_when_they_started() -> None:
    assert activities.file_name(START) == "20260909T063000.fit"


def test_two_rides_starting_in_the_same_second_do_not_collide(
    tmp_path: Path,
) -> None:
    first = activities.save(b"one", START, tmp_path)
    second = activities.save(b"two", START, tmp_path)

    assert first != second
    assert first.read_bytes() == b"one", "the first ride is not overwritten"
    assert second.read_bytes() == b"two"


def test_the_store_lists_rides_oldest_first(tmp_path: Path) -> None:
    later = activities.save(b"b", START + timedelta(hours=2), tmp_path)
    earlier = activities.save(b"a", START, tmp_path)

    assert activities.rides(tmp_path) == [earlier, later]


def test_an_empty_store_lists_nothing() -> None:
    assert activities.rides() == []


def test_the_store_creates_itself_on_first_use() -> None:
    assert not paths.activities_dir().exists()

    activities.save(b"ride", START)

    assert paths.activities_dir().is_dir()
