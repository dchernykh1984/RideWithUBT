"""A recorded ride, as a FIT activity file.

## No coordinates, on purpose

A ride in a virtual world is not a ride at the place the world was traced from.
Writing Sokol's real coordinates into an indoor recording would upload something
that looks like an outdoor ride at Sokol - and would put times on the real
segments there, against people who actually rode them. So a recording carries
distance, speed, power, cadence, heart rate and altitude, and no position at all.

The activity is also marked as a virtual one in the file itself, which is what
Garmin Connect and Strava read to show it as such rather than as a ride outdoors.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.storage.fit import (
    ACTIVITY_EVENT,
    ACTIVITY_TYPE_MANUAL,
    ALTITUDE_OFFSET,
    ALTITUDE_SCALE,
    BASE_ENUM,
    BASE_UINT8,
    BASE_UINT16,
    BASE_UINT32,
    BASE_UINT32Z,
    DISTANCE_SCALE,
    EVENT_LAP,
    EVENT_SESSION,
    EVENT_TYPE_STOP,
    FILE_TYPE_ACTIVITY,
    MANUFACTURER_DEVELOPMENT,
    MESSAGE_ACTIVITY,
    MESSAGE_FILE_ID,
    MESSAGE_LAP,
    MESSAGE_RECORD,
    MESSAGE_SESSION,
    SPEED_SCALE,
    SPORT_CYCLING,
    SUB_SPORT_VIRTUAL_ACTIVITY,
    TIME_SCALE,
    Definition,
    Field,
    FitWriter,
    timestamp,
)

# Local slots. Any four bits would do; these are just kept in message order.
SLOT_FILE_ID = 0
SLOT_RECORD = 1
SLOT_LAP = 2
SLOT_SESSION = 3
SLOT_ACTIVITY = 4


class EmptyRideError(ValueError):
    """A ride with nothing in it is not a file worth writing."""


@dataclass(frozen=True)
class RideSample:
    """One second of a ride, as it will be written."""

    at: datetime
    distance_m: float
    speed_ms: float
    altitude_m: float = 0.0
    power_w: float | None = None
    cadence_rpm: float | None = None
    heart_rate_bpm: float | None = None


FILE_ID_FIELDS = (
    Field(0, BASE_ENUM),  # type
    Field(1, BASE_UINT16),  # manufacturer
    Field(2, BASE_UINT16),  # product
    Field(3, BASE_UINT32Z),  # serial number
    Field(4, BASE_UINT32),  # time created
)
RECORD_FIELDS = (
    Field(253, BASE_UINT32),  # timestamp
    Field(2, BASE_UINT16),  # altitude
    Field(3, BASE_UINT8),  # heart rate
    Field(4, BASE_UINT8),  # cadence
    Field(5, BASE_UINT32),  # distance
    Field(6, BASE_UINT16),  # speed
    Field(7, BASE_UINT16),  # power
)
LAP_FIELDS = (
    Field(254, BASE_UINT16),  # message index
    Field(253, BASE_UINT32),  # timestamp
    Field(0, BASE_ENUM),  # event
    Field(1, BASE_ENUM),  # event type
    Field(2, BASE_UINT32),  # start time
    Field(7, BASE_UINT32),  # total elapsed time
    Field(8, BASE_UINT32),  # total timer time
    Field(9, BASE_UINT32),  # total distance
)
SESSION_FIELDS = (
    Field(254, BASE_UINT16),  # message index
    Field(253, BASE_UINT32),  # timestamp
    Field(0, BASE_ENUM),  # event
    Field(1, BASE_ENUM),  # event type
    Field(2, BASE_UINT32),  # start time
    Field(5, BASE_ENUM),  # sport
    Field(6, BASE_ENUM),  # sub sport
    Field(7, BASE_UINT32),  # total elapsed time
    Field(8, BASE_UINT32),  # total timer time
    Field(9, BASE_UINT32),  # total distance
    Field(14, BASE_UINT16),  # average speed
    Field(15, BASE_UINT16),  # maximum speed
    Field(16, BASE_UINT8),  # average heart rate
    Field(18, BASE_UINT8),  # average cadence
    Field(20, BASE_UINT16),  # average power
    Field(21, BASE_UINT16),  # maximum power
    Field(25, BASE_UINT16),  # first lap index
    Field(26, BASE_UINT16),  # number of laps
)
ACTIVITY_FIELDS = (
    Field(253, BASE_UINT32),  # timestamp
    Field(0, BASE_UINT32),  # total timer time
    Field(1, BASE_UINT16),  # number of sessions
    Field(2, BASE_ENUM),  # type
    Field(3, BASE_ENUM),  # event
    Field(4, BASE_ENUM),  # event type
)


def _average(values: Sequence[float]) -> int | None:
    return round(sum(values) / len(values)) if values else None


def _maximum(values: Sequence[float]) -> int | None:
    return round(max(values)) if values else None


def encode_activity(samples: Sequence[RideSample]) -> bytes:
    """Turn a ride into the bytes of a FIT activity file."""
    if not samples:
        raise EmptyRideError("a ride with no samples cannot be written")
    writer = FitWriter()
    start, end = samples[0], samples[-1]
    elapsed_s = (end.at - start.at).total_seconds()

    writer.define(Definition(SLOT_FILE_ID, MESSAGE_FILE_ID, FILE_ID_FIELDS))
    writer.write(
        SLOT_FILE_ID,
        {
            0: FILE_TYPE_ACTIVITY,
            1: MANUFACTURER_DEVELOPMENT,
            2: 0,
            3: None,
            4: timestamp(start.at),
        },
    )

    writer.define(Definition(SLOT_RECORD, MESSAGE_RECORD, RECORD_FIELDS))
    for sample in samples:
        writer.write(SLOT_RECORD, _record(sample))

    totals = _totals(samples)
    writer.define(Definition(SLOT_LAP, MESSAGE_LAP, LAP_FIELDS))
    writer.write(
        SLOT_LAP,
        {
            254: 0,
            253: timestamp(end.at),
            0: EVENT_LAP,
            1: EVENT_TYPE_STOP,
            2: timestamp(start.at),
            7: round(elapsed_s * TIME_SCALE),
            8: round(elapsed_s * TIME_SCALE),
            9: round(end.distance_m * DISTANCE_SCALE),
        },
    )

    writer.define(Definition(SLOT_SESSION, MESSAGE_SESSION, SESSION_FIELDS))
    writer.write(
        SLOT_SESSION,
        {
            254: 0,
            253: timestamp(end.at),
            0: EVENT_SESSION,
            1: EVENT_TYPE_STOP,
            2: timestamp(start.at),
            5: SPORT_CYCLING,
            6: SUB_SPORT_VIRTUAL_ACTIVITY,
            7: round(elapsed_s * TIME_SCALE),
            8: round(elapsed_s * TIME_SCALE),
            9: round(end.distance_m * DISTANCE_SCALE),
            25: 0,
            26: 1,
            **totals,
        },
    )

    writer.define(Definition(SLOT_ACTIVITY, MESSAGE_ACTIVITY, ACTIVITY_FIELDS))
    writer.write(
        SLOT_ACTIVITY,
        {
            253: timestamp(end.at),
            0: round(elapsed_s * TIME_SCALE),
            1: 1,
            2: ACTIVITY_TYPE_MANUAL,
            3: ACTIVITY_EVENT,
            4: EVENT_TYPE_STOP,
        },
    )
    return writer.to_bytes()


def _record(sample: RideSample) -> dict[int, int | None]:
    return {
        253: timestamp(sample.at),
        2: round(sample.altitude_m * ALTITUDE_SCALE + ALTITUDE_OFFSET * ALTITUDE_SCALE),
        3: round(sample.heart_rate_bpm) if sample.heart_rate_bpm else None,
        4: round(sample.cadence_rpm) if sample.cadence_rpm is not None else None,
        5: round(sample.distance_m * DISTANCE_SCALE),
        6: round(sample.speed_ms * SPEED_SCALE),
        7: round(sample.power_w) if sample.power_w is not None else None,
    }


def _totals(samples: Sequence[RideSample]) -> dict[int, int | None]:
    speeds = [sample.speed_ms for sample in samples]
    powers = [s.power_w for s in samples if s.power_w is not None]
    cadences = [s.cadence_rpm for s in samples if s.cadence_rpm is not None]
    heart_rates = [s.heart_rate_bpm for s in samples if s.heart_rate_bpm]
    return {
        14: round(sum(speeds) / len(speeds) * SPEED_SCALE),
        15: round(max(speeds) * SPEED_SCALE),
        16: _average(heart_rates),
        18: _average(cadences),
        20: _average(powers),
        21: _maximum(powers),
    }
