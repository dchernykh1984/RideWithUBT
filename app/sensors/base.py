"""The contract every transport implements.

A transport's whole job is to turn whatever its radio gives it into `Reading`s
and push them at a sink. It owns connecting, reconnecting and its own protocol
quirks; it owns nothing about the ride.

Keeping this a Protocol rather than a base class is deliberate: the Bluetooth and
ANT+ transports have nothing in common to inherit, and a fake in a test should
not have to import either of them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.sensors.types import Metric, Reading

ReadingSink = Callable[[Reading], None]


class Transport(StrEnum):
    BLE = "ble"
    ANT = "ant"
    SIMULATED = "simulated"


@dataclass(frozen=True)
class DeviceInfo:
    """A device the app can offer to connect to.

    ``metrics`` is what the device says it provides. It is a claim made at
    discovery time, so the hub still treats readings that never arrive as absent
    rather than as zero.
    """

    id: str
    name: str
    transport: Transport
    metrics: frozenset[Metric]
    controllable: bool = False

    @property
    def label(self) -> str:
        return f"{self.name} ({self.transport})"


class SensorSource(Protocol):
    """A connected device, pushing readings until it is stopped."""

    @property
    def device(self) -> DeviceInfo: ...

    async def connect(self, sink: ReadingSink) -> None:
        """Start delivering readings to ``sink``. Returns once subscribed."""
        ...

    async def disconnect(self) -> None:
        """Stop delivering readings and release the radio."""
        ...


class Scanner(Protocol):
    """Finds devices on one transport."""

    async def scan(self, seconds: float) -> list[DeviceInfo]: ...
