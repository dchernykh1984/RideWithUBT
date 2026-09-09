"""Riding together, over real sockets on the loopback interface.

A test that mocks the socket proves the mock. These open two UDP sockets and a
relay and pass actual datagrams between them, which is the only way to find out
whether the thing works.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest

from app.core.presence import FORGET_AFTER_S, RiderState
from app.services.company import DEFAULT_PORT, NetworkCompany, parse_host
from app.services.room import Relay, serve


def rider(identifier: str = "me", world: str = "sokol", **changes: float) -> RiderState:
    fields: dict[str, float] = {
        "x": 10.0,
        "y": 20.0,
        "z": 645.0,
        "heading_rad": 0.5,
        "distance_m": 100.0,
        "speed_ms": 10.0,
    }
    fields.update(changes)
    return RiderState(id=identifier, name=identifier, world_id=world, **fields)


# Reading a host as a rider writes it.


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("192.168.1.20", ("192.168.1.20", DEFAULT_PORT)),
        ("192.168.1.20:9000", ("192.168.1.20", 9000)),
        ("  laptop.local  ", ("laptop.local", DEFAULT_PORT)),
        ("laptop.local:1", ("laptop.local", 1)),
        ("[::1]:9000", ("::1", 9000)),
        ("[fe80::1]", ("fe80::1", DEFAULT_PORT)),
        ("::1", ("::1", DEFAULT_PORT)),
    ],
)
def test_a_host_is_read_the_way_it_is_typed(
    text: str, expected: tuple[str, int]
) -> None:
    assert parse_host(text) == expected


@pytest.mark.parametrize(
    "text", ["", "   ", ":9000", "host:", "host:port", "host:0", "host:70000", "[::1"]
)
def test_a_host_that_is_not_one_says_so(text: str) -> None:
    with pytest.raises(ValueError):
        parse_host(text)


# The relay.


def test_the_relay_copies_a_rider_to_everybody_else() -> None:
    relay = Relay()
    relay.route(rider("one").encode(), ("10.0.0.1", 1000), now=0.0)
    relay.route(rider("two").encode(), ("10.0.0.2", 2000), now=0.0)

    going_to = relay.route(rider("three").encode(), ("10.0.0.3", 3000), now=0.0)

    assert set(going_to) == {("10.0.0.1", 1000), ("10.0.0.2", 2000)}


def test_a_rider_is_not_sent_their_own_datagram() -> None:
    relay = Relay()
    relay.route(rider("one").encode(), ("10.0.0.1", 1000), now=0.0)

    assert relay.route(rider("one").encode(), ("10.0.0.1", 1000), now=0.1) == ()


def test_riders_in_different_worlds_do_not_hear_each_other() -> None:
    relay = Relay()
    relay.route(rider("one", world="alps").encode(), ("10.0.0.1", 1000), now=0.0)

    going_to = relay.route(rider("two").encode(), ("10.0.0.2", 2000), now=0.0)

    assert going_to == ()


def test_the_relay_forwards_nothing_it_cannot_read() -> None:
    """It is a room for riders, not a way to send strangers arbitrary bytes."""
    relay = Relay()
    relay.route(rider("one").encode(), ("10.0.0.1", 1000), now=0.0)

    assert relay.route(b"anything at all", ("10.0.0.9", 9000), now=0.0) == ()
    assert relay.riders == 1, "junk does not join the room either"


def test_a_rider_who_leaves_is_forgotten() -> None:
    relay = Relay()
    relay.route(rider("one").encode(), ("10.0.0.1", 1000), now=0.0)

    later = FORGET_AFTER_S + 1.0
    going_to = relay.route(rider("two").encode(), ("10.0.0.2", 2000), now=later)

    assert going_to == ()
    assert relay.riders == 1


def test_a_full_room_stays_full_rather_than_growing() -> None:
    relay = Relay(max_riders=3)
    for number in range(5):
        relay.route(rider(f"r{number}").encode(), (f"10.0.0.{number}", 1000), now=0.0)

    assert relay.riders == 3


def test_a_rider_already_in_a_full_room_is_still_heard() -> None:
    relay = Relay(max_riders=2)
    relay.route(rider("one").encode(), ("10.0.0.1", 1000), now=0.0)
    relay.route(rider("two").encode(), ("10.0.0.2", 2000), now=0.0)

    going_to = relay.route(rider("one").encode(), ("10.0.0.1", 1000), now=0.1)

    assert going_to == (("10.0.0.2", 2000),)


# Two riders, one relay, real datagrams.


class Room:
    """A relay on loopback, running for the length of a test."""

    def __init__(self) -> None:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.bind(("127.0.0.1", 0))
        self.port = probe.getsockname()[1]
        probe.close()
        self.stop = threading.Event()
        self.said: list[str] = []
        self.thread = threading.Thread(
            target=serve,
            kwargs={
                "host": "127.0.0.1",
                "port": self.port,
                "announce": self.said.append,
                "stop": self.stop.is_set,
            },
            daemon=True,
        )

    def __enter__(self) -> Room:
        self.thread.start()
        for _ in range(100):  # the bind is quick, but it is not instant
            if self.said:
                break
            time.sleep(0.01)
        return self

    def __exit__(self, *_: object) -> None:
        self.stop.set()
        self.thread.join(timeout=5.0)


def joined(port: int, name: str) -> NetworkCompany:
    return NetworkCompany(address=("127.0.0.1", port), me=rider(name))


def ride(*riders: NetworkCompany, until: int = 0, seconds: float = 10.0) -> None:
    """Ride everybody at once, until each has the company expected.

    All of them together, because a rider only hears somebody who is talking
    at the time: advancing one and then the other is two people taking turns
    to be alone on the track.
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        for rider_here in riders:
            rider_here.advance(0.05)
        # `until=0` is "ride the whole time and see what turns up", which is how
        # a test shows that nobody does.
        if until and all(
            len(rider_here.companions()) >= until for rider_here in riders
        ):
            return
        time.sleep(0.02)


