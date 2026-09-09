from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from app.core.control import Command, CommandKind
from app.sensors import ant
from app.sensors import ant_protocol as pages
from app.sensors.base import DeviceInfo, Transport
from app.sensors.control_protocol import fec_target_power
from app.sensors.types import Metric, Reading
from app.trainer.wheels import Wheel

WHEEL = Wheel(measured_rollout_mm=2000.0)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class FakeRadio:
    """Stands in for the USB stick, and lets a test push broadcasts."""

    def __init__(self) -> None:
        self.channels: dict[tuple[int, int], Callable[[bytes], None]] = {}
        self.sent: list[bytes] = []

    async def subscribe(
        self,
        device_type: int,
        device_number: int,
        on_broadcast: Callable[[bytes], None],
    ) -> None:
        self.channels[(device_type, device_number)] = on_broadcast

    async def unsubscribe(self, device_type: int, device_number: int) -> None:
        self.channels.pop((device_type, device_number), None)

    async def send(self, device_type: int, device_number: int, payload: bytes) -> None:
        self.sent.append(payload)

    def broadcast(self, device_type: int, device_number: int, payload: bytes) -> None:
        self.channels[(device_type, device_number)](payload)


def page(*values: int) -> bytes:
    return bytes(values)


def uint16(value: int) -> tuple[int, int]:
    return value & 0xFF, (value >> 8) & 0xFF


def sensor(
    device_type: int,
    wheel: Wheel | None = WHEEL,
    radio: FakeRadio | None = None,
    number: int = 42,
) -> tuple[ant.AntSensor, FakeClock]:
    device = ant.device_from_channel(device_type, number)
    assert device is not None
    clock = FakeClock()
    return (
        ant.AntSensor(
            device, device_type, number, wheel=wheel, radio=radio, clock=clock
        ),
        clock,
    )


def test_a_device_id_says_which_profile_and_which_sensor() -> None:
    assert ant.device_id(pages.DEVICE_POWER, 42) == "ant:11:42"


def test_a_known_profile_is_described_for_the_picker() -> None:
    device = ant.device_from_channel(pages.DEVICE_FITNESS_EQUIPMENT, 7)

    assert device is not None
    assert device.transport is Transport.ANT
    assert device.name == "Smart trainer #7"
    assert device.controllable, "fitness equipment is the profile that takes commands"


def test_a_heart_rate_strap_is_not_offered_as_controllable() -> None:
    device = ant.device_from_channel(pages.DEVICE_HEART_RATE, 3)

    assert device is not None
    assert device.metrics == frozenset({Metric.HEART_RATE})
    assert not device.controllable


def test_a_profile_we_do_not_read_is_skipped() -> None:
    assert ant.device_from_channel(3, 1) is None, "a stride sensor is not for us"


def test_heart_rate_becomes_a_reading() -> None:
    device, clock = sensor(pages.DEVICE_HEART_RATE)

    (reading,) = device.handle(page(0, 0, 0, 0, 0, 0, 12, 149))

    assert reading == Reading(
        metric=Metric.HEART_RATE, value=149.0, at=clock.now, source="ant:120:42"
    )


def test_a_strap_with_no_pulse_yet_produces_nothing() -> None:
    device, _ = sensor(pages.DEVICE_HEART_RATE)

    assert device.handle(page(0, 0, 0, 0, 0, 0, 0, 0)) == []


def test_a_power_meter_reports_power_and_cadence_together() -> None:
    device, _ = sensor(pages.DEVICE_POWER)

    readings = device.handle(page(0x10, 5, 50, 88, *uint16(1200), *uint16(243)))

    assert {r.metric: r.value for r in readings} == {
        Metric.POWER: 243.0,
        Metric.CADENCE: 88.0,
    }


def test_a_power_page_we_do_not_read_produces_nothing() -> None:
    device, _ = sensor(pages.DEVICE_POWER)

    assert device.handle(page(0x11, 5, 50, 88, 0, 0, 0, 0)) == []


def test_speed_needs_two_broadcasts_because_it_is_a_difference() -> None:
    device, clock = sensor(pages.DEVICE_SPEED)
    first = device.handle(page(0, 0, 0, 0, *uint16(0), *uint16(0)))

    clock.now += 1.0
    second = device.handle(page(0, 0, 0, 0, *uint16(1024), *uint16(5)))

    assert first == []
    # Five revolutions of a two-metre wheel in one second.
    assert [(r.metric, r.value) for r in second] == [
        (Metric.SPEED, pytest.approx(10.0))
    ]


def test_a_combined_sensor_reports_both_rates() -> None:
    device, clock = sensor(pages.DEVICE_SPEED_CADENCE)
    device.handle(page(*uint16(0), *uint16(0), *uint16(0), *uint16(0)))

    clock.now += 1.0
    readings = device.handle(page(*uint16(1024), *uint16(2), *uint16(1024), *uint16(4)))

    by_metric = {r.metric: r.value for r in readings}
    assert by_metric[Metric.SPEED] == pytest.approx(8.0)
    assert by_metric[Metric.CADENCE] == pytest.approx(120.0)


def test_a_cadence_sensor_reports_only_cadence() -> None:
    device, clock = sensor(pages.DEVICE_CADENCE)
    device.handle(page(0, 0, 0, 0, *uint16(0), *uint16(0)))

    clock.now += 1.0
    readings = device.handle(page(0, 0, 0, 0, *uint16(1024), *uint16(2)))

    assert [r.metric for r in readings] == [Metric.CADENCE]


def test_without_a_wheel_there_is_no_speed_to_report() -> None:
    device, clock = sensor(pages.DEVICE_SPEED, wheel=None)
    device.handle(page(0, 0, 0, 0, *uint16(0), *uint16(0)))

    clock.now += 1.0

    assert device.handle(page(0, 0, 0, 0, *uint16(1024), *uint16(5))) == []


