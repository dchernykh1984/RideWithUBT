"""Sending a command to a trainer, over whichever radio it is on.

`app/core/control.py` decides what to ask for; `control_protocol.py` turns that
into bytes; this puts the bytes on the wire. Each implementation is given the one
function it needs to write, so both can be tested against a list.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from app.core.control import Command, CommandKind
from app.sensors.control_protocol import (
    ControlError,
    fec_target_power,
    fec_track_resistance,
    ftms_request_control,
    ftms_start,
    ftms_target_power,
)
from app.sensors.control_protocol import ftms_simulation as ftms_simulation_bytes

Writer = Callable[[bytes], Awaitable[None]]


class TrainerControl(Protocol):
    """A trainer that can be told what to do."""

    async def take_control(self) -> None:
        """Ask for command of the trainer, and start it. Called once, on connect."""
        ...

    async def apply(self, command: Command) -> None: ...


class BleTrainerControl:
    """Commands over the Fitness Machine Control Point."""

    def __init__(self, write: Writer) -> None:
        self._write = write

    async def take_control(self) -> None:
        # A fitness machine ignores commands until control is requested, and
        # sits in a paused state until it is started - both are easy to leave
        # out, and leaving either out looks exactly like a trainer that will not
        # respond to ERG.
        await self._write(ftms_request_control())
        await self._write(ftms_start())

    async def apply(self, command: Command) -> None:
        if command.kind is CommandKind.TARGET_POWER:
            await self._write(ftms_target_power(command.watts))
            return
        await self._write(ftms_simulation_bytes(command.grade_percent))


class AntTrainerControl:
    """Commands as FE-C control pages."""

    def __init__(self, write: Writer) -> None:
        self._write = write

    async def take_control(self) -> None:
        """FE-C has nothing to request: a page sent is a command given."""
        return

    async def apply(self, command: Command) -> None:
        if command.kind is CommandKind.TARGET_POWER:
            await self._write(fec_target_power(command.watts))
            return
        await self._write(fec_track_resistance(command.grade_percent))


class NoTrainerControl:
    """A stand-in for a trainer that cannot be commanded.

    Every classic trainer, and every smart one before it has connected. Having
    one of these means the ride never has to ask whether control exists.
    """

    async def take_control(self) -> None:
        return

    async def apply(self, command: Command) -> None:
        return


__all__ = [
    "AntTrainerControl",
    "BleTrainerControl",
    "ControlError",
    "NoTrainerControl",
    "TrainerControl",
    "Writer",
]
