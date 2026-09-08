from __future__ import annotations

import struct
from typing import Any

import pytest

from app.sensors import ble
from app.sensors.base import DeviceInfo, Transport
from app.sensors.types import Metric, Reading
from app.trainer.wheels import Wheel

WHEEL = Wheel(measured_rollout_mm=2000.0)


class FakeClock:
    """A clock the test moves by hand, so rates are arithmetic, not timing."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class FakeClient:
    """Stands in for a BleakClient: records what was subscribed to."""

    def __init__(self, address: str) -> None:
        self.address = address
        self.connected = False
        self.subscriptions: dict[str, Any] = {}

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def start_notify(self, characteristic: str, handler: Any) -> None:
        self.subscriptions[characteristic] = handler

    def notify(self, characteristic: str, payload: bytes) -> None:
        self.subscriptions[characteristic](object(), bytearray(payload))


def sensor(
    services: list[str] | None = None,
    wheel: Wheel | None = WHEEL,
    clock: FakeClock | None = None,
) -> tuple[ble.BleSensor, FakeClock]:
    ticker = clock or FakeClock()
    device = DeviceInfo(
        id="AA:BB:CC", name="Trainer", transport=Transport.BLE, metrics=frozenset()
    )
    return (
        ble.BleSensor(
            device,
            services or [ble.FITNESS_MACHINE_SERVICE],
            wheel=wheel,
            clock=ticker,
        ),
        ticker,
    )


def test_short_uuids_expand_the_way_bleak_reports_them() -> None:
    assert ble.uuid(0x180D) == "0000180d-0000-1000-8000-00805f9b34fb"


def test_a_device_is_described_by_what_it_advertises() -> None:
    device = ble.device_from_advertisement(
        "AA:BB:CC", "KICKR", [ble.FITNESS_MACHINE_SERVICE]
    )

    assert device is not None
    assert device.transport is Transport.BLE
    assert device.controllable, "the fitness machine service also takes commands"
    assert Metric.POWER in device.metrics


def test_a_heart_rate_strap_is_not_offered_as_controllable() -> None:
    device = ble.device_from_advertisement("AA", "Strap", [ble.HEART_RATE_SERVICE])

    assert device is not None
    assert device.metrics == frozenset({Metric.HEART_RATE})
    assert not device.controllable


def test_advertised_uuids_are_matched_case_insensitively() -> None:
    """Platforms disagree about the case of a UUID; a mismatch hides the device."""
    device = ble.device_from_advertisement(
        "AA", "Strap", ["0000180D-0000-1000-8000-00805F9B34FB"]
    )

    assert device is not None


def test_a_device_with_nothing_we_read_is_skipped() -> None:
    assert (
        ble.device_from_advertisement(
            "AA", "Speaker", ["0000110b-0000-1000-8000-00805f9b34fb"]
        )
        is None
    )


def test_an_unnamed_device_still_gets_a_label() -> None:
    device = ble.device_from_advertisement("AA", None, [ble.HEART_RATE_SERVICE])

    assert device is not None
    assert device.name == "Unnamed device"


async def test_scanning_returns_only_usable_devices_in_name_order() -> None:
    async def discover(seconds: float) -> list[tuple[str, str | None, list[str]]]:
        assert seconds == 3.0
        return [
            ("03", "Zeta strap", [ble.HEART_RATE_SERVICE]),
            ("01", "Speaker", ["0000110b-0000-1000-8000-00805f9b34fb"]),
            ("02", "Alpha trainer", [ble.FITNESS_MACHINE_SERVICE]),
        ]

    found = await ble.BleScanner(discover).scan(seconds=3.0)

    assert [device.name for device in found] == ["Alpha trainer", "Zeta strap"]


def test_only_the_advertised_services_are_subscribed_to() -> None:
    device, _ = sensor([ble.HEART_RATE_SERVICE, ble.CYCLING_POWER_SERVICE])

    assert device.characteristics == [
        ble.HEART_RATE_MEASUREMENT,
        ble.CYCLING_POWER_MEASUREMENT,
    ]


def test_an_unknown_service_contributes_no_subscription() -> None:
    device, _ = sensor(["0000110b-0000-1000-8000-00805f9b34fb"])

    assert device.characteristics == []


def test_heart_rate_becomes_a_reading() -> None:
    device, clock = sensor([ble.HEART_RATE_SERVICE])

    (reading,) = device.handle(ble.HEART_RATE_MEASUREMENT, struct.pack("<BB", 0, 151))

    assert reading == Reading(
        metric=Metric.HEART_RATE, value=151.0, at=clock.now, source="AA:BB:CC"
    )


def test_a_notification_we_did_not_ask_for_is_ignored() -> None:
    device, _ = sensor()

    assert device.handle(ble.uuid(0x2A19), b"\x50") == []


def test_power_arrives_immediately_but_speed_needs_two_samples() -> None:
    """Power is instantaneous; speed is a difference between counters."""
    device, clock = sensor([ble.CYCLING_POWER_SERVICE])

    first = device.handle(
        ble.CYCLING_POWER_MEASUREMENT, struct.pack("<HhIH", 0x0010, 200, 100, 0)
    )
    clock.now += 1.0
    second = device.handle(
        ble.CYCLING_POWER_MEASUREMENT, struct.pack("<HhIH", 0x0010, 200, 105, 2048)
    )

    assert [r.metric for r in first] == [Metric.POWER]
    assert [r.metric for r in second] == [Metric.POWER, Metric.SPEED]
    # Five revolutions of a two-metre wheel in one second, timed at 1/2048 s.
    assert second[1].value == pytest.approx(10.0)


def test_speed_and_cadence_produce_both_rates() -> None:
    device, clock = sensor([ble.SPEED_CADENCE_SERVICE])
    payload = struct.pack("<BIHHH", 0x03, 0, 0, 0, 0)
    device.handle(ble.SPEED_CADENCE_MEASUREMENT, payload)

    clock.now += 1.0
    readings = device.handle(
        ble.SPEED_CADENCE_MEASUREMENT, struct.pack("<BIHHH", 0x03, 4, 1024, 2, 1024)
    )

    by_metric = {reading.metric: reading.value for reading in readings}
    assert by_metric[Metric.SPEED] == pytest.approx(8.0)
    assert by_metric[Metric.CADENCE] == pytest.approx(120.0)


def test_the_two_wheel_clocks_are_tracked_separately() -> None:
    """A device reporting through both services must not mix 1/1024 with 1/2048."""
    device, clock = sensor([ble.CYCLING_POWER_SERVICE, ble.SPEED_CADENCE_SERVICE])
    device.handle(ble.CYCLING_POWER_MEASUREMENT, struct.pack("<HhIH", 0x0010, 0, 0, 0))
    device.handle(ble.SPEED_CADENCE_MEASUREMENT, struct.pack("<BIH", 0x01, 0, 0))

    clock.now += 1.0
    from_power = device.handle(
        ble.CYCLING_POWER_MEASUREMENT, struct.pack("<HhIH", 0x0010, 0, 5, 2048)
    )
    from_csc = device.handle(
        ble.SPEED_CADENCE_MEASUREMENT, struct.pack("<BIH", 0x01, 5, 1024)
    )

    assert from_power[1].value == pytest.approx(10.0)
    assert from_csc[0].value == pytest.approx(10.0)


def test_without_a_wheel_there_is_no_speed_to_report() -> None:
    device, clock = sensor([ble.SPEED_CADENCE_SERVICE], wheel=None)
    device.handle(ble.SPEED_CADENCE_MEASUREMENT, struct.pack("<BIH", 0x01, 0, 0))

    clock.now += 1.0
    readings = device.handle(
        ble.SPEED_CADENCE_MEASUREMENT, struct.pack("<BIH", 0x01, 5, 1024)
    )

    assert readings == []


def test_indoor_bike_data_needs_no_differentiating() -> None:
    """A trainer sends rates already, so one notification is enough."""
    device, _ = sensor()

    readings = device.handle(
        ble.INDOOR_BIKE_DATA, struct.pack("<HHHh", 0x0044, 3600, 180, 250)
    )

    by_metric = {reading.metric: reading.value for reading in readings}
    assert by_metric[Metric.SPEED] == pytest.approx(10.0)
    assert by_metric[Metric.CADENCE] == pytest.approx(90.0)
    assert by_metric[Metric.POWER] == 250.0


async def test_connecting_subscribes_and_feeds_the_sink() -> None:
    clients: list[FakeClient] = []

    def factory(address: str) -> FakeClient:
        client = FakeClient(address)
        clients.append(client)
        return client

    device = ble.BleSensor(
        DeviceInfo(
            id="AA:BB:CC",
            name="Strap",
            transport=Transport.BLE,
            metrics=frozenset({Metric.HEART_RATE}),
        ),
        [ble.HEART_RATE_SERVICE],
        client_factory=factory,
    )
    collected: list[Reading] = []

    await device.connect(collected.append)
    (client,) = clients
    client.notify(ble.HEART_RATE_MEASUREMENT, struct.pack("<BB", 0, 143))

    assert client.connected
    assert list(client.subscriptions) == [ble.HEART_RATE_MEASUREMENT]
    assert [reading.value for reading in collected] == [143.0]

    await device.disconnect()
    assert not client.connected


async def test_disconnecting_without_connecting_is_harmless() -> None:
    device, _ = sensor()

    await device.disconnect()
