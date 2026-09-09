"""What one rider tells another, and nothing more.

Riding with other people needs a shape on the wire, and this is it: where a
rider is, how fast, how hard, on which track. That list is the whole of it. No
account, no history, no identity beyond a name the rider chose and an id their
own machine made up - because the point of a shared road is seeing someone
ahead of you, and nothing else about them is needed to draw them there.

The format is deliberately dull: one JSON object per datagram, a version number
in front, and every field a number or a short string. It is documented in
`docs/protocol.md` so that anyone can write the relay, and this project can go
on running none.

There is no socket in this module. Encoding a rider is not networking, and
keeping it separate is what lets the format be tested exhaustively - including
all the ways a stranger's datagram can be malformed, which is the part that
matters, because everything decoded here came off a network from someone this
application has never met.
"""

from __future__ import annotations

import json
import math
import secrets
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.core.companions import Companion

#: Bumped when the shape changes in a way an older client cannot read. A client
#: ignores anything it does not recognise rather than guessing.
PROTOCOL_VERSION = 1

#: How often a rider says where they are. Twenty times a second is a waste of a
#: network and five times a second is enough to draw someone smoothly.
UPDATE_INTERVAL_S = 0.2

#: Silence long enough to mean gone. Short enough that a rider who quits does
#: not linger on the road; long enough to ride through a handful of lost
#: datagrams without anyone flickering.
FORGET_AFTER_S = 5.0

#: A name is drawn above a rider's head, so it is short, and it is text - a
#: stranger does not get to send control characters into someone else's window.
MAX_NAME = 24
MAX_ID = 64

#: Nobody is a kilometre underground or doing the speed of sound. These are not
#: physics, they are a bound on what a hostile datagram can do to the scene.
MAX_COORDINATE_M = 1_000_000.0
MAX_SPEED_MS = 100.0
MAX_DISTANCE_M = 10_000_000.0
MAX_POWER_W = 3000.0
MAX_CADENCE_RPM = 300.0


def anonymous_id() -> str:
    """An id for a rider, made up on their machine and meaning nothing.

    Other riders need to tell one datagram stream from another, and that is the
    entire job. It is not derived from the machine, the account or the person,
    because none of those are anybody else's business.
    """
    return secrets.token_hex(8)


class PresenceError(ValueError):
    """A datagram that is not a rider. Dropped, never raised at the rider."""


@dataclass(frozen=True)
class RiderState:
    """One rider, as everyone else on the road is told about them."""

    id: str
    name: str
    world_id: str
    x: float
    y: float
    z: float
    heading_rad: float
    distance_m: float
    speed_ms: float
    cadence_rpm: float | None = None
    power_w: float | None = None

    def encode(self) -> bytes:
        """The rider as one datagram: short keys, because this goes out often."""
        payload: dict[str, Any] = {
            "v": PROTOCOL_VERSION,
            "id": self.id,
            "name": self.name,
            "world": self.world_id,
            "x": round(self.x, 2),
            "y": round(self.y, 2),
            "z": round(self.z, 2),
            "heading": round(self.heading_rad, 4),
            "distance": round(self.distance_m, 1),
            "speed": round(self.speed_ms, 3),
        }
        if self.cadence_rpm is not None:
            payload["cadence"] = round(self.cadence_rpm, 1)
        if self.power_w is not None:
            payload["power"] = round(self.power_w, 1)
        return json.dumps(payload, separators=(",", ":")).encode("utf-8")

    @classmethod
    def decode(cls, datagram: bytes) -> RiderState:
        """A rider out of a datagram, or `PresenceError` if it is not one.

        Everything reaching here was written by a stranger, so nothing is
        assumed: not the encoding, not the shape, not the types, and not that
        the numbers are numbers a world can contain.
        """
        try:
            payload = json.loads(datagram.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PresenceError(f"not a datagram this speaks: {error}") from None
        if not isinstance(payload, dict):
            raise PresenceError("a rider is an object, not a bare value")
        if payload.get("v") != PROTOCOL_VERSION:
            raise PresenceError(
                f"protocol {payload.get('v')!r}, not {PROTOCOL_VERSION}"
            )
        return cls(
            id=_text(payload, "id", MAX_ID, required=True),
            name=_text(payload, "name", MAX_NAME),
            world_id=_text(payload, "world", MAX_ID, required=True),
            x=_number(payload, "x", MAX_COORDINATE_M),
            y=_number(payload, "y", MAX_COORDINATE_M),
            z=_number(payload, "z", MAX_COORDINATE_M),
            heading_rad=_number(payload, "heading", 2 * math.pi + 1.0),
            distance_m=_number(payload, "distance", MAX_DISTANCE_M),
            speed_ms=_number(payload, "speed", MAX_SPEED_MS),
            cadence_rpm=_optional(payload, "cadence", MAX_CADENCE_RPM),
            power_w=_optional(payload, "power", MAX_POWER_W),
        )

    def as_companion(self) -> Companion:
        """The rider as the renderer wants them, knowing nothing of wires."""
        from app.world.network import Point

        return Companion(
            id=self.id,
            name=self.name or self.id[:MAX_NAME],
            point=Point(self.x, self.y, self.z),
            heading_rad=self.heading_rad,
            distance_m=self.distance_m,
            speed_ms=self.speed_ms,
            power_w=self.power_w,
        )


@dataclass
class Roster:
    """Who is on the road, and when each of them was last heard from.

    A rider who goes quiet is forgotten rather than left standing on the track:
    a network drops things, and a ghost at the last known corner is worse than
    an empty road.
    """

    world_id: str = ""
    forget_after_s: float = FORGET_AFTER_S
    ignore: str = ""
    heard: dict[str, tuple[float, RiderState]] = field(default_factory=dict)

    def hear(self, state: RiderState, now: float) -> bool:
        """Take in one rider. False if they are not someone to draw."""
        if state.id == self.ignore:
            return False  # our own datagram, come back off a relay
        if self.world_id and state.world_id != self.world_id:
            return False  # riding somewhere else entirely
        self.heard[state.id] = (now, state)
        return True

    def forget_quiet(self, now: float) -> None:
        self.heard = {
            rider: seen
            for rider, seen in self.heard.items()
            if now - seen[0] <= self.forget_after_s
        }

    def companions(self) -> Sequence[Companion]:
        return tuple(state.as_companion() for _, state in self.heard.values())


def _text(
    payload: dict[str, Any], key: str, limit: int, *, required: bool = False
) -> str:
    raw = payload.get(key)
    if raw is None and not required:
        return ""
    if not isinstance(raw, str):
        raise PresenceError(f"{key} should be text, not {type(raw).__name__}")
    # Control characters would go straight into a window as whatever the font
    # makes of them; a name is a name.
    clean = "".join(character for character in raw if character.isprintable())
    if required and not clean:
        raise PresenceError(f"{key} is required")
    return clean[:limit]


def _number(payload: dict[str, Any], key: str, limit: float) -> float:
    raw = payload.get(key)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise PresenceError(f"{key} should be a number, not {type(raw).__name__}")
    value = float(raw)
    if not math.isfinite(value):
        raise PresenceError(f"{key} is {value}")
    if abs(value) > limit:
        raise PresenceError(f"{key} is {value}, which is off the map")
    return value


def _optional(payload: dict[str, Any], key: str, limit: float) -> float | None:
    if payload.get(key) is None:
        return None
    return _number(payload, key, limit)
