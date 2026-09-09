from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.core.control import Command, CommandKind
from app.sensors.base import DeviceInfo, ReadingSink, Transport
from app.sensors.control import NoTrainerControl
from app.sensors.hub import SensorHub
from app.sensors.manager import DeviceManager, DeviceTransport, UnknownDeviceError
from app.sensors.types import Metric, Reading


def device(
    name: str, transport: Transport = Transport.BLE, controllable: bool = False
) -> DeviceInfo:
    return DeviceInfo(
        id=f"{transport}:{name}",
        name=name,
        transport=transport,
        metrics=frozenset({Metric.POWER}),
        controllable=controllable,
    )


class FakeSource:
    def __init__(self, info: DeviceInfo) -> None:
        self.info = info
        self.sink: ReadingSink | None = None
        self.connected = False

    @property
    def device(self) -> DeviceInfo:
        return self.info

    async def connect(self, sink: ReadingSink) -> None:
        self.sink = sink
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    def report(self, value: float, at: float) -> None:
        assert self.sink is not None
        self.sink(Reading(Metric.POWER, value, at=at, source=self.info.id))


class FakeControl:
    def __init__(self) -> None:
        self.taken = False
        self.applied: list[Command] = []

    async def take_control(self) -> None:
        self.taken = True

    async def apply(self, command: Command) -> None:
        self.applied.append(command)


@dataclass
class FakeTransport:
    kind: Transport = Transport.BLE
    found: list[DeviceInfo] = field(default_factory=list)
    opened: list[FakeSource] = field(default_factory=list)
    controls: dict[str, FakeControl] = field(default_factory=dict)
    fail_scan: bool = False

    @property
    def transport(self) -> Transport:
        return self.kind

    async def scan(self, seconds: float) -> list[DeviceInfo]:
        if self.fail_scan:
            raise RuntimeError("no radio")
        return list(self.found)

    def open(self, info: DeviceInfo, wheel: object) -> FakeSource:
        source = FakeSource(info)
        self.opened.append(source)
        return source

    def control_for(self, source: object) -> FakeControl | None:
        assert isinstance(source, FakeSource)
        if not source.info.controllable:
            return None
        control = FakeControl()
        self.controls[source.info.id] = control
        return control


def manager(*transports: DeviceTransport) -> tuple[DeviceManager, SensorHub]:
    hub = SensorHub()
    return DeviceManager(hub=hub, transports=transports), hub


async def test_scanning_asks_every_radio() -> None:
    ble = FakeTransport(Transport.BLE, [device("Strap")])
    ant = FakeTransport(Transport.ANT, [device("Meter", Transport.ANT)])
    devices, _ = manager(ble, ant)

    found = await devices.scan(seconds=0.1)

    assert [item.name for item in found] == ["Meter", "Strap"], "sorted by name"


async def test_a_radio_that_is_not_there_does_not_stop_the_other() -> None:
    """A rider with no ANT+ stick should still be offered what Bluetooth found."""
    ble = FakeTransport(Transport.BLE, [device("Strap")])
    ant = FakeTransport(Transport.ANT, fail_scan=True)
    devices, _ = manager(ble, ant)

    found = await devices.scan(seconds=0.1)

    assert [item.name for item in found] == ["Strap"]


async def test_scanning_with_no_radios_finds_nothing() -> None:
    devices, _ = manager()

    assert await devices.scan(seconds=0.1) == []


async def test_connecting_points_the_readings_at_the_hub() -> None:
    strap = device("Strap")
    transport = FakeTransport(Transport.BLE, [strap])
    devices, hub = manager(transport)

    await devices.connect(strap)
    transport.opened[0].report(212.0, at=10.0)

    snapshot = hub.snapshot(now=10.0)
    assert snapshot.power is not None
    assert snapshot.power.value == 212.0
    assert devices.connected == (strap,)


async def test_connecting_twice_opens_one_device() -> None:
    strap = device("Strap")
    transport = FakeTransport(Transport.BLE, [strap])
    devices, _ = manager(transport)

    first = await devices.connect(strap)
    second = await devices.connect(strap)

    assert first is second
    assert len(transport.opened) == 1


async def test_a_device_on_a_transport_that_is_not_here() -> None:
    devices, _ = manager(FakeTransport(Transport.BLE))

    with pytest.raises(UnknownDeviceError, match="speaks ant"):
        await devices.connect(device("Meter", Transport.ANT))


