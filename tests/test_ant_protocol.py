"""Broadcasts are built here byte by byte, the way each ANT+ device profile lays
them out, so a parser that drifts is caught by construction."""

from __future__ import annotations

import pytest

from app.sensors import ant_protocol as pages


def page(*values: int) -> bytes:
    assert len(values) == 8
    return bytes(values)


def uint16(value: int) -> tuple[int, int]:
    return value & 0xFF, (value >> 8) & 0xFF


def test_a_broadcast_must_be_eight_bytes() -> None:
    """Anything else is a framing bug, and padding it would invent a reading."""
    with pytest.raises(pages.PayloadError, match="8 bytes"):
        pages.parse_heart_rate(b"\x00\x01\x02")


def test_heart_rate_is_the_last_byte_of_every_page() -> None:
    data = pages.parse_heart_rate(page(0, 0, 0, 0, 0, 0, 12, 148))

    assert data.beats_per_minute == 148


def test_a_strap_that_has_not_found_a_pulse_reports_nothing() -> None:
    assert pages.parse_heart_rate(page(0, 0, 0, 0, 0, 0, 0, 0)).beats_per_minute is None


def test_the_standard_power_page() -> None:
    payload = page(0x10, 5, 50, 88, *uint16(1200), *uint16(243))

    measurement = pages.parse_power(payload)

    assert measurement is not None
    assert measurement.watts == 243
    assert measurement.cadence_rpm == 88


def test_a_power_meter_with_no_cadence_says_so() -> None:
    payload = page(0x10, 5, 50, 0xFF, *uint16(1200), *uint16(243))

    measurement = pages.parse_power(payload)

    assert measurement is not None
    assert measurement.cadence_rpm is None


def test_other_power_pages_are_skipped_rather_than_misread() -> None:
    """Torque and calibration pages share the channel and mean something else."""
    assert pages.parse_power(page(0x11, 5, 50, 88, 0, 0, 0, 0)) is None


def test_the_combined_speed_and_cadence_page_carries_both_counters() -> None:
    payload = page(*uint16(1024), *uint16(300), *uint16(2048), *uint16(900))

    data = pages.parse_speed_cadence(payload)

    assert data.crank is not None
    assert data.crank.event_time == 1024
    assert data.crank.revolutions == 300
    assert data.wheel is not None
    assert data.wheel.event_time == 2048
    assert data.wheel.revolutions == 900


def test_a_speed_only_sensor_puts_its_counter_last() -> None:
    data = pages.parse_speed(page(0, 0, 0, 0, *uint16(4096), *uint16(1500)))

    assert data.wheel is not None
    assert data.wheel.revolutions == 1500
    assert data.crank is None


def test_a_cadence_only_sensor_is_laid_out_the_same_way() -> None:
    data = pages.parse_cadence(page(0, 0, 0, 0, *uint16(4096), *uint16(700)))

    assert data.crank is not None
    assert data.crank.revolutions == 700
    assert data.wheel is None


def test_the_general_fitness_equipment_page() -> None:
    payload = page(0x10, 25, 40, 200, *uint16(8000), 150, 0x30)

    data = pages.parse_fitness_equipment(payload)

    assert data is not None
    assert data.speed_ms == pytest.approx(8.0)  # reported in 1/1000 m/s
    assert data.heart_rate_bpm == 150
    assert data.distance_m == 200
    assert data.elapsed_s == pytest.approx(10.0)  # counted in quarter-seconds


def test_a_trainer_with_no_strap_paired_reports_no_heart_rate() -> None:
    payload = page(0x10, 25, 40, 200, *uint16(8000), 0xFF, 0x30)

    data = pages.parse_fitness_equipment(payload)

    assert data is not None
    assert data.heart_rate_bpm is None


def test_an_unknown_speed_is_not_reported_as_a_huge_one() -> None:
    payload = page(0x10, 25, 40, 200, 0xFF, 0xFF, 150, 0x30)

    data = pages.parse_fitness_equipment(payload)

    assert data is not None
    assert data.speed_ms is None


def test_the_specific_trainer_page_reads_power_across_a_nibble_boundary() -> None:
    """Instantaneous power is twelve bits: a byte plus the low nibble of the next."""
    # 300 W = 0x12C: low byte 0x2C, high nibble 0x1, with status 0x3 above it.
    payload = page(0x19, 7, 92, *uint16(5000), 0x2C, 0x31, 0x00)

    data = pages.parse_fitness_equipment(payload)

    assert data is not None
    assert data.power_w == 300
    assert data.cadence_rpm == 92


def test_a_trainer_that_cannot_measure_power_says_so() -> None:
    payload = page(0x19, 7, 92, *uint16(5000), 0xFF, 0x3F, 0x00)

    data = pages.parse_fitness_equipment(payload)

    assert data is not None
    assert data.power_w is None


def test_other_fitness_equipment_pages_are_skipped() -> None:
    assert pages.parse_fitness_equipment(page(0x1A, 0, 0, 0, 0, 0, 0, 0)) is None
