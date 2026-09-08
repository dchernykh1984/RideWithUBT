"""Parsing the standard Bluetooth cycling characteristics.

These payloads are public, stable and fiddly: a leading flags field says which
optional fields follow, and every optional field shifts the offset of the ones
after it. Getting an offset wrong does not raise - it silently reads a cadence
out of the middle of a power value.

So the parsing lives here, as pure functions over bytes, and is tested against
payloads written out field by field. `ble.py` only moves bytes from a radio into
these functions.

Characteristics covered:

* Heart Rate Measurement (0x2A37)
* Cycling Power Measurement (0x2A63)
* Cycling Speed and Cadence Measurement (0x2A5B)
* Indoor Bike Data (0x2AD2), the Fitness Machine Service's ride telemetry
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

# Cycling Power reports its wheel event time in 1/2048 s, while Cycling Speed and
# Cadence uses 1/1024 s for both wheel and crank. Mixing the two up halves or
# doubles the resulting speed, so each parser states which it produced.
CPS_WHEEL_TICKS_PER_SECOND = 2048
CSC_TICKS_PER_SECOND = 1024
CRANK_TICKS_PER_SECOND = 1024


class PayloadError(ValueError):
    """A payload too short for the fields its flags claim."""


@dataclass(frozen=True)
class WheelData:
    """A cumulative wheel counter, as reported. Rates are computed elsewhere."""

    revolutions: int
    event_time: int
    ticks_per_second: int


@dataclass(frozen=True)
class CrankData:
    revolutions: int
    event_time: int
    ticks_per_second: int = CRANK_TICKS_PER_SECOND


@dataclass(frozen=True)
class PowerMeasurement:
    watts: int
    wheel: WheelData | None = None
    crank: CrankData | None = None


@dataclass(frozen=True)
class SpeedCadenceMeasurement:
    wheel: WheelData | None = None
    crank: CrankData | None = None


@dataclass(frozen=True)
class IndoorBikeData:
    """Whatever the trainer chose to send this notification."""

    speed_ms: float | None = None
    cadence_rpm: float | None = None
    power_w: int | None = None
    heart_rate_bpm: int | None = None
    resistance_level: float | None = None
    distance_m: int | None = None


class _Cursor:
    """Walks a payload, refusing to read past its end."""

    def __init__(self, payload: bytes, name: str) -> None:
        self._payload = payload
        self._name = name
        self._offset = 0

    def take(self, fmt: str) -> tuple[int, ...]:
        size = struct.calcsize(fmt)
        end = self._offset + size
        if end > len(self._payload):
            raise PayloadError(
                f"{self._name}: payload of {len(self._payload)} bytes is too short "
                f"for a {size}-byte field at offset {self._offset}"
            )
        values: tuple[int, ...] = struct.unpack_from(fmt, self._payload, self._offset)
        self._offset = end
        return values

    def one(self, fmt: str) -> int:
        return self.take(fmt)[0]

    def raw(self, size: int) -> bytes:
        end = self._offset + size
        if end > len(self._payload):
            raise PayloadError(
                f"{self._name}: payload of {len(self._payload)} bytes is too short "
                f"for a {size}-byte field at offset {self._offset}"
            )
        chunk = self._payload[self._offset : end]
        self._offset = end
        return chunk

    def skip(self, size: int) -> None:
        self._offset += size


def parse_heart_rate(payload: bytes) -> int:
    """Heart Rate Measurement (0x2A37). Flag bit 0 widens the value to 16 bits."""
    cursor = _Cursor(payload, "heart rate")
    flags = cursor.one("<B")
    return cursor.one("<H") if flags & 0x01 else cursor.one("<B")


def parse_cycling_power(payload: bytes) -> PowerMeasurement:
    """Cycling Power Measurement (0x2A63).

    Instantaneous power is the only mandatory field, but the optional ones that
    precede the revolution data have to be stepped over in the order the flags
    declare them, which is why this reads as a walk rather than a struct.
    """
    cursor = _Cursor(payload, "cycling power")
    flags = cursor.one("<H")
    watts = cursor.one("<h")
    if flags & 0x0001:  # pedal power balance
        cursor.skip(1)
    if flags & 0x0004:  # accumulated torque
        cursor.skip(2)
    wheel = None
    if flags & 0x0010:
        revolutions, event_time = cursor.take("<IH")
        wheel = WheelData(revolutions, event_time, CPS_WHEEL_TICKS_PER_SECOND)
    crank = None
    if flags & 0x0020:
        revolutions, event_time = cursor.take("<HH")
        crank = CrankData(revolutions, event_time)
    return PowerMeasurement(watts=watts, wheel=wheel, crank=crank)


def parse_speed_cadence(payload: bytes) -> SpeedCadenceMeasurement:
    """Cycling Speed and Cadence Measurement (0x2A5B)."""
    cursor = _Cursor(payload, "speed and cadence")
    flags = cursor.one("<B")
    wheel = None
    if flags & 0x01:
        revolutions, event_time = cursor.take("<IH")
        wheel = WheelData(revolutions, event_time, CSC_TICKS_PER_SECOND)
    crank = None
    if flags & 0x02:
        revolutions, event_time = cursor.take("<HH")
        crank = CrankData(revolutions, event_time)
    return SpeedCadenceMeasurement(wheel=wheel, crank=crank)


# Indoor Bike Data fields, in the order the specification lays them out: the flag
# that announces the field, the struct format for the whole field group, and the
# name to keep the first value under (None means step over it).
_UINT24_DISTANCE = 0x0010
_INDOOR_BIKE_FIELDS: tuple[tuple[int, str, str | None], ...] = (
    (0x0002, "<H", None),  # average speed
    (0x0004, "<H", "cadence"),
    (0x0008, "<H", None),  # average cadence
    (_UINT24_DISTANCE, "", "distance"),  # total distance: 24 bits, handled apart
    (0x0020, "<h", "resistance"),
    (0x0040, "<h", "power"),
    (0x0080, "<h", None),  # average power
    (0x0100, "<HHB", None),  # expended energy: total, per hour, per minute
    (0x0200, "<B", "heart_rate"),
    (0x0400, "<B", None),  # metabolic equivalent
    (0x0800, "<H", None),  # elapsed time
    (0x1000, "<H", None),  # remaining time
)


def parse_indoor_bike_data(payload: bytes) -> IndoorBikeData:
    """Indoor Bike Data (0x2AD2), the Fitness Machine Service's ride telemetry.

    Note the inversion in the first flag: bit 0 is "More Data", and instantaneous
    speed is present when it is *clear*. Reading it the obvious way round shifts
    every following field by two bytes.
    """
    cursor = _Cursor(payload, "indoor bike data")
    flags = cursor.one("<H")
    values: dict[str, float] = {}
    if not flags & 0x0001:
        values["speed"] = cursor.one("<H") * 0.01  # 0.01 km/h
    for flag, fmt, name in _INDOOR_BIKE_FIELDS:
        if not flags & flag:
            continue
        if flag == _UINT24_DISTANCE:
            values["distance"] = int.from_bytes(cursor.raw(3), "little")
            continue
        value = cursor.take(fmt)[0]
        if name is not None:
            values[name] = value
    return IndoorBikeData(
        speed_ms=_kmh_to_ms(values.get("speed")),
        cadence_rpm=_scaled(values.get("cadence"), 0.5),
        power_w=_as_int(values.get("power")),
        heart_rate_bpm=_as_int(values.get("heart_rate")),
        # The FTMS specification gives resistance level a resolution of 0.1.
        resistance_level=_scaled(values.get("resistance"), 0.1),
        distance_m=_as_int(values.get("distance")),
    )


def _kmh_to_ms(value: float | None) -> float | None:
    return None if value is None else value / 3.6


def _scaled(value: float | None, factor: float) -> float | None:
    return None if value is None else value * factor


def _as_int(value: float | None) -> int | None:
    return None if value is None else int(value)
