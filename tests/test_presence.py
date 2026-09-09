"""The wire format, and every way a stranger's datagram can be wrong.

Everything decoded here came off a network from somebody this application has
never met, so the interesting tests are not the round trip - they are the junk.
"""

from __future__ import annotations

import json
import math

import pytest

from app.core.presence import (
    FORGET_AFTER_S,
    MAX_NAME,
    PROTOCOL_VERSION,
    PresenceError,
    RiderState,
    Roster,
    anonymous_id,
)


def rider(**changes: object) -> RiderState:
    fields: dict[str, object] = {
        "id": "abc123",
        "name": "Askar",
        "world_id": "sokol",
        "x": 120.5,
        "y": -33.25,
        "z": 645.0,
        "heading_rad": 1.5,
        "distance_m": 4400.0,
        "speed_ms": 11.1,
        "cadence_rpm": 90.0,
        "power_w": 240.0,
    }
    fields.update(changes)
    return RiderState(**fields)  # type: ignore[arg-type]


def datagram(**changes: object) -> bytes:
    payload = {
        "v": PROTOCOL_VERSION,
        "id": "abc123",
        "name": "Askar",
        "world": "sokol",
        "x": 120.5,
        "y": -33.25,
        "z": 645.0,
        "heading": 1.5,
        "distance": 4400.0,
        "speed": 11.1,
    }
    payload.update(changes)
    return json.dumps(payload).encode("utf-8")


def test_a_rider_survives_the_round_trip() -> None:
    there_and_back = RiderState.decode(rider().encode())

    assert there_and_back == rider()


def test_the_datagram_carries_what_was_promised_and_no_more() -> None:
    """Position, speed, cadence, power. Not a heart rate, not a workout."""
    payload = json.loads(rider().encode())

    assert set(payload) == {
        "v",
        "id",
        "name",
        "world",
        "x",
        "y",
        "z",
        "heading",
        "distance",
        "speed",
        "cadence",
        "power",
    }


def test_a_rider_with_no_sensors_sends_no_readings() -> None:
    payload = json.loads(rider(cadence_rpm=None, power_w=None).encode())

    assert "cadence" not in payload
    assert "power" not in payload
    assert (
        RiderState.decode(rider(cadence_rpm=None, power_w=None).encode()).power_w
        is None
    )


def test_a_datagram_is_small() -> None:
    """It goes out five times a second, per rider, to everyone else."""
    assert len(rider().encode()) < 256


@pytest.mark.parametrize(
    "junk",
    [
        b"",
        b"not json at all",
        b"\xff\xfe\x00",
        b"[1, 2, 3]",
        b'"a string"',
        b"null",
        b"12",
    ],
    ids=["empty", "text", "bytes", "array", "string", "null", "number"],
)
def test_junk_is_not_a_rider(junk: bytes) -> None:
    with pytest.raises(PresenceError):
        RiderState.decode(junk)


def test_a_protocol_from_the_future_is_not_guessed_at() -> None:
    with pytest.raises(PresenceError, match="protocol"):
        RiderState.decode(datagram(v=PROTOCOL_VERSION + 1))

    with pytest.raises(PresenceError, match="protocol"):
        RiderState.decode(datagram(v="one"))


@pytest.mark.parametrize("missing", ["id", "world", "x", "y", "speed", "heading"])
def test_a_datagram_missing_something_it_needs_is_dropped(missing: str) -> None:
    payload = json.loads(datagram())
    del payload[missing]

    with pytest.raises(PresenceError):
        RiderState.decode(json.dumps(payload).encode())


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_numbers_that_are_not_numbers_are_dropped(value: float) -> None:
    """A NaN coordinate does not draw a rider; it poisons the scene graph."""
    with pytest.raises(PresenceError):
        RiderState.decode(json.dumps({**json.loads(datagram()), "x": value}).encode())


def test_a_rider_off_the_map_is_dropped() -> None:
    with pytest.raises(PresenceError, match="off the map"):
        RiderState.decode(datagram(x=1e12))


def test_nobody_does_the_speed_of_sound() -> None:
    with pytest.raises(PresenceError, match="off the map"):
        RiderState.decode(datagram(speed=340.0))


def test_a_power_nobody_produces_is_dropped() -> None:
    with pytest.raises(PresenceError):
        RiderState.decode(datagram(power=99999.0))


def test_text_where_a_number_belongs_is_dropped() -> None:
    with pytest.raises(PresenceError, match="should be a number"):
        RiderState.decode(datagram(speed="fast"))


