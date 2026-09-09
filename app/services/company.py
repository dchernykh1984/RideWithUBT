"""Riding with other people, over a relay this project does not run.

The brief for this application is offline-first, and joining a group ride is the
one place that could quietly stop being true. So it does not: there is no
account, no sign-up and no RideWithUBT server. A rider joins by naming a host -
a laptop on the same network, a teammate's box, whatever a club sets up - and
that host does one thing, which is copying datagrams to everyone else in the
room. It stores nothing and it is not this project's.

What goes on the wire is `app/core/presence.py` and nothing else: position,
heading, speed, distance, cadence, power, and a name the rider typed. That is
the whole of what riding together needs.

Everything here fails soft. An unreachable host, a firewall, a relay that goes
away mid-ride: the ride carries on, alone, because a training session must not
end because a network did.
"""

from __future__ import annotations

import socket
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.core.companions import Companion
from app.core.presence import (
    UPDATE_INTERVAL_S,
    PresenceError,
    RiderState,
    Roster,
)

#: The port a relay listens on when nobody says otherwise. Unregistered, high,
#: and easy to remember next to the year this was written.
DEFAULT_PORT = 51820

#: A datagram is one rider. This is several times the size one needs, and small
#: enough that nothing can be posted through the socket to fill memory.
MAX_DATAGRAM = 2048

#: How many datagrams to take in one pass of the ride loop. A burst is drained
#: over the next few frames rather than in one, so a flood cannot stall a frame.
MAX_PER_TICK = 64


def parse_host(text: str, default_port: int = DEFAULT_PORT) -> tuple[str, int]:
    """`host`, `host:port`, or an IPv6 address in brackets, as a rider types it."""
    stripped = text.strip()
    if not stripped:
        raise ValueError("no host to ride with")
    if stripped.startswith("["):  # [::1]:51820
        closing = stripped.find("]")
        if closing < 0:
            raise ValueError(f"{text!r} opens a bracket it never closes")
        host, rest = stripped[1:closing], stripped[closing + 1 :]
        given_port = rest.startswith(":")
        port_text = rest[1:] if given_port else ""
    elif stripped.count(":") == 1:
        host, _, port_text = stripped.partition(":")
        given_port = True
    else:  # a bare IPv6 address has several colons and no port
        host, port_text, given_port = stripped, "", False
    if not host:
        raise ValueError(f"{text!r} has no host in it")
    if not given_port:
        return host, default_port
    # A colon with nothing after it is a port somebody meant to type, so it is
    # a mistake to correct rather than a default to apply quietly.
    if not port_text:
        raise ValueError(f"{text!r} ends in a colon with no port after it")
    try:
        port = int(port_text)
    except ValueError:
        raise ValueError(f"{port_text!r} is not a port number") from None
    if not 1 <= port <= 65535:
        raise ValueError(f"{port} is not a port number")
    return host, port


@dataclass
class NetworkCompany:
    """Other riders, heard from a relay, drawn like anybody else.

    This is a `CompanionSource`: the renderer and the ride do not know or care
    that these riders came from a network rather than from the pace-partner
    machinery next door.
    """

    address: tuple[str, int]
    me: RiderState
    roster: Roster = field(default_factory=Roster)
    interval_s: float = UPDATE_INTERVAL_S
    sock: socket.socket | None = None
    clock: object = time.monotonic
    #: Set once the socket has failed. The ride goes on; it just goes on alone.
    lost: str = ""
    _next_send: float = 0.0

    def __post_init__(self) -> None:
        self.roster.ignore = self.me.id
        self.roster.world_id = self.roster.world_id or self.me.world_id
        if self.sock is None:
            self.sock = self._open()

    def _open(self) -> socket.socket | None:
        try:
            family = socket.getaddrinfo(
                self.address[0], self.address[1], type=socket.SOCK_DGRAM
            )[0][0]
            sock = socket.socket(family, socket.SOCK_DGRAM)
            sock.setblocking(False)
            return sock
        except OSError as error:  # a name that does not resolve, mostly
            self.lost = f"cannot reach {self.address[0]}: {error}"
            return None

    # What the ride asks of it.

    def report(self, me: RiderState) -> None:
        """Say where we are, at most every `interval_s`."""
        self.me = me

    def advance(self, seconds: float) -> None:
        """One step: tell them where we are, hear where they are."""
        now = float(self.clock())  # type: ignore[operator]
        self._send(now)
        self._receive(now)
        self.roster.forget_quiet(now)

    def companions(self) -> Sequence[Companion]:
        return self.roster.companions()

    def close(self) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    # The wire.

    def _send(self, now: float) -> None:
        if self.sock is None or now < self._next_send:
            return
        self._next_send = now + self.interval_s
        try:
            self.sock.sendto(self.me.encode(), self.address)
        except OSError as error:
            # Not fatal and not final: a relay can come back, and a rider who
            # loses one mid-interval should not be dropped off their own ride.
            self.lost = f"cannot reach {self.address[0]}: {error}"

    def _receive(self, now: float) -> None:
        if self.sock is None:
            return
        for _ in range(MAX_PER_TICK):
            try:
                datagram, _sender = self.sock.recvfrom(MAX_DATAGRAM)
            except BlockingIOError:
                return  # nothing waiting, which is the usual case
            except OSError:
                return  # including the "connection refused" a relay's absence gives
            try:
                self.roster.hear(RiderState.decode(datagram), now)
            except PresenceError:
                continue  # somebody else's traffic, or somebody being difficult
