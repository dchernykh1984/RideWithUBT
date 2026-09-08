"""The ANT+ transport.

Shaped like the Bluetooth one: `ant_protocol` parses, this module wires. What
differs is the radio underneath. ANT+ needs a USB stick and openant drives it
from its own blocking loop in a worker thread, so the radio sits behind a small
`Radio` protocol - which is also what lets `connect` and `disconnect` be tested
against a fake instead of a dongle.

Which sensor a broadcast came from is not in the payload: the same eight bytes
mean different things per device type, and the device type belongs to the
channel. So an `AntSensor` is created for one device type and stays that way.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

from app.sensors import ant_protocol as pages
from app.sensors.base import DeviceInfo, ReadingSink, Transport
from app.sensors.revolutions import Cadence, WheelSpeed
from app.sensors.types import Metric, Reading
from app.trainer.wheels import Wheel

# What each profile can tell us, and what to call it before the rider renames it.
DEVICE_PROFILES: dict[int, tuple[str, frozenset[Metric]]] = {
    pages.DEVICE_HEART_RATE: ("Heart rate monitor", frozenset({Metric.HEART_RATE})),
    pages.DEVICE_POWER: (
        "Power meter",
        frozenset({Metric.POWER, Metric.CADENCE}),
    ),
    pages.DEVICE_SPEED_CADENCE: (
        "Speed and cadence sensor",
        frozenset({Metric.SPEED, Metric.CADENCE}),
    ),
    pages.DEVICE_CADENCE: ("Cadence sensor", frozenset({Metric.CADENCE})),
    pages.DEVICE_SPEED: ("Speed sensor", frozenset({Metric.SPEED})),
    pages.DEVICE_FITNESS_EQUIPMENT: (
        "Smart trainer",
        frozenset({Metric.SPEED, Metric.CADENCE, Metric.POWER, Metric.HEART_RATE}),
    ),
}
# Fitness equipment is the profile that also takes commands, which is what ERG
# mode and on-course gradient will need.
CONTROLLABLE_DEVICE_TYPES = frozenset({pages.DEVICE_FITNESS_EQUIPMENT})


def device_id(device_type: int, device_number: int) -> str:
    """A stable id for a paired sensor. Settings and profiles store this."""
    return f"ant:{device_type}:{device_number}"


def device_from_channel(device_type: int, device_number: int) -> DeviceInfo | None:
    """Describe a sensor seen on a channel, or None for a profile we do not read."""
    profile = DEVICE_PROFILES.get(device_type)
    if profile is None:
        return None
    name, metrics = profile
    return DeviceInfo(
        id=device_id(device_type, device_number),
        name=f"{name} #{device_number}",
        transport=Transport.ANT,
        metrics=metrics,
        controllable=device_type in CONTROLLABLE_DEVICE_TYPES,
    )


class Radio(Protocol):
    """The USB stick, reduced to what a sensor needs from it."""

    async def subscribe(
        self,
        device_type: int,
        device_number: int,
        on_broadcast: Callable[[bytes], None],
    ) -> None: ...

    async def unsubscribe(self, device_type: int, device_number: int) -> None: ...


class AntSensor:
    """One paired ANT+ sensor, translated into readings."""

    def __init__(
        self,
        device: DeviceInfo,
        device_type: int,
        device_number: int,
        wheel: Wheel | None = None,
        radio: Radio | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._device = device
        self._device_type = device_type
        self._device_number = device_number
        self._wheel = wheel
        self._radio = radio
        self._clock = clock
        self._subscribed = False
        self._cadence = Cadence()
        self._wheel_speed = WheelSpeed(rollout_mm=wheel.rollout_mm if wheel else 0.0)

    @property
    def device(self) -> DeviceInfo:
        return self._device

    def handle(self, payload: bytes) -> list[Reading]:
        """Turn one broadcast into readings. The whole translation path."""
        now = self._clock()
        match self._device_type:
            case pages.DEVICE_HEART_RATE:
                return self._heart_rate(payload, now)
            case pages.DEVICE_POWER:
                return self._power(payload, now)
            case pages.DEVICE_SPEED_CADENCE:
                return self._counters(pages.parse_speed_cadence(payload), now)
            case pages.DEVICE_SPEED:
                return self._counters(pages.parse_speed(payload), now)
            case pages.DEVICE_CADENCE:
                return self._counters(pages.parse_cadence(payload), now)
            case pages.DEVICE_FITNESS_EQUIPMENT:
                return self._fitness_equipment(payload, now)
        return []

    def _reading(self, metric: Metric, value: float, now: float) -> Reading:
        return Reading(
            metric=metric, value=float(value), at=now, source=self._device.id
        )

    def _heart_rate(self, payload: bytes, now: float) -> list[Reading]:
        rate = pages.parse_heart_rate(payload).beats_per_minute
        if rate is None:
            return []
        return [self._reading(Metric.HEART_RATE, rate, now)]

    def _power(self, payload: bytes, now: float) -> list[Reading]:
        measurement = pages.parse_power(payload)
        if measurement is None:
            return []
        readings = [self._reading(Metric.POWER, measurement.watts, now)]
        if measurement.cadence_rpm is not None:
            readings.append(self._reading(Metric.CADENCE, measurement.cadence_rpm, now))
        return readings

    def _counters(self, data: pages.SpeedCadenceData, now: float) -> list[Reading]:
        readings = []
        if data.wheel is not None and self._wheel is not None:
            speed = self._wheel_speed.update(
                data.wheel.revolutions, data.wheel.event_time, now
            )
            if speed is not None:
                readings.append(self._reading(Metric.SPEED, speed, now))
        if data.crank is not None:
            cadence = self._cadence.update(
                data.crank.revolutions, data.crank.event_time, now
            )
            if cadence is not None:
                readings.append(self._reading(Metric.CADENCE, cadence, now))
        return readings

    def _fitness_equipment(self, payload: bytes, now: float) -> list[Reading]:
        data = pages.parse_fitness_equipment(payload)
        if data is None:
            return []
        values = (
            (Metric.SPEED, data.speed_ms),
            (Metric.CADENCE, data.cadence_rpm),
            (Metric.POWER, data.power_w),
            (Metric.HEART_RATE, data.heart_rate_bpm),
        )
        return [
            self._reading(metric, value, now)
            for metric, value in values
            if value is not None
        ]

    async def connect(self, sink: ReadingSink) -> None:
        if self._radio is None or self._subscribed:
            return

        def on_broadcast(payload: bytes) -> None:
            for reading in self.handle(payload):
                sink(reading)

        await self._radio.subscribe(
            self._device_type, self._device_number, on_broadcast
        )
        self._subscribed = True

    async def disconnect(self) -> None:
        if self._radio is None or not self._subscribed:
            return
        await self._radio.unsubscribe(self._device_type, self._device_number)
        self._subscribed = False