def test_a_boolean_is_not_a_number() -> None:
    """True is 1 in Python, and that is exactly the sort of thing to reject."""
    with pytest.raises(PresenceError, match="should be a number"):
        RiderState.decode(datagram(speed=True))


def test_a_number_where_a_name_belongs_is_dropped() -> None:
    with pytest.raises(PresenceError, match="should be text"):
        RiderState.decode(datagram(name=12))


def test_an_empty_id_is_not_an_id() -> None:
    with pytest.raises(PresenceError, match="required"):
        RiderState.decode(datagram(id=""))


def test_control_characters_never_reach_a_window() -> None:
    """A name is drawn above a rider's head, whoever sent it."""
    state = RiderState.decode(datagram(name="Askar\x00\x1b[31m\n"))

    assert state.name == "Askar[31m"


def test_a_name_longer_than_the_screen_is_cut() -> None:
    state = RiderState.decode(datagram(name="A" * 500))

    assert len(state.name) == MAX_NAME


def test_a_datagram_with_no_name_at_all_is_still_a_rider() -> None:
    """A name is optional; an id and a place are not."""
    payload = json.loads(datagram())
    del payload["name"]

    assert RiderState.decode(json.dumps(payload).encode()).name == ""


def test_a_rider_with_no_name_is_still_someone() -> None:
    state = RiderState.decode(datagram(name=""))

    assert state.name == ""
    assert state.as_companion().name == "abc123"


def test_a_rider_becomes_somebody_to_draw() -> None:
    companion = rider().as_companion()

    assert companion.id == "abc123"
    assert companion.name == "Askar"
    assert (companion.point.x, companion.point.y, companion.point.z) == (
        120.5,
        -33.25,
        645.0,
    )
    assert companion.speed_ms == pytest.approx(11.1)
    assert companion.power_w == pytest.approx(240.0)


def test_an_id_is_random_and_means_nothing() -> None:
    first, second = anonymous_id(), anonymous_id()

    assert first != second
    assert len(first) == 16
    assert int(first, 16) >= 0  # hex, so it survives any transport


# The roster.


def test_the_roster_collects_who_is_out_there() -> None:
    roster = Roster(world_id="sokol")

    assert roster.hear(rider(id="one"), now=0.0)
    assert roster.hear(rider(id="two"), now=0.1)

    assert {companion.id for companion in roster.companions()} == {"one", "two"}


def test_a_rider_who_goes_quiet_is_forgotten() -> None:
    """A ghost at the last known corner is worse than an empty road."""
    roster = Roster(world_id="sokol")
    roster.hear(rider(id="one"), now=0.0)
    roster.hear(rider(id="two"), now=0.0)

    roster.hear(rider(id="two"), now=FORGET_AFTER_S + 1.0)
    roster.forget_quiet(now=FORGET_AFTER_S + 1.0)

    assert [companion.id for companion in roster.companions()] == ["two"]


def test_a_rider_still_talking_stays() -> None:
    roster = Roster(world_id="sokol")
    for tick in range(20):
        moment = tick * (FORGET_AFTER_S / 2)
        roster.hear(rider(id="one"), now=moment)
        roster.forget_quiet(now=moment)

    assert len(roster.companions()) == 1


def test_the_latest_word_is_the_one_that_counts() -> None:
    roster = Roster(world_id="sokol")
    roster.hear(rider(id="one", distance_m=100.0), now=0.0)
    roster.hear(rider(id="one", distance_m=200.0), now=0.2)

    assert [companion.distance_m for companion in roster.companions()] == [200.0]


def test_our_own_datagram_coming_back_is_not_another_rider() -> None:
    """A relay copies to everyone; a rider must not chase themselves."""
    roster = Roster(world_id="sokol", ignore="me")

    assert not roster.hear(rider(id="me"), now=0.0)
    assert roster.companions() == ()


def test_somebody_riding_a_different_world_is_not_on_this_road() -> None:
    roster = Roster(world_id="sokol")

    assert not roster.hear(rider(id="one", world_id="alps"), now=0.0)
    assert roster.companions() == ()


def test_heading_stays_an_angle() -> None:
    with pytest.raises(PresenceError):
        RiderState.decode(datagram(heading=1000.0))

    assert RiderState.decode(datagram(heading=-math.pi)).heading_rad == pytest.approx(
        -math.pi
    )
