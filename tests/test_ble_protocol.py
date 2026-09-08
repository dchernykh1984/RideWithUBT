"""Payloads are built here field by field, the way the specification lays them
out, so a parser that drifts is caught by construction rather than by a rider
noticing their cadence looks wrong."""

from __future__ import annotations

import struct

import pytest

from app.sensors.ble_protocol import (
    CPS_WHEEL_TICKS_PER_SECOND,
    CRANK_TICKS_PER_SECOND,
    CSC_TICKS_PER_SECOND,
    PayloadError,
    parse_cycling_power,
    parse_heart_rate,
    parse_indoor_bike_data,
    parse_speed_cadence,
)


def test_an_eight_bit_heart_rate() -> None:
    assert parse_heart_rate(struct.pack("<BB", 0x00, 148)) == 148


def test_a_sixteen_bit_heart_rate() -> None:
    """Flag bit 0 widens the field; reading it as a byte would give 44."""
    assert parse_heart_rate(struct.pack("<BH", 0x01, 300)) == 300


def test_heart_rate_ignores_the_trailing_optional_fields() -> None:
    payload = struct.pack("<BBHHH", 0x18, 150, 500, 800, 810)

    assert parse_heart_rate(payload) == 150


def test_power_alone() -> None:
    measurement = parse_cycling_power(struct.pack("<Hh", 0x0000, 243))

    assert measurement.watts == 243
    assert measurement.wheel is None
    assert measurement.crank is None


def test_power_can_be_negative() -> None:
    """Instantaneous power is signed; a coasting meter may report below zero."""
    assert parse_cycling_power(struct.pack("<Hh", 0x0000, -5)).watts == -5


def test_power_with_wheel_and_crank_data() -> None:
    payload = struct.pack("<HhIHHH", 0x0030, 210, 123456, 40000, 900, 30000)

    measurement = parse_cycling_power(payload)

    assert measurement.watts == 210
    assert measurement.wheel is not None
    assert measurement.wheel.revolutions == 123456
    assert measurement.wheel.event_time == 40000
    # Cycling Power times its wheel events in 1/2048 s, unlike everything else.
    assert measurement.wheel.ticks_per_second == CPS_WHEEL_TICKS_PER_SECOND
    assert measurement.crank is not None
    assert measurement.crank.revolutions == 900
    assert measurement.crank.ticks_per_second == CRANK_TICKS_PER_SECOND


def test_power_steps_over_the_optional_fields_before_the_counters() -> None:
    """Balance and torque sit between power and the wheel data and shift it."""
    payload = struct.pack("<HhBHIH", 0x0015, 210, 50, 7000, 123456, 40000)

    measurement = parse_cycling_power(payload)

    assert measurement.watts == 210
    assert measurement.wheel is not None
    assert measurement.wheel.revolutions == 123456


def test_speed_and_cadence_wheel_only() -> None:
    payload = struct.pack("<BIH", 0x01, 98765, 12345)

    measurement = parse_speed_cadence(payload)

    assert measurement.wheel is not None
    assert measurement.wheel.revolutions == 98765
    assert measurement.wheel.ticks_per_second == CSC_TICKS_PER_SECOND
    assert measurement.crank is None


def test_speed_and_cadence_crank_only() -> None:
    payload = struct.pack("<BHH", 0x02, 1500, 22222)

    measurement = parse_speed_cadence(payload)

    assert measurement.wheel is None
    assert measurement.crank is not None
    assert measurement.crank.revolutions == 1500


def test_speed_and_cadence_both() -> None:
    payload = struct.pack("<BIHHH", 0x03, 98765, 12345, 1500, 22222)

    measurement = parse_speed_cadence(payload)

    assert measurement.wheel is not None
    assert measurement.crank is not None
    assert measurement.crank.event_time == 22222


def test_indoor_bike_data_speed_is_present_when_the_first_flag_is_clear() -> None:
    """Bit 0 means "more data", not "speed present". Inverting it shifts everything."""
    payload = struct.pack("<HH", 0x0000, 3000)  # 30.00 km/h

    data = parse_indoor_bike_data(payload)

    assert data.speed_ms == pytest.approx(30 / 3.6)


def test_indoor_bike_data_without_speed() -> None:
    payload = struct.pack("<Hh", 0x0041, 250)  # more-data set, power present

    data = parse_indoor_bike_data(payload)

    assert data.speed_ms is None
    assert data.power_w == 250


def test_indoor_bike_data_typical_trainer_notification() -> None:
    """Speed, cadence and power: what a smart trainer sends every second."""
    payload = struct.pack("<HHHh", 0x0044, 3210, 180, 247)

    data = parse_indoor_bike_data(payload)

    assert data.speed_ms == pytest.approx(32.10 / 3.6)
    assert data.cadence_rpm == pytest.approx(90.0)  # reported in halves of an rpm
    assert data.power_w == 247


def test_indoor_bike_data_full_house() -> None:
    payload = struct.pack(
        "<HHHHH3shhhHHBBBHH",
        0x1FFE,  # every optional field except "more data"
        2000,  # instantaneous speed
        1900,  # average speed
        180,  # instantaneous cadence
        176,  # average cadence
        (12345).to_bytes(3, "little"),  # total distance
        75,  # resistance level
        230,  # instantaneous power
        215,  # average power
        50,  # total energy
        30,  # energy per hour
        2,  # energy per minute
        152,  # heart rate
        8,  # metabolic equivalent
        600,  # elapsed time
        900,  # remaining time
    )

    data = parse_indoor_bike_data(payload)

    assert data.speed_ms == pytest.approx(20.0 / 3.6)
    assert data.cadence_rpm == pytest.approx(90.0)
    assert data.distance_m == 12345
    assert data.resistance_level == pytest.approx(7.5)
    assert data.power_w == 230
    assert data.heart_rate_bpm == 152


def test_a_truncated_payload_is_refused_rather_than_misread() -> None:
    """A short payload must not be padded into a plausible-looking reading."""
    with pytest.raises(PayloadError, match="too short"):
        parse_cycling_power(struct.pack("<HhI", 0x0010, 210, 123456))


def test_a_truncated_indoor_bike_payload_is_refused() -> None:
    with pytest.raises(PayloadError, match="too short"):
        parse_indoor_bike_data(struct.pack("<HH", 0x0040, 3000))
