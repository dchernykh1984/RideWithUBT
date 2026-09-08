"""A sensor source with no hardware behind it.

Two jobs. It is what the tests use, so the ride, the workout engine and the HUD
can be exercised without a radio. And it is what a developer rides while the
world is being built, or what a rider can use to look around a track before they
have set anything up.

The values it produces are deterministic: a fixed profile plus a smooth wobble
derived from elapsed time, never a random number. A test that feeds it the same
clock twice gets the same ride twice.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from dataclasses import dataclass

from app.sensors.base import DeviceInfo, ReadingSink, Transport
from app.sensors.types import Metric, Reading

SOURCE_ID = "simulated"
DEFAULT_INTERVAL_S = 1.0

# Amplitude of the wobble applied to each metric, so a screen shows a rider
# rather than a test pattern. Small enough not to change what a value means.
WOBBLE = {Metric.POWER: 0.04, Metric.CADENCE: 0.02, Metric.HEART_RATE: 0.01}
WOBBLE_PERIOD_S = 11.0


@dataclass(frozen=True)
class RiderState:
    """What the imaginary rider is doing at one moment."""

    power_w: float
    cadence_rpm: float
    heart_rate_bpm: float


Profile = Callable[[float], RiderState]


def steady(
    power_w: float = 180.0,
    cadence_rpm: float = 85.0,
    heart_rate_bpm: float = 140.0,
) -> Profile:
    """Riding along at one effort."""

    def profile(elapsed_s: float) -> RiderState:
        return RiderState(power_w, cadence_rpm, heart_rate_bpm)

    return profile


def intervals(
    work_s: float = 300.0,
    rest_s: float = 180.0,
    work_w: float = 280.0,
    rest_w: float = 120.0,
) -> Profile:
    """Hard efforts and recoveries, for exercising anything that reacts to them.

    Cadence and heart rate follow the effort, heart rate lagging the way a real
    one does - not modelled properly, just enough that a screen showing it does
    not look wrong.
    """
    cycle = work_s + rest_s

    def profile(elapsed_s: float) -> RiderState:
        position = elapsed_s % cycle
        working = position < work_s
        power = work_w if working else rest_w
        return RiderState(
            power_w=power,
            cadence_rpm=92.0 if working else 78.0,
            heart_rate_bpm=110.0 + (power - rest_w) * 0.25,
        )

    return profile


def wobble(metric: Metric, elapsed_s: float) -> float:
    """A smooth, repeatable multiplier around 1.0."""
    amplitude = WOBBLE.get(metric, 0.0)
    return 1.0 + amplitude * math.sin(2 * math.pi * elapsed_s / WOBBLE_PERIOD_S)


class SimulatedSensors:
    """A `SensorSource` that invents its readings."""

    def __init__(
        self, profile: Profile | None = None, interval_s: float = DEFAULT_INTERVAL_S
    ) -> None:
        self.profile = profile or steady()
        self.interval_s = interval_s
        self._task: asyncio.Task[None] | None = None

    @property
    def device(self) -> DeviceInfo:
        return DeviceInfo(
            id=SOURCE_ID,
            name="Simulated sensors",
            transport=Transport.SIMULATED,
            metrics=frozenset({Metric.POWER, Metric.CADENCE, Metric.HEART_RATE}),
        )

    def sample(self, elapsed_s: float, now: float) -> list[Reading]:
        """The readings this source would emit at a given point in the ride."""
        state = self.profile(elapsed_s)
        values = {
            Metric.POWER: state.power_w,
            Metric.CADENCE: state.cadence_rpm,
            Metric.HEART_RATE: state.heart_rate_bpm,
        }
        return [
            Reading(
                metric=metric,
                value=value * wobble(metric, elapsed_s),
                at=now,
                source=SOURCE_ID,
            )
            for metric, value in values.items()
        ]

    async def connect(self, sink: ReadingSink) -> None:
        """Start emitting readings once per interval until disconnected."""
        if self._task is not None:
            return
        loop = asyncio.get_running_loop()
        started = loop.time()
        self._task = asyncio.create_task(self._run(sink, started))

    async def _run(self, sink: ReadingSink, started: float) -> None:
        loop = asyncio.get_running_loop()
        while True:
            now = loop.time()
            for reading in self.sample(now - started, now):
                sink(reading)
            await asyncio.sleep(self.interval_s)

    async def disconnect(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
