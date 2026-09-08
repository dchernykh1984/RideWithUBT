"""Telling a smart trainer what to do.

Two protocols, one idea. A trainer can be asked to hold a power whatever the
rider does - ERG, which is what makes an interval an interval - or to behave as
though the rider were on a slope, which is what makes a course a course. Both
Bluetooth's Fitness Machine Service and ANT+ FE-C can do each; they disagree only
about the bytes.

As with reading, the encoding lives here as pure functions over numbers so it can
be tested without a trainer, and the transports only carry the bytes.

The scales are where the mistakes hide. FE-C sends power in quarter-watts and
grade as a percentage shifted by two hundred so a descent stays positive; FTMS
sends power in whole watts and grade in hundredths of a percent, signed. Getting
one wrong does not fail - it just holds the wrong number.
"""

from __future__ import annotations

import struct

# --- Bluetooth: the Fitness Machine Control Point (0x2AD9) --------------------

FTMS_REQUEST_CONTROL = 0x00
FTMS_RESET = 0x01
FTMS_SET_TARGET_POWER = 0x05
FTMS_START_OR_RESUME = 0x07
FTMS_SET_SIMULATION = 0x11

# Field scales, from the Fitness Machine Service specification.
FTMS_WIND_SPEED_SCALE = 1000  # metres per second, thousandths
FTMS_GRADE_SCALE = 100  # percent, hundredths
FTMS_CRR_SCALE = 10000
FTMS_CW_SCALE = 100  # kilograms per metre, hundredths

# --- ANT+: fitness equipment control pages -----------------------------------

FEC_PAGE_TARGET_POWER = 0x31
FEC_PAGE_TRACK_RESISTANCE = 0x33
FEC_POWER_SCALE = 4  # quarter watts
FEC_GRADE_SCALE = 100  # percent, hundredths
# Grade is sent unsigned with two hundred percent added, so a descent is positive.
FEC_GRADE_OFFSET = 200.0
FEC_CRR_SCALE = 20000  # the field's resolution is 5e-5
FEC_RESERVED = 0xFF
PAYLOAD_BYTES = 8

# Sensible bounds. A trainer asked for something outside them would clamp, refuse
# or wrap, and wrapping is the one that would silently apply the opposite.
MAX_TARGET_W = 2000
MIN_GRADE = -40.0
MAX_GRADE = 40.0
DEFAULT_CRR = 0.004


class ControlError(ValueError):
    """A command a trainer could not be asked to carry out."""


def _checked_power(watts: float) -> int:
    rounded = round(watts)
    if not 0 <= rounded <= MAX_TARGET_W:
        raise ControlError(f"{rounded} W is not a target a trainer can hold")
    return rounded


def _checked_grade(percent: float) -> float:
    if not MIN_GRADE <= percent <= MAX_GRADE:
        raise ControlError(f"{percent}% is not a gradient anyone rides")
    return percent


def ftms_request_control() -> bytes:
    """Ask for permission to command the trainer. Everything else needs it first."""
    return bytes([FTMS_REQUEST_CONTROL])


def ftms_start() -> bytes:
    return bytes([FTMS_START_OR_RESUME])


def ftms_reset() -> bytes:
    return bytes([FTMS_RESET])


def ftms_target_power(watts: float) -> bytes:
    """Hold this power whatever the rider does: ERG."""
    return struct.pack("<Bh", FTMS_SET_TARGET_POWER, _checked_power(watts))


def ftms_simulation(
    grade_percent: float,
    crr: float = DEFAULT_CRR,
    wind_speed_ms: float = 0.0,
    wind_area: float = 0.51,
) -> bytes:
    """Behave as though the rider were on this slope, in this air."""
    return struct.pack(
        "<BhhBB",
        FTMS_SET_SIMULATION,
        round(wind_speed_ms * FTMS_WIND_SPEED_SCALE),
        round(_checked_grade(grade_percent) * FTMS_GRADE_SCALE),
        round(crr * FTMS_CRR_SCALE),
        round(wind_area * FTMS_CW_SCALE),
    )


def fec_target_power(watts: float) -> bytes:
    """FE-C page 49. Power is in quarter watts, in the last two bytes."""
    target = _checked_power(watts) * FEC_POWER_SCALE
    return struct.pack(
        "<BBBBBBH",
        FEC_PAGE_TARGET_POWER,
        FEC_RESERVED,
        FEC_RESERVED,
        FEC_RESERVED,
        FEC_RESERVED,
        FEC_RESERVED,
        target,
    )


def fec_track_resistance(grade_percent: float, crr: float = DEFAULT_CRR) -> bytes:
    """FE-C page 51: the slope to simulate, and what the tyres are rolling on."""
    grade = round((_checked_grade(grade_percent) + FEC_GRADE_OFFSET) * FEC_GRADE_SCALE)
    return struct.pack(
        "<BBBBBHB",
        FEC_PAGE_TRACK_RESISTANCE,
        FEC_RESERVED,
        FEC_RESERVED,
        FEC_RESERVED,
        FEC_RESERVED,
        grade,
        round(crr * FEC_CRR_SCALE),
    )
