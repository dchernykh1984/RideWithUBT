"""What this writer produces is decoded with `fitparse`, an independent
implementation, rather than with anything in this repository. A writer checked
against its own reader agrees with itself and with nothing else in the world -
and the whole point of writing FIT is that Garmin and Strava will read it."""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fitparse import FitFile

from app.storage.activity import EmptyRideError, RideSample, encode_activity
from app.storage.fit import FIT_EPOCH, crc16, semicircles, timestamp

START = datetime(2026, 9, 9, 6, 30, tzinfo=UTC)
# The start line of the Sokol circuit, which is where these rides happen.
SOKOL_LAT = 43.5814425
SOKOL_LON = 76.5651263


def ride(
    seconds: int = 60,
    power_w: float | None = 210.0,
    cadence_rpm: float | None = 88.0,
    heart_rate_bpm: float | None = 146.0,
    speed_ms: float = 9.3,
) -> list[RideSample]:
    return [
        RideSample(
            at=START + timedelta(seconds=second),
            distance_m=speed_ms * second,
            speed_ms=speed_ms,
            altitude_m=612.0,
            power_w=power_w,
            cadence_rpm=cadence_rpm,
            heart_rate_bpm=heart_rate_bpm,
            latitude=SOKOL_LAT,
            longitude=SOKOL_LON,
        )
        for second in range(seconds)
    ]


def decode(data: bytes) -> FitFile:
    """Parse with the independent reader, which also verifies the checksums."""
    fit = FitFile(io.BytesIO(data), check_crc=True)
    fit.parse()
    return fit


def messages(fit: FitFile, name: str) -> list[dict[str, Any]]:
    """Decoded messages. Typed loosely: what a FIT field holds is not known
    until the file says so."""
    return [message.get_values() for message in fit.get_messages(name)]


def degrees(semicircles_value: float) -> float:
    """FIT stores coordinates as semicircles, and so reports them back."""
    return semicircles_value * 180 / 2**31


def test_the_file_parses_and_its_checksums_hold() -> None:
    decode(encode_activity(ride()))


def test_it_says_it_is_an_activity_file() -> None:
    (file_id,) = messages(decode(encode_activity(ride())), "file_id")

    assert file_id["type"] == "activity"
    assert file_id["time_created"] == START.replace(tzinfo=None)


def test_a_ride_is_marked_as_a_virtual_one() -> None:
    """This is what stops an indoor ride showing up as a ride outdoors."""
    (session,) = messages(decode(encode_activity(ride())), "session")

    assert session["sport"] == "cycling"
    assert session["sub_sport"] == "virtual_activity"


def test_the_ride_is_written_where_it_happened() -> None:
    """A virtual lap of a real place should sit on the map of that place."""
    records = messages(decode(encode_activity(ride())), "record")

    assert records
    for record in records:
        assert degrees(record["position_lat"]) == pytest.approx(SOKOL_LAT, abs=1e-6)
        assert degrees(record["position_long"]) == pytest.approx(SOKOL_LON, abs=1e-6)


def test_a_world_that_is_not_anywhere_records_no_position() -> None:
    """Better a ride with no positions than one with made-up ones."""
    nowhere = [
        RideSample(at=sample.at, distance_m=sample.distance_m, speed_ms=sample.speed_ms)
        for sample in ride(seconds=5)
    ]

    records = messages(decode(encode_activity(nowhere)), "record")

    assert len(records) == 5
    for record in records:
        assert record.get("position_lat") is None
        assert record.get("position_long") is None


def test_a_ride_is_both_here_and_indoors() -> None:
    """The two facts are not in tension and both are written."""
    fit = decode(encode_activity(ride()))

    (session,) = messages(fit, "session")
    first = messages(fit, "record")[0]
    assert session["sub_sport"] == "virtual_activity"
    assert first["position_lat"] is not None


def test_every_second_of_the_ride_comes_back() -> None:
    records = messages(decode(encode_activity(ride(seconds=90))), "record")

    assert len(records) == 90
    assert records[0]["timestamp"] == START.replace(tzinfo=None)
    assert records[-1]["timestamp"] == (START + timedelta(seconds=89)).replace(
        tzinfo=None
    )


def test_the_values_survive_the_scaling_they_are_stored_at() -> None:
    records = messages(decode(encode_activity(ride(seconds=10))), "record")

    tenth = records[9]
    assert tenth["power"] == 210
    assert tenth["cadence"] == 88
    assert tenth["heart_rate"] == 146
    assert tenth["speed"] == pytest.approx(9.3, abs=0.01)
    assert tenth["distance"] == pytest.approx(9.3 * 9, abs=0.01)
    assert tenth["altitude"] == pytest.approx(612.0, abs=0.2)


def test_the_session_totals_are_what_was_ridden() -> None:
    (session,) = messages(decode(encode_activity(ride(seconds=61))), "session")

    assert session["total_elapsed_time"] == pytest.approx(60.0)
    assert session["total_distance"] == pytest.approx(9.3 * 60, abs=0.05)
    assert session["avg_power"] == 210
    assert session["max_power"] == 210
    assert session["avg_cadence"] == 88
    assert session["avg_heart_rate"] == 146
    assert session["avg_speed"] == pytest.approx(9.3, abs=0.01)


def test_a_ride_with_no_sensors_still_writes() -> None:
    """Coasting with nothing connected is a short, dull ride, not a crash."""
    samples = ride(seconds=30, power_w=None, cadence_rpm=None, heart_rate_bpm=None)

    records = messages(decode(encode_activity(samples)), "record")

    assert len(records) == 30
    assert records[0].get("power") is None
    assert records[0].get("heart_rate") is None
    assert records[0]["speed"] == pytest.approx(9.3, abs=0.01)


def test_a_lap_is_written_so_the_ride_has_one() -> None:
    (lap,) = messages(decode(encode_activity(ride(seconds=61))), "lap")

    assert lap["total_elapsed_time"] == pytest.approx(60.0)
    assert lap["total_distance"] == pytest.approx(9.3 * 60, abs=0.05)


def test_the_activity_message_closes_the_file() -> None:
    (activity,) = messages(decode(encode_activity(ride(seconds=61))), "activity")

    assert activity["num_sessions"] == 1
    assert activity["total_timer_time"] == pytest.approx(60.0)


def test_a_ride_with_nothing_in_it_is_refused() -> None:
    with pytest.raises(EmptyRideError, match="no samples"):
        encode_activity([])


def test_a_corrupted_file_is_caught_by_its_checksum() -> None:
    """Proof the checksum is real and not decoration."""
    data = bytearray(encode_activity(ride()))
    data[40] ^= 0xFF

    with pytest.raises(Exception, match=r"(?i)crc"):
        decode(bytes(data))


# The pieces underneath.


def test_the_epoch_is_the_one_fit_counts_from() -> None:
    assert timestamp(FIT_EPOCH) == 0
    assert timestamp(datetime(1990, 1, 1, tzinfo=UTC)) == 86400


def test_a_time_without_a_timezone_is_not_a_time() -> None:
    with pytest.raises(ValueError, match="without a timezone"):
        timestamp(datetime(2026, 9, 9, 6, 30))


def test_semicircles_cover_the_circle() -> None:
    assert semicircles(180.0) == 2**31
    assert semicircles(0.0) == 0
    assert semicircles(-90.0) == -(2**30)


def test_the_checksum_notices_a_changed_byte() -> None:
    assert crc16(b"") == 0
    assert crc16(b"RideWithUBT") != crc16(b"RideWithUBU")
