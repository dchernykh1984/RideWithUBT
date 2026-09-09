"""The relay: the smallest thing that lets people ride together.

It receives a rider's datagram and copies it to everyone else in the same world.
That is all of it. It keeps no history, writes no file, has no account and no
database, and forgets a rider seconds after they stop speaking. Run it on a
laptop on the club's network, or on a box someone hosts; this project runs none
and never will, which is why joining a group ride still leaves the application
offline-first in the sense that matters - nothing of yours passes through
anybody's server on the way to your training.

Deliberately not hardened for the open internet. A relay forwards to whoever
has recently spoken, so a forged source address could aim other riders' traffic
at a third party. On a home or club network, or across a VPN, that is nobody's
problem. Exposed to the world it is a small one, and the honest answer is to say
so here rather than to imply a robustness this does not have.
"""

from __future__ import annotations

import socket
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app.core.presence import FORGET_AFTER_S, PresenceError, RiderState

#: Enough for a club, small enough that a room cannot be turned into a megaphone.
MAX_RIDERS = 64
MAX_DATAGRAM = 2048


@dataclass(frozen=True)
class Member:
    """One rider in the room, as the relay needs to know them."""

    address: tuple[str, int]
    rider_id: str
    world_id: str
    heard_at: float


@dataclass
class Relay:
    """Who is in the room, and where each datagram should go next."""

    forget_after_s: float = FORGET_AFTER_S
    max_riders: int = MAX_RIDERS
    members: dict[tuple[str, int], Member] = field(default_factory=dict)

    def route(
        self, datagram: bytes, sender: tuple[str, int], now: float
    ) -> tuple[tuple[str, int], ...]:
        """Take one datagram in; say where it goes.

        A datagram that is not a rider goes nowhere. That check is what keeps
        the relay from being a general-purpose way of sending strangers bytes.
        """
        try:
            state = RiderState.decode(datagram)
        except PresenceError:
            return ()
        self.forget_quiet(now)
        if sender not in self.members and len(self.members) >= self.max_riders:
            return ()  # a full room, rather than an unbounded one
        self.members[sender] = Member(sender, state.id, state.world_id, now)
        return tuple(
            member.address
            for member in self.members.values()
            if member.address != sender and member.world_id == state.world_id
        )

    def forget_quiet(self, now: float) -> None:
        self.members = {
            address: member
            for address, member in self.members.items()
            if now - member.heard_at <= self.forget_after_s
        }

    @property
    def riders(self) -> int:
        return len(self.members)


#: Every interface, because a relay nobody else can reach is not a relay. This
#: is the one knob that decides who can find the room, so it is an argument the
#: caller can narrow to a single address, not a constant.
ALL_INTERFACES = "0.0.0.0"  # noqa: S104 - the point of a room is being reachable


def serve(
    host: str = ALL_INTERFACES,
    port: int = 51820,
    *,
    announce: Callable[[str], None] = print,
    stop: Callable[[], bool] = lambda: False,
    relay: Relay | None = None,
) -> None:
    """Run a room until interrupted. One socket, one loop, no state on disk."""
    room = relay or Relay()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
        sock.settimeout(0.5)
        announce(f"room open on {host}:{port} - ctrl-c to close it")
        riders = -1
        while not stop():
            try:
                datagram, sender = sock.recvfrom(MAX_DATAGRAM)
            except TimeoutError:
                room.forget_quiet(time.monotonic())
                continue
            except OSError:  # pragma: no cover - the socket going away under us
                break
            for address in room.route(datagram, sender, time.monotonic()):
                try:
                    sock.sendto(datagram, address)
                except OSError:  # pragma: no cover - one rider's route breaking
                    continue
            if room.riders != riders:
                riders = room.riders
                announce(f"{riders} rider(s) in the room")
    except KeyboardInterrupt:  # pragma: no cover - how a person stops a server
        announce("room closed")
    finally:
        sock.close()
