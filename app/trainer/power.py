"""Power curves: watts from wheel speed, and a curve fitted from measurements.

A trainer absorbs power as a function of how fast the wheel drives it. Fluid and
air units rise roughly with the cube of speed, magnetic units roughly with the
square, so one family of curves covers all of them:

    P = coefficient * speed ** exponent + offset

Two ways to get such a curve. A *profile* is one recorded from a real trainer
against a real power meter - measured, reusable, contributable. A *generic* curve
is a rough stand-in keyed off the resistance type, used until someone records a
profile. The difference is not cosmetic, so it is carried in the type
(``is_calibrated``) and must be shown to the rider: uncalibrated watts are an
estimate, and training on them without knowing that is worse than not having them.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

# Speeds below this are freewheeling or noise: a stopped wheel makes no watts,
# and dividing the log-log fit by them would swamp it.
MIN_FIT_SPEED_MS = 2.0
# A curve fitted to a narrow speed band extrapolates badly, and a handful of
# samples fits noise. Both are refused rather than quietly published.
MIN_FIT_SAMPLES = 20
MIN_FIT_SPEED_SPAN_MS = 2.5


class NotEnoughDataError(ValueError):
    """The samples cannot support a trustworthy curve."""


@dataclass(frozen=True)
class PowerCurve:
    """P = coefficient * speed ** exponent + offset_w, over wheel speed in m/s."""

    coefficient: float
    exponent: float
    offset_w: float = 0.0

    def power_w(self, speed_ms: float) -> float:
        """Watts absorbed at this wheel speed. Never negative, zero when stopped."""
        if speed_ms <= 0.0:
            return 0.0
        return max(0.0, self.coefficient * speed_ms**self.exponent + self.offset_w)


# Rough stand-ins, one per resistance type, anchored at 30 km/h (8.33 m/s):
# a fluid unit takes about 200 W there, a magnetic one about 180 W, and rollers
# about 130 W. The exponents come from how each brake works - fluid and air
# resistance rise with the square of speed, so power rises with the cube, while
# an eddy-current brake's drag is closer to linear. They exist so a rider can
# start immediately; they are not a substitute for recording a profile.
GENERIC_CURVES: dict[str, PowerCurve] = {
    "fluid": PowerCurve(coefficient=0.346, exponent=3.0),
    "air": PowerCurve(coefficient=0.225, exponent=3.0),
    "magnetic": PowerCurve(coefficient=2.59, exponent=2.0),
}


def generic_curve(resistance: str) -> PowerCurve | None:
    """A stand-in curve for a resistance type, or None if estimating is wrong here.

    Electromagnetic and motor-brake units are the trainers that measure and report
    their own power. Estimating theirs from wheel speed would replace a real
    measurement with a guess, so this returns None and the caller uses the device.
    """
    return GENERIC_CURVES.get(resistance)


@dataclass(frozen=True)
class CurveFit:
    """A curve fitted from measurements, with what is needed to judge it."""

    curve: PowerCurve
    samples: int
    rms_error_w: float
    speed_range_ms: tuple[float, float]

    @property
    def speed_range_kmh(self) -> tuple[float, float]:
        low, high = self.speed_range_ms
        return (low * 3.6, high * 3.6)


def usable_samples(
    samples: Sequence[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Drop the pairs a log-log fit cannot use: coasting, stopping, zero power."""
    return [
        (speed, power)
        for speed, power in samples
        if speed >= MIN_FIT_SPEED_MS and power > 0.0
    ]


def fit_power_curve(samples: Sequence[tuple[float, float]]) -> CurveFit:
    """Fit P = k * v**n to measured (wheel speed in m/s, power in W) pairs.

    Taking logs turns the power law into a straight line, so this is an ordinary
    least-squares fit in log space. That weights the low-speed end more evenly
    than fitting in watts would, which is what we want: the curve has to be
    honest in the range people warm up in, not just where the numbers are big.
    """
    usable = usable_samples(samples)
    if len(usable) < MIN_FIT_SAMPLES:
        raise NotEnoughDataError(
            f"{len(usable)} usable samples, need at least {MIN_FIT_SAMPLES}"
        )
    speeds = [speed for speed, _ in usable]
    low, high = min(speeds), max(speeds)
    if high - low < MIN_FIT_SPEED_SPAN_MS:
        raise NotEnoughDataError(
            f"samples span {(high - low) * 3.6:.1f} km/h, need at least "
            f"{MIN_FIT_SPEED_SPAN_MS * 3.6:.1f} km/h - ride the whole range"
        )

    count = len(usable)
    xs = [math.log(speed) for speed, _ in usable]
    ys = [math.log(power) for _, power in usable]
    mean_x = sum(xs) / count
    mean_y = sum(ys) / count
    variance = sum((x - mean_x) ** 2 for x in xs)
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    exponent = covariance / variance
    coefficient = math.exp(mean_y - exponent * mean_x)

    curve = PowerCurve(coefficient=coefficient, exponent=exponent)
    error = math.sqrt(
        sum((curve.power_w(speed) - power) ** 2 for speed, power in usable) / count
    )
    return CurveFit(
        curve=curve,
        samples=count,
        rms_error_w=error,
        speed_range_ms=(low, high),
    )