def test_a_trainer_sends_both_of_its_pages_and_both_are_read() -> None:
    """Interleaved pages: one channel gives speed, heart rate, cadence and power."""
    device, _ = sensor(pages.DEVICE_FITNESS_EQUIPMENT)

    general = device.handle(page(0x10, 25, 40, 200, *uint16(8000), 150, 0x30))
    specific = device.handle(page(0x19, 7, 92, *uint16(5000), 0x2C, 0x31, 0x00))

    assert {r.metric for r in general} == {Metric.SPEED, Metric.HEART_RATE}
    assert {r.metric: r.value for r in specific} == {
        Metric.CADENCE: 92.0,
        Metric.POWER: 300.0,
    }


def test_a_trainer_page_we_do_not_read_produces_nothing() -> None:
    device, _ = sensor(pages.DEVICE_FITNESS_EQUIPMENT)

    assert device.handle(page(0x1A, 0, 0, 0, 0, 0, 0, 0)) == []


def test_an_unhandled_profile_produces_nothing() -> None:
    """Nothing crashes if a sensor is built for a profile with no parser."""
    unknown = DeviceInfo(
        id="ant:3:1",
        name="Stride sensor",
        transport=Transport.ANT,
        metrics=frozenset(),
    )
    device = ant.AntSensor(unknown, device_type=3, device_number=1)

    assert device.handle(page(0, 0, 0, 0, 0, 0, 0, 0)) == []


async def test_connecting_opens_a_channel_and_feeds_the_sink() -> None:
    radio = FakeRadio()
    device, _ = sensor(pages.DEVICE_HEART_RATE, radio=radio)
    collected: list[Reading] = []

    await device.connect(collected.append)
    radio.broadcast(pages.DEVICE_HEART_RATE, 42, page(0, 0, 0, 0, 0, 0, 12, 147))

    assert [r.value for r in collected] == [147.0]

    await device.disconnect()
    assert radio.channels == {}


async def test_connecting_twice_opens_one_channel() -> None:
    radio = FakeRadio()
    device, _ = sensor(pages.DEVICE_HEART_RATE, radio=radio)

    await device.connect(lambda reading: None)
    await device.connect(lambda reading: None)

    assert len(radio.channels) == 1


async def test_disconnecting_without_connecting_is_harmless() -> None:
    radio = FakeRadio()
    device, _ = sensor(pages.DEVICE_HEART_RATE, radio=radio)

    await device.disconnect()


async def test_without_a_radio_connecting_does_nothing() -> None:
    """The app can build a sensor before a stick is present."""
    device, _ = sensor(pages.DEVICE_HEART_RATE)

    await device.connect(lambda reading: None)
    await device.disconnect()


def test_only_fitness_equipment_offers_a_way_to_command_it() -> None:
    trainer, _ = sensor(pages.DEVICE_FITNESS_EQUIPMENT)
    strap, _ = sensor(pages.DEVICE_HEART_RATE)

    assert trainer.controller() is not None
    assert strap.controller() is None, "a heart rate strap takes no orders"


async def test_a_control_page_goes_out_on_the_channel() -> None:
    radio = FakeRadio()
    device, _ = sensor(pages.DEVICE_FITNESS_EQUIPMENT, radio=radio)
    control = device.controller()
    assert control is not None

    await control.apply(Command(CommandKind.TARGET_POWER, 240))

    assert radio.sent == [fec_target_power(240)]


async def test_commanding_with_no_stick_says_so() -> None:
    device, _ = sensor(pages.DEVICE_FITNESS_EQUIPMENT)

    with pytest.raises(RuntimeError, match="no ANT\\+ radio"):
        await device.send_page(b"\x31")


# The transport, as the device manager uses it.


def test_a_device_id_splits_back_into_the_channel_it_names() -> None:
    assert ant.parse_device_id("ant:11:42") == (11, 42)


@pytest.mark.parametrize("bad", ["ble:11:42", "ant:11", "ant:power:42"])
def test_an_id_that_is_not_an_ant_device(bad: str) -> None:
    with pytest.raises(ant.NetworkIdError, match="not an ANT"):
        ant.parse_device_id(bad)


async def test_scanning_reports_whatever_answers_on_each_profile() -> None:
    radio = FakeRadio()
    transport = ant.AntTransport(radio, profiles=(pages.DEVICE_HEART_RATE,))

    async def answer() -> None:
        # A strap broadcasts on the wildcard channel while the scan is listening.
        await asyncio.sleep(0)
        radio.broadcast(pages.DEVICE_HEART_RATE, 0, page(0, 0, 0, 0, 0, 0, 1, 140))

    found, _ = await asyncio.gather(transport.scan(0.01), answer())

    assert [device.name for device in found] == ["Heart rate monitor #0"]
    assert radio.channels == {}, "the scan closes what it opened"


async def test_scanning_without_a_stick_finds_nothing() -> None:
    assert await ant.AntTransport().scan(0.01) == []


def test_the_transport_opens_a_device_from_its_id() -> None:
    radio = FakeRadio()
    transport = ant.AntTransport(radio)
    info = ant.device_from_channel(pages.DEVICE_FITNESS_EQUIPMENT, 7)
    assert info is not None

    opened = transport.open(info, WHEEL)

    assert transport.transport is Transport.ANT
    assert transport.control_for(opened) is not None
    assert opened.device.id == "ant:17:7"


def test_only_fitness_equipment_gets_a_controller_from_the_transport() -> None:
    transport = ant.AntTransport(FakeRadio())
    info = ant.device_from_channel(pages.DEVICE_HEART_RATE, 3)
    assert info is not None

    assert transport.control_for(transport.open(info, None)) is None