def test_two_riders_find_each_other_through_a_relay() -> None:
    with Room() as room:
        askar, dana = joined(room.port, "askar"), joined(room.port, "dana")
        try:
            askar.report(rider("askar", distance_m=1200.0))
            dana.report(rider("dana", distance_m=800.0))
            ride(askar, dana, until=1)

            seen_by_askar = askar.companions()
            seen_by_dana = dana.companions()
        finally:
            askar.close()
            dana.close()

    assert [companion.name for companion in seen_by_askar] == ["dana"]
    assert seen_by_askar[0].distance_m == pytest.approx(800.0)
    assert [companion.name for companion in seen_by_dana] == ["askar"]


def test_a_rider_never_sees_themselves() -> None:
    with Room() as room:
        askar = joined(room.port, "askar")
        try:
            ride(askar, seconds=1.0, until=0)
            alone = askar.companions()
        finally:
            askar.close()

    assert alone == ()


def test_riding_on_a_different_track_is_riding_alone() -> None:
    with Room() as room:
        askar = NetworkCompany(
            address=("127.0.0.1", room.port), me=rider("askar", world="sokol")
        )
        dana = NetworkCompany(
            address=("127.0.0.1", room.port), me=rider("dana", world="alps")
        )
        try:
            ride(askar, dana, seconds=1.0)
            seen = askar.companions()
        finally:
            askar.close()
            dana.close()

    assert seen == ()


def test_the_room_says_who_is_in_it() -> None:
    with Room() as room:
        askar = joined(room.port, "askar")
        try:
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                askar.advance(0.05)
                if any("rider" in line for line in room.said):
                    break
                time.sleep(0.02)
        finally:
            askar.close()
        said = list(room.said)

    assert any("room open" in line for line in said)
    assert any("1 rider" in line for line in said)


# When the network is not there, which is the case that matters.


def test_a_host_that_does_not_resolve_is_not_a_crash() -> None:
    """A training session does not end because a name server said no."""
    company = NetworkCompany(address=("no-such-host.invalid", 51820), me=rider("askar"))
    try:
        company.advance(0.05)

        assert company.lost
        assert "no-such-host.invalid" in company.lost
        assert company.companions() == ()
    finally:
        company.close()


def test_a_relay_that_goes_away_leaves_the_rider_riding() -> None:
    """The room stops answering mid-ride; the ride does not stop."""
    with Room() as room:
        port = room.port
    company = NetworkCompany(address=("127.0.0.1", port), me=rider("askar"))
    try:
        for tick in range(20):
            company.advance(0.05)  # nothing here should raise
            company.report(rider("askar", distance_m=float(tick)))

        assert company.companions() == ()
    finally:
        company.close()