async def test_disconnecting_forgets_what_the_device_said() -> None:
    """An unplugged strap should stop showing a heart rate at once."""
    strap = device("Strap")
    transport = FakeTransport(Transport.BLE, [strap])
    devices, hub = manager(transport)
    await devices.connect(strap)
    transport.opened[0].report(212.0, at=10.0)

    await devices.disconnect(strap.id)

    assert hub.snapshot(now=10.0).power is None
    assert not transport.opened[0].connected
    assert devices.connected == ()


async def test_disconnecting_something_that_is_not_connected() -> None:
    devices, _ = manager(FakeTransport())

    await devices.disconnect("nothing")


async def test_disconnecting_everything() -> None:
    one, two = device("One"), device("Two")
    transport = FakeTransport(Transport.BLE, [one, two])
    devices, _ = manager(transport)
    await devices.connect_all([one, two])

    await devices.disconnect_all()

    assert devices.connected == ()
    assert all(not source.connected for source in transport.opened)


async def test_a_trainer_is_asked_for_control_when_it_connects() -> None:
    trainer = device("Trainer", controllable=True)
    transport = FakeTransport(Transport.BLE, [trainer])
    devices, _ = manager(transport)

    connection = await devices.connect(trainer)

    assert connection.controllable
    assert devices.has_trainer_control
    assert transport.controls[trainer.id].taken


async def test_commands_reach_the_device_that_can_take_them() -> None:
    strap, trainer = device("Strap"), device("Trainer", controllable=True)
    transport = FakeTransport(Transport.BLE, [strap, trainer])
    devices, _ = manager(transport)
    await devices.connect_all([strap, trainer])

    await devices.apply(Command(CommandKind.TARGET_POWER, 250))

    assert transport.controls[trainer.id].applied == [
        Command(CommandKind.TARGET_POWER, 250)
    ]


async def test_with_no_trainer_a_command_goes_nowhere_and_nothing_breaks() -> None:
    """So a ride never has to ask whether a trainer is there."""
    strap = device("Strap")
    devices, _ = manager(FakeTransport(Transport.BLE, [strap]))
    await devices.connect(strap)

    assert isinstance(devices.trainer, NoTrainerControl)
    assert not devices.has_trainer_control
    await devices.apply(Command(CommandKind.TARGET_POWER, 250))


async def test_nothing_to_send_is_not_an_error() -> None:
    devices, _ = manager(FakeTransport())

    await devices.apply(None)


class Refusing:
    """A device that will not open, the way a flat battery will not."""

    def __init__(self, info: DeviceInfo) -> None:
        self.info = info
        self.disconnected = False

    @property
    def device(self) -> DeviceInfo:
        return self.info

    async def connect(self, sink: ReadingSink) -> None:
        raise RuntimeError("no answer")

    async def disconnect(self) -> None:
        self.disconnected = True


@dataclass
class RefusingTransport:
    """A radio whose devices all refuse to open. Not a FakeTransport subclass:
    they differ in exactly the thing being tested."""

    kind: Transport = Transport.BLE
    found: list[DeviceInfo] = field(default_factory=list)
    opened: list[Refusing] = field(default_factory=list)

    @property
    def transport(self) -> Transport:
        return self.kind

    async def scan(self, seconds: float) -> list[DeviceInfo]:
        return list(self.found)

    def open(self, info: DeviceInfo, wheel: object) -> Refusing:
        source = Refusing(info)
        self.opened.append(source)
        return source

    def control_for(self, source: object) -> None:
        return None


async def test_a_device_that_fails_to_open_is_closed_again() -> None:
    """Half a connection keeps feeding the hub from something nobody can close."""
    strap = device("Strap")
    transport = RefusingTransport(Transport.BLE, [strap])
    devices, _ = manager(transport)

    with pytest.raises(RuntimeError, match="no answer"):
        await devices.connect(strap)

    assert transport.opened[0].disconnected
    assert devices.connected == ()


async def test_one_device_that_will_not_connect_does_not_cost_the_others() -> None:
    """A strap with a flat battery must not stop the trainer from working."""
    good, bad = device("Trainer", controllable=True), device("Strap")
    working = FakeTransport(Transport.BLE, [good])
    broken = RefusingTransport(Transport.ANT, [bad])
    hub = SensorHub()
    devices = DeviceManager(hub=hub, transports=(working, broken))
    bad = device("Strap", transport=Transport.ANT)

    opened = await devices.connect_all([good, bad])

    assert [item.info.name for item in opened] == ["Trainer"]
    assert devices.has_trainer_control
    assert "no answer" in devices.failures[bad.id]


async def test_connecting_after_a_failure_clears_it() -> None:
    strap = device("Strap")
    devices, _ = manager(FakeTransport(Transport.BLE, [strap]))
    devices.failures[strap.id] = "no answer"

    await devices.connect(strap)

    assert strap.id not in devices.failures
