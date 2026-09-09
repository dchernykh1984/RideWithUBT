"""One live picture of the rider, out of however many devices are connected.

Readings arrive from several devices at different rates, and some of them
overlap: a smart trainer and a power meter both report power, two straps both
report heart rate. The hub decides which value is current, forgets values whose
device has gone quiet, and fills in power from wheel speed when there is nothing
better - marking it estimated when it does.

It is also the one place in the app where two threads meet. Radios deliver on
their own thread and the renderer reads on the main one, so every touch of the
stored readings is taken under a lock. It is a cheap one - a handful of
dictionary operations - and it is the difference between a defined snapshot and
one taken half way through an update.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from app.sensors.types import Metric, MetricValue, Reading, RideSnapshot
from app.trainer.estimate import PowerEstimator

# How long a reading stays current. Sensors report at roughly 1 Hz, so a few
# seconds of silence means the device has dropped out, not that the rider is
# holding a value perfectly steady.
DEFAULT_STALE_AFTER_S = 4.0


@dataclass
class SensorHub:
    """Collects readings and answers what is true right now."""

    stale_after_s: float = DEFAULT_STALE_AFTER_S
    estimator: PowerEstimator | None = None
    preferred: dict[Metric, str] = field(default_factory=dict)
    _latest: dict[tuple[Metric, str], Reading] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def submit(self, reading: Reading) -> None:
        """Take one reading. The newest from a given device replaces the last.

        Called from whichever thread the radio delivers on.
        """
        with self._lock:
            self._latest[(reading.metric, reading.source)] = reading

    def prefer(self, metric: Metric, source: str) -> None:
        """Pin a metric to one device, for a rider with two of something."""
        self.preferred[metric] = source

    def forget(self, source: str) -> None:
        """Drop everything from a device, on disconnect."""
        for key in [key for key in self._latest if key[1] == source]:
            del self._latest[key]

    def sources(self, metric: Metric) -> list[str]:
        """Which devices are currently offering this metric."""
        return sorted(
            source
            for reading_metric, source in self._latest
            if reading_metric == metric
        )

    def _current(self, metric: Metric, now: float) -> Reading | None:
        """The reading to believe for this metric, or None if nothing is fresh."""
        with self._lock:
            fresh = [
                reading
                for (reading_metric, _), reading in self._latest.items()
                if reading_metric == metric and now - reading.at <= self.stale_after_s
            ]
        if not fresh:
            return None
        pinned = self.preferred.get(metric)
        if pinned is not None:
            for reading in fresh:
                if reading.source == pinned:
                    return reading
        # A measurement beats an estimate; between equals, the newest wins.
        return max(fresh, key=lambda reading: (not reading.estimated, reading.at))

    def _value(self, metric: Metric, now: float) -> MetricValue | None:
        reading = self._current(metric, now)
        if reading is None:
            return None
        return MetricValue(
            value=reading.value,
            source=reading.source,
            age_s=now - reading.at,
            estimated=reading.estimated,
        )

    def snapshot(self, now: float) -> RideSnapshot:
        """What the rider's screen and the recorder should both be looking at."""
        speed = self._value(Metric.SPEED, now)
        power = self._value(Metric.POWER, now)
        if power is None and speed is not None:
            power = self._estimate_power(speed, now)
        return RideSnapshot(
            at=now,
            power=power,
            cadence=self._value(Metric.CADENCE, now),
            speed=speed,
            heart_rate=self._value(Metric.HEART_RATE, now),
        )

    def _estimate_power(self, speed: MetricValue, now: float) -> MetricValue | None:
        """Watts from wheel speed, for a rider with no power meter.

        Only reached when nothing measured power, so it cannot override a real
        measurement, and what it produces is always marked estimated.
        """
        if self.estimator is None:
            return None
        estimate = self.estimator.from_speed(speed.value)
        if estimate is None:
            return None
        return MetricValue(
            value=estimate.watts,
            source=self.estimator.trainer.id,
            age_s=speed.age_s,
            estimated=True,
        )
