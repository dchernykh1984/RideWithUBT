"""The Bluetooth Low Energy transport.

Thin on purpose. Bleak does the radio; `ble_protocol` does the parsing; this
module is the wiring between them, plus the bookkeeping that turns cumulative
counters into rates.

Everything that can be tested without a radio is: `BleSensor.handle` takes a
characteristic id and a payload and returns readings, so the whole translation
path is exercised from bytes to `Reading` with no device and no event loop
involved. Only `connect` and `disconnect` touch bleak.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from app.sensors.base import DeviceInfo, ReadingSink, Transport
from app.sensors.ble_protocol import (
    CRANK_TICKS_PER_SECOND,
    CrankData,
    IndoorBikeData,
    WheelData,
    parse_cycling_power,
    parse_heart_rate,
    parse_indoor_bike_data,
    parse_speed_cadence,
)
from app.sensors.control import BleTrainerControl
from app.sensors.revolutions import Cadence, WheelSpeed
from app.sensors.types import Metric, Reading
from app.trainer.wheels import Wheel


def uuid(short: int) -> str:
    """Expand a 16-bit assigned number into the full 128-bit UUID bleak reports."""
    return f"0000{short:04x}-0000-1000-8000-00805f9b34fb"


HEART_RATE_SERVICE = uuid(0x180D)
CYCLING_POWER_SERVICE = uuid(0x1818)
SPEED_CADENCE_SERVICE = uuid(0x1816)
FITNESS_MACHINE_SERVICE = uuid(0x1826)

HEART_RATE_MEASUREMENT = uuid(0x2A37)
CYCLING_POWER_MEASUREMENT = uuid(0x2A63)
SPEED_CADENCE_MEASUREMENT = uuid(0x2A5B)
INDOOR_BIKE_DATA = uuid(0x2AD2)
FITNESS_MACHINE_CONTROL_POINT = uuid(0x2AD9)

# What each service is worth subscribing to, and what it can tell us. A device
# advertising none of these is not offered to the rider.
SERVICE_CHARACTERISTIC: dict[str, str] = {
    HEART_RATE_SERVICE: HEART_RATE_MEASUREMENT,
    CYCLING_POWER_SERVICE: CYCLING_POWER_MEASUREMENT,
    SPEED_CADENCE_SERVICE: SPEED_CADENCE_MEASUREMENT,
    FITNESS_MACHINE_SERVICE: INDOOR_BIKE_DATA,
}
SERVICE_METRICS: dict[str, frozenset[Metric]] = {
    HEART_RATE_SERVICE: frozenset({Metric.HEART_RATE}),
    CYCLING_POWER_SERVICE: frozenset({Metric.POWER, Metric.CADENCE, Metric.SPEED}),
    SPEED_CADENCE_SERVICE: frozenset({Metric.SPEED, Metric.CADENCE}),
    FITNESS_MACHINE_SERVICE: frozenset(
        {Metric.POWER, Metric.CADENCE, Metric.SPEED, Metric.HEART_RATE}
    ),
}
# The Fitness Machine Service is the one that also takes commands, which is what
# ERG mode and on-course gradient will need.
CONTROLLABLE_SERVICES = frozenset({FITNESS_MACHINE_SERVICE})


def device_from_advertisement(
    address: str, name: str | None, service_uuids: Iterable[str]
) -> DeviceInfo | None:
    """Describe an advertising device, or None if it has nothing we can read."""
    advertised = {found.lower() for found in service_uuids}
    known = advertised & set(SERVICE_METRICS)
    if not known:
        return None
    metrics: set[Metric] = set()
    for service in known:
        metrics |= SERVICE_METRICS[service]
    return DeviceInfo(
        id=address,
        name=name or "Unnamed device",
        transport=Transport.BLE,
        metrics=frozenset(metrics),
        controllable=bool(known & CONTROLLABLE_SERVICES),
    )


Discover = Callable[[float], Awaitable[list[tuple[str, str | None, list[str]]]]]


async def _bleak_discover(
    seconds: float,
) -> list[tuple[str, str | None, list[str]]]:  # pragma: no cover - needs a radio
    from bleak import BleakScanner

    found = await BleakScanner.discover(timeout=seconds, return_adv=True)
    return [
        (device.address, device.name, list(advertisement.service_uuids))
        for device, advertisement in found.values()
    ]


class BleScanner:
    """Finds nearby sensors. ``discover`` is injectable so tests need no radio."""

    def __init__(self, discover: Discover | None = None) -> None:
        self._discover = discover or _bleak_discover

    async def scan(self, seconds: float = 5.0) -> list[DeviceInfo]:
        found = await self._discover(seconds)
        devices = [
            device
            for address, name, services in found
            if (device := device_from_advertisement(address, name, services))
        ]
        return sorted(devices, key=lambda device: device.name.lower())


class BleSensor:
    """One connected Bluetooth device, translated into readings.

    ``wheel`` is needed only to turn a wheel counter into speed; without it a
    speed sensor still reports, but its revolutions cannot be given a distance.
    """

    def __init__(
        self,
        device: DeviceInfo,
        services: Iterable[str],
        wheel: Wheel | None = None,
        client_factory: Callable[[str], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._device = device
        self._services = [service.lower() for service in services]
        self._wheel = wheel
        self._client_factory = client_factory or _bleak_client
        self._clock = clock
        self._client: Any = None
        self._cadence = Cadence(ticks_per_second=CRANK_TICKS_PER_SECOND)
        self._wheel_speed: dict[int, WheelSpeed] = {}

    @property
    def device(self) -> DeviceInfo:
        return self._device

    @property
    def characteristics(self) -> list[str]:
        """The notifications worth subscribing to on this device."""
        return [
            SERVICE_CHARACTERISTIC[service]
            for service in self._services
            if service in SERVICE_CHARACTERISTIC
        ]

    def handle(self, characteristic: str, payload: bytes) -> list[Reading]:
        """Turn one notification into readings. The whole translation path."""
        now = self._clock()
        which = characteristic.lower()
        if which == HEART_RATE_MEASUREMENT:
            return [self._reading(Metric.HEART_RATE, parse_heart_rate(payload), now)]
        if which == CYCLING_POWER_MEASUREMENT:
            power = parse_cycling_power(payload)
            return [
                self._reading(Metric.POWER, power.watts, now),
                *self._from_counters(power.wheel, power.crank, now),
            ]
        if which == SPEED_CADENCE_MEASUREMENT:
            speed_cadence = parse_speed_cadence(payload)
            return self._from_counters(speed_cadence.wheel, speed_cadence.crank, now)
        if which == INDOOR_BIKE_DATA:
            return self._from_indoor_bike(parse_indoor_bike_data(payload), now)
        return []

    def _reading(self, metric: Metric, value: float, now: float) -> Reading:
        return Reading(
            metric=metric, value=float(value), at=now, source=self._device.id
        )

    def _from_counters(
        self, wheel: WheelData | None, crank: CrankData | None, now: float
    ) -> list[Reading]:
        readings = []
        if wheel is not None and self._wheel is not None:
            speed = self._speed_tracker(wheel.ticks_per_second).update(
                wheel.revolutions, wheel.event_time, now
            )
            if speed is not None:
                readings.append(self._reading(Metric.SPEED, speed, now))
        if crank is not None:
            cadence = self._cadence.update(crank.revolutions, crank.event_time, now)
            if cadence is not None:
                readings.append(self._reading(Metric.CADENCE, cadence, now))
        return readings

    def _speed_tracker(self, ticks_per_second: int) -> WheelSpeed:
        """One tracker per event-clock resolution.

        A device can report wheel data through both Cycling Power (1/2048 s) and
        Speed and Cadence (1/1024 s); feeding both into one tracker would mix two
        clocks in a single difference.
        """
        tracker = self._wheel_speed.get(ticks_per_second)
        if tracker is None:
            rollout = self._wheel.rollout_mm if self._wheel else 0.0
            tracker = WheelSpeed(rollout_mm=rollout, ticks_per_second=ticks_per_second)
            self._wheel_speed[ticks_per_second] = tracker
        return tracker

    def _from_indoor_bike(self, data: IndoorBikeData, now: float) -> list[Reading]:
        """A trainer's own telemetry: already rates, so nothing to differentiate."""
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
        """Subscribe to every characteristic this device offers."""
        client = self._client_factory(self._device.id)
        await client.connect()
        self._client = client
        for characteristic in self.characteristics:
            await client.start_notify(
                characteristic, self._notification_handler(characteristic, sink)
            )

    def _notification_handler(
        self, characteristic: str, sink: ReadingSink
    ) -> Callable[[Any, bytearray], None]:
        """Bind the characteristic we subscribed to, rather than reading it back.

        Bleak hands the callback a characteristic object whose shape is its own
        business; we already know which subscription this is, so we close over it.
        """

        def on_notification(_sender: Any, payload: bytearray) -> None:
            for reading in self.handle(characteristic, bytes(payload)):
                sink(reading)

        return on_notification

    async def write_control_point(self, payload: bytes) -> None:
        """Send a command to the trainer. Only a fitness machine has one."""
        if self._client is None:
            raise RuntimeError("the trainer is not connected")
        await self._client.write_gatt_char(
            FITNESS_MACHINE_CONTROL_POINT, payload, response=True
        )

    def controller(self) -> BleTrainerControl | None:
        """A handle for commanding this device, if it is one that can be."""
        if FITNESS_MACHINE_SERVICE not in self._services:
            return None
        return BleTrainerControl(self.write_control_point)

    async def disconnect(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        await client.disconnect()


def _bleak_client(address: str) -> Any:  # pragma: no cover - needs a radio
    from bleak import BleakClient

    return BleakClient(address)
