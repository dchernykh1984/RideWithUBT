"""Parsing ANT+ device profile pages.

An ANT+ broadcast is always exactly eight bytes. The first byte usually names the
page, and the rest means whatever that page says it means - so the same eight
bytes are a power reading from one device type and a speed reading from another.
Nothing in the payload identifies the sensor; the channel it arrived on does.

As with Bluetooth, the parsing is pure functions over bytes so the whole path can
be tested without a stick, and `ant.py` only moves bytes from the radio to here.

Profiles covered:

* Heart Rate (device type 120)
* Bicycle Power (11), standard power-only page
* Bicycle Speed and Cadence (121), and the speed-only (123) and cadence-only
  (122) sensors
* Fitness Equipment / FE-C (17), general and specific trainer pages
"""

from __future__ import annotations

from dataclasses import dataclass

PAYLOAD_BYTES = 8

# ANT+ device types, as advertised on the channel id.
DEVICE_HEART_RATE = 120
DEVICE_POWER = 11
DEVICE_SPEED_CADENCE = 121
DEVICE_CADENCE = 122
DEVICE_SPEED = 123
DEVICE_FITNESS_EQUIPMENT = 17

# Page numbers that carry what we want.
PAGE_STANDARD_POWER = 0x10
PAGE_GENERAL_FE = 0x10
PAGE_SPECIFIC_TRAINER = 0x19

# Every ANT+ event timestamp is in 1/1024 of a second, in a 16-bit field.
TICKS_PER_SECOND = 1024
# Speed on the general FE page is in 1/1000 of a metre per second.
FE_SPEED_UNIT_MS = 0.001
# Elapsed time on the general FE page counts quarter-seconds.
FE_TIME_UNIT_S = 0.25

# An invalid heart rate, cadence or speed is sent as an all-ones field.
INVALID_BYTE = 0xFF
INVALID_UINT16 = 0xFFFF
# Instantaneous power on the trainer page is twelve bits wide.
POWER_INVALID = 0x0FFF


class PayloadError(ValueError):
    """A broadcast that is not eight bytes."""


@dataclass(frozen=True)
class Counter:
    """A cumulative revolution counter and the time of its last event."""

    revolutions: int
    event_time: int
    ticks_per_second: int = TICKS_PER_SECOND


@dataclass(frozen=True)
class HeartRateData:
    beats_per_minute: int | None


@dataclass(frozen=True)
class PowerData:
    watts: int
    cadence_rpm: int | None = None


@dataclass(frozen=True)
class SpeedCadenceData:
    wheel: Counter | None = None
    crank: Counter | None = None


@dataclass(frozen=True)
class TrainerData:
    """What a fitness equipment page told us. Any field may be absent."""

    speed_ms: float | None = None
    cadence_rpm: int | None = None
    power_w: int | None = None
    heart_rate_bpm: int | None = None
    distance_m: int | None = None
    elapsed_s: float | None = None


def _checked(payload: bytes) -> bytes:
    if len(payload) != PAYLOAD_BYTES:
        raise PayloadError(
            f"an ANT+ broadcast is {PAYLOAD_BYTES} bytes, got {len(payload)}"
        )
    return payload


def _uint16(payload: bytes, offset: int) -> int:
    return int.from_bytes(payload[offset : offset + 2], "little")


def parse_heart_rate(payload: bytes) -> HeartRateData:
    """Heart rate. Every page of this profile carries the same last four bytes."""
    data = _checked(payload)
    rate = data[7]
    return HeartRateData(beats_per_minute=None if rate == 0 else rate)


def parse_power(payload: bytes) -> PowerData | None:
    """The standard power-only page. Other pages of this profile are ignored."""
    data = _checked(payload)
    if data[0] != PAGE_STANDARD_POWER:
        return None
    cadence = data[3]
    return PowerData(
        watts=_uint16(data, 6),
        cadence_rpm=None if cadence == INVALID_BYTE else cadence,
    )


def parse_speed_cadence(payload: bytes) -> SpeedCadenceData:
    """The combined speed and cadence sensor: both counters in one page."""
    data = _checked(payload)
    return SpeedCadenceData(
        crank=Counter(revolutions=_uint16(data, 2), event_time=_uint16(data, 0)),
        wheel=Counter(revolutions=_uint16(data, 6), event_time=_uint16(data, 4)),
    )


def parse_speed(payload: bytes) -> SpeedCadenceData:
    """A speed-only sensor: its counter always sits in the last four bytes."""
    data = _checked(payload)
    return SpeedCadenceData(
        wheel=Counter(revolutions=_uint16(data, 6), event_time=_uint16(data, 4))
    )


def parse_cadence(payload: bytes) -> SpeedCadenceData:
    """A cadence-only sensor, laid out like the speed-only one."""
    data = _checked(payload)
    return SpeedCadenceData(
        crank=Counter(revolutions=_uint16(data, 6), event_time=_uint16(data, 4))
    )


def parse_fitness_equipment(payload: bytes) -> TrainerData | None:
    """The two fitness equipment pages worth reading.

    Page 16 is what the trainer is doing as a machine - speed, distance, heart
    rate. Page 25 is what it is doing as a trainer - cadence and power. A trainer
    sends both, interleaved, so a rider gets all of it from one channel.
    """
    data = _checked(payload)
    if data[0] == PAGE_GENERAL_FE:
        return _general_fitness_equipment(data)
    if data[0] == PAGE_SPECIFIC_TRAINER:
        return _specific_trainer(data)
    return None


def _general_fitness_equipment(data: bytes) -> TrainerData:
    speed = _uint16(data, 4)
    heart_rate = data[6]
    return TrainerData(
        speed_ms=None if speed == INVALID_UINT16 else speed * FE_SPEED_UNIT_MS,
        heart_rate_bpm=None if heart_rate == INVALID_BYTE else heart_rate,
        distance_m=data[3],
        elapsed_s=data[2] * FE_TIME_UNIT_S,
    )


def _specific_trainer(data: bytes) -> TrainerData:
    cadence = data[2]
    # Instantaneous power is twelve bits: a whole byte plus the low nibble of the
    # next one, whose high nibble is the trainer's status instead.
    power = data[5] | ((data[6] & 0x0F) << 8)
    return TrainerData(
        cadence_rpm=None if cadence == INVALID_BYTE else cadence,
        power_w=None if power == POWER_INVALID else power,
    )