def test_a_send_that_fails_is_reported_and_survived() -> None:
    """The route to the relay goes away between one datagram and the next."""

    class BrokenSocket:
        def sendto(self, _datagram: bytes, _address: tuple[str, int]) -> int:
            raise OSError("network is down")

        def recvfrom(self, _size: int) -> tuple[bytes, tuple[str, int]]:
            raise BlockingIOError

        def close(self) -> None:
            return

    company = NetworkCompany(
        address=("127.0.0.1", 51820),
        me=rider("askar"),
        sock=BrokenSocket(),  # type: ignore[arg-type]
    )

    company.advance(0.05)

    assert "network is down" in company.lost
    assert company.companions() == ()


def test_a_closed_company_is_quiet_rather_than_broken() -> None:
    company = NetworkCompany(address=("127.0.0.1", 51820), me=rider("askar"))
    company.close()

    company.advance(0.05)  # no socket left to use

    assert company.companions() == ()
    company.close()  # and closing twice is not an error either


def test_riders_are_not_told_where_we_are_more_often_than_agreed() -> None:
    """Five times a second, not once a frame: this goes out per rider."""
    sent: list[bytes] = []

    class CountingSocket:
        def sendto(self, datagram: bytes, _address: tuple[str, int]) -> int:
            sent.append(datagram)
            return len(datagram)

        def recvfrom(self, _size: int) -> tuple[bytes, tuple[str, int]]:
            raise BlockingIOError

        def close(self) -> None:
            return

    clock = iter([tick * 0.016 for tick in range(120)])  # 60 fps for two seconds
    company = NetworkCompany(
        address=("127.0.0.1", 51820),
        me=rider("askar"),
        sock=CountingSocket(),  # type: ignore[arg-type]
        clock=lambda: next(clock),
    )

    for _ in range(120):
        company.advance(0.016)

    assert 8 <= len(sent) <= 12, f"about ten in two seconds, got {len(sent)}"


def test_a_flood_cannot_hold_up_a_frame() -> None:
    """A burst is drained over the next few frames rather than all at once."""

    class FloodingSocket:
        def __init__(self) -> None:
            self.reads = 0

        def sendto(self, datagram: bytes, _address: tuple[str, int]) -> int:
            return len(datagram)

        def recvfrom(self, _size: int) -> tuple[bytes, tuple[str, int]]:
            self.reads += 1
            return rider(f"r{self.reads}").encode(), ("10.0.0.1", 1)

        def close(self) -> None:
            return

    flooding = FloodingSocket()
    company = NetworkCompany(
        address=("127.0.0.1", 51820),
        me=rider("askar"),
        sock=flooding,  # type: ignore[arg-type]
    )
    company.advance(0.016)

    assert flooding.reads <= 64, "one frame does not read an unbounded backlog"


def test_a_refused_datagram_is_not_an_error_a_rider_sees() -> None:
    """Linux reports an absent relay by failing the *next* read, not the send."""

    class RefusingSocket:
        def sendto(self, datagram: bytes, _address: tuple[str, int]) -> int:
            return len(datagram)

        def recvfrom(self, _size: int) -> tuple[bytes, tuple[str, int]]:
            raise ConnectionRefusedError("connection refused")

        def close(self) -> None:
            return

    company = NetworkCompany(
        address=("127.0.0.1", 51820),
        me=rider("askar"),
        sock=RefusingSocket(),  # type: ignore[arg-type]
    )

    company.advance(0.05)  # must not raise

    assert company.companions() == ()


def test_junk_on_the_socket_is_ignored_rather_than_drawn() -> None:
    class NoisySocket:
        def __init__(self) -> None:
            self.given = [b"not a rider at all", rider("dana").encode()]

        def sendto(self, datagram: bytes, _address: tuple[str, int]) -> int:
            return len(datagram)

        def recvfrom(self, _size: int) -> tuple[bytes, tuple[str, int]]:
            if not self.given:
                raise BlockingIOError
            return self.given.pop(0), ("10.0.0.1", 1)

        def close(self) -> None:
            return

    company = NetworkCompany(
        address=("127.0.0.1", 51820),
        me=rider("askar"),
        sock=NoisySocket(),  # type: ignore[arg-type]
    )
    company.advance(0.05)

    assert [companion.name for companion in company.companions()] == ["dana"]
