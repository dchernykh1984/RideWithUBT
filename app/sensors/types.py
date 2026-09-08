"""What a sensor produces and what the app reads back."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Metric(StrEnum):
    """The quantities a ride is made of."""

    POWER = "power"
    CADENCE = "cadence"
    SPEED = "speed"
    HEART_RATE = "heart_rate"


# Unit per metric, stated once so nothing has to guess: watts, revolutions per
# minute, metres per second, beats per minute.
UNITS: dict[Metric, str] = {
    Metric.POWER: "W",
    Metric.CADENCE: "rpm",
    Metric.SPEED: "m/s",
    Metric.HEART_RATE: "bpm",
}


@dataclass(frozen=True)
class Reading:
    """One value from one device at one moment.

    ``at`` is a monotonic clock reading, not a wall clock: readings are compared
    to decide what is current, and a clock that can jump backwards would make
    fresh data look stale.

    ``estimated`` marks a value the app computed rather than measured - power
    derived from wheel speed, most of all. It travels with the value so that a
    screen or a workout can never silently treat an estimate as a measurement.
    """

    metric: Metric
    value: float
    at: float
    source: str
    estimated: bool = False


@dataclass(frozen=True)
class MetricValue:
    """A metric's current value, with where it came from and how old it is."""

    value: float
    source: str
    age_s: float
    estimated: bool


@dataclass(frozen=True)
class RideSnapshot:
    """Everything known about the rider right now. Missing means no live sensor."""

    at: float
    power: MetricValue | None = None
    cadence: MetricValue | None = None
    speed: MetricValue | None = None
    heart_rate: MetricValue | None = None

    def get(self, metric: Metric) -> MetricValue | None:
        return {
            Metric.POWER: self.power,
            Metric.CADENCE: self.cadence,
            Metric.SPEED: self.speed,
            Metric.HEART_RATE: self.heart_rate,
        }[metric]

    @property
    def has_power(self) -> bool:
        return self.power is not None
