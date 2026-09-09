"""Finding devices, connecting them, and keeping them connected.

One place that knows about both radios, so nothing above it does. It scans each
transport, opens the devices the rider chose, points their readings at the hub,
and passes trainer commands to whichever connected device can take them.

The transports sit behind a small protocol rather than being reached for
directly, which is what lets the whole of this be tested against fakes - and what
would let a third transport be added without touching anything here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from app.core.control import Command
from app.sensors.base import DeviceInfo, SensorSource, Transport
from app.sensors.control import NoTrainerControl, TrainerControl
from app.sensors.hub import SensorHub
from app.trainer.wheels import Wheel


class UnknownDeviceError(LookupError):
    """A device that was not found on any transport."""


class DeviceTransport(Protocol):
    """One radio, as the manager needs it."""

    @property
    def transport(self) -> Transport: ...

    async def scan(self, seconds: float) -> list[DeviceInfo]: ...

    def open(self, device: DeviceInfo, wheel: Wheel | None) -> SensorSource: ...

    def control_for(self, source: SensorSource) -> TrainerControl | None:
        """A handle for commanding this device, or None if it takes no orders."""
        ...


@dataclass(frozen=True)
class Connection:
    """A device that is connected, and what can be done with it."""

    info: DeviceInfo
    source: SensorSource
    control: TrainerControl | None = None

    @property
    def controllable(self) -> bool:
        return self.control is not None


@dataclass
class DeviceManager:
    """Owns the connected devices and the readings they produce."""

    hub: SensorHub
    transports: Sequence[DeviceTransport] = ()
    wheel: Wheel | None = None
    connections: dict[str, Connection] = field(default_factory=dict)

    @property
    def connected(self) -> tuple[DeviceInfo, ...]:
        return tuple(item.info for item in self.connections.values())

    @property
    def trainer(self) -> TrainerControl:
        """The connected device that takes commands, or one that ignores them.

        Never None, so a ride never has to ask whether a trainer is there.
        """
        for item in self.connections.values():
            if item.control is not None:
                return item.control
        return NoTrainerControl()

    @property
    def has_trainer_control(self) -> bool:
        return any(item.controllable for item in self.connections.values())

    async def scan(self, seconds: float = 5.0) -> list[DeviceInfo]:
        """Look on every transport at once, and report what answered.

        A radio that is missing or refuses to start is not an error: a rider with
        no ANT+ stick should still be offered what Bluetooth found.
        """
        results = await asyncio.gather(
            *(transport.scan(seconds) for transport in self.transports),
            return_exceptions=True,
        )
        found: list[DeviceInfo] = []
        for result in results:
            if isinstance(result, BaseException):
                continue
            found.extend(result)
        return sorted(found, key=lambda device: (device.name.lower(), device.id))

    def _transport_for(self, device: DeviceInfo) -> DeviceTransport:
        for transport in self.transports:
            if transport.transport is device.transport:
                return transport
        raise UnknownDeviceError(f"nothing here speaks {device.transport}")

    async def connect(self, device: DeviceInfo) -> Connection:
        """Open a device and start feeding its readings into the hub."""
        existing = self.connections.get(device.id)
        if existing is not None:
            return existing
        transport = self._transport_for(device)
        source = transport.open(device, self.wheel)
        await source.connect(self.hub.submit)
        control = transport.control_for(source)
        if control is not None:
            await control.take_control()
        connection = Connection(info=device, source=source, control=control)
        self.connections[device.id] = connection
        return connection

    async def connect_all(self, devices: Iterable[DeviceInfo]) -> list[Connection]:
        return [await self.connect(device) for device in devices]

    async def disconnect(self, device_id: str) -> None:
        """Close a device and forget what it told us.

        Forgetting matters: a strap that is unplugged should stop showing a heart
        rate at once, not hold its last one until it goes stale.
        """
        connection = self.connections.pop(device_id, None)
        if connection is None:
            return
        await connection.source.disconnect()
        self.hub.forget(device_id)

    async def disconnect_all(self) -> None:
        for device_id in list(self.connections):
            await self.disconnect(device_id)

    async def apply(self, command: Command | None) -> None:
        """Pass a trainer command on, if there is one and something to take it."""
        if command is None:
            return
        await self.trainer.apply(command)
