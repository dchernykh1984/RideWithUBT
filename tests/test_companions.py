"""Other riders on the same track.

The point of this is not the pace partners. It is that there is somewhere for
other riders to be and a protocol for saying where they are, so riding with real
people over a network is something to add rather than to retrofit - while the
application still works with the cable pulled."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from app.core.companions import (
    DEFAULT_PARTNER_WATTS,
    Companion,
    NoCompany,
    PacePartners,
    Peloton,
    air_for,
    departed,
    parse_partners,
)
from app.core.physics import Air, Bike, steady_speed_ms
from app.core.presence import RiderState
from app.core.ride import Ride, RideSetup
from app.world.description import load
from app.world.network import Point
from tests.worlds import loop_network


def sokol():  # type: ignore[no-untyped-def]
    return load("sokol")


def ride_along(company: PacePartners, seconds: float, step: float = 0.5) -> None:
    for _ in range(int(seconds / step)):
        company.advance(step)


def test_riding_alone_is_the_ordinary_case() -> None:
    """With no company the road is empty, and nothing has to check for a server."""
    alone = NoCompany()

    alone.advance(1.0)

    assert alone.companions() == ()


def test_partners_start_where_the_rider_does() -> None:
    company = PacePartners.holding(loop_network(), watts=(150.0, 250.0))

    riders = company.companions()

    assert [rider.name for rider in riders] == ["150 W", "250 W"]
    assert all(rider.distance_m == 0.0 for rider in riders)
    assert len({rider.id for rider in riders}) == 2


def test_a_stronger_partner_ends_up_further_up_the_road() -> None:
    company = PacePartners.holding(loop_network(), watts=(150.0, 290.0))

    ride_along(company, seconds=600.0)

    slow, fast = company.companions()
    assert fast.distance_m > slow.distance_m
    assert fast.speed_ms > slow.speed_ms


def test_a_partner_settles_at_the_speed_their_power_is_worth() -> None:
    """They ride the same physics as the rider, or they are decoration."""
    company = PacePartners.holding(loop_network(), watts=(220.0,))

    ride_along(company, seconds=1200.0)

    (rider,) = company.companions()
    expected = steady_speed_ms(220.0, 0.0, Bike(), Air.at_altitude(0.0))
    assert rider.speed_ms == pytest.approx(expected, abs=0.1)


def test_partners_ride_the_real_circuit_with_its_ground() -> None:
    company = PacePartners.holding(sokol(), watts=(200.0,))

    ride_along(company, seconds=300.0)

    (rider,) = company.companions()
    assert 600 < rider.point.z < 700, "on the ground Sokol actually has"
    assert rider.distance_m > 1000


def test_a_partner_follows_the_route_it_was_given() -> None:
    world = sokol()
    company = PacePartners.holding(
        world, watts=(250.0,), route=world.route("small-ring")
    )

    ride_along(company, seconds=900.0)

    (rider,) = company.companions()
    assert rider.distance_m > 3000, "a lap of the small ring at least"


def test_a_companion_reports_what_a_screen_needs() -> None:
    company = PacePartners.holding(loop_network(), watts=(200.0,))
    ride_along(company, seconds=60.0)

    (rider,) = company.companions()

    assert isinstance(rider, Companion)
    assert rider.power_w == 200.0
    assert rider.speed_kmh == pytest.approx(rider.speed_ms * 3.6)


# Reading what the rider asked for.


def test_powers_are_read_the_way_a_rider_writes_them() -> None:
    assert parse_partners("150,220,290") == (150.0, 220.0, 290.0)
    assert parse_partners(" 200 , 250 ") == (200.0, 250.0)
    assert parse_partners("200,,250") == (200.0, 250.0)


def test_something_that_is_not_a_number_is_refused() -> None:
    with pytest.raises(ValueError, match="not a number of watts"):
        parse_partners("hard")


@pytest.mark.parametrize("watts", ["0", "-100", "3000"])
def test_a_pace_nobody_holds_is_refused(watts: str) -> None:
    with pytest.raises(ValueError, match="not a pace anyone holds"):
        parse_partners(watts)


def test_the_default_group_covers_a_club_run() -> None:
    """One to sit in with, one to work at, one to chase."""
    assert len(DEFAULT_PARTNER_WATTS) == 3
    assert DEFAULT_PARTNER_WATTS == tuple(sorted(DEFAULT_PARTNER_WATTS))


def test_companions_breathe_the_air_of_the_world_they_are_in() -> None:
    high = air_for(sokol())

    assert high.density_kgm3 < Air().density_kgm3


# In a ride.


def test_a_ride_without_partners_has_the_road_to_itself() -> None:
    riding = Ride(setup=RideSetup())

    assert riding.companions == ()


def test_partners_move_as_the_ride_moves() -> None:
    riding = Ride(setup=RideSetup(partner_watts=(150.0, 290.0), power_w=200.0))

    now = 0.0
    for _ in range(600):
        now += 0.5
        riding.advance(0.5, now)

    slow, fast = riding.companions
    assert slow.distance_m > 0
    assert fast.distance_m > slow.distance_m
    assert slow.distance_m < riding.state.distance_m < fast.distance_m, (
        "a rider at 200 W belongs between one at 150 and one at 290"
    )


def companion(identifier: str) -> Companion:
    return Companion(
        id=identifier,
        name=identifier,
        point=Point(0.0, 0.0, 0.0),
        heading_rad=0.0,
        distance_m=0.0,
        speed_ms=0.0,
    )


def test_a_rider_who_leaves_takes_their_marker_with_them() -> None:
    """Otherwise an arrow stays parked at the corner they were last seen at."""
    drawn = {"askar", "dana", "partner-0"}

    assert departed(drawn, [companion("askar"), companion("partner-0")]) == ("dana",)


def test_nobody_leaving_removes_nothing() -> None:
    drawn = {"askar", "dana"}

    assert departed(drawn, [companion("askar"), companion("dana")]) == ()


def test_an_empty_road_takes_every_marker_away() -> None:
    assert departed({"askar", "dana"}, []) == ("askar", "dana")


def test_a_rider_nobody_has_drawn_yet_is_not_departed() -> None:
    assert departed(set(), [companion("askar")]) == ()


# A road holds more than one kind of rider.


@dataclass
class Fixed:
    """A source with a fixed cast, counting what the ride asks of it."""

    people: tuple[Companion, ...]
    advanced: float = 0.0
    told: list[str] = field(default_factory=list)

    def advance(self, seconds: float) -> None:
        self.advanced += seconds

    def report(self, me: RiderState) -> None:
        self.told.append(me.id)

    def companions(self) -> Sequence[Companion]:
        return self.people


def someone(identifier: str) -> RiderState:
    return RiderState(
        id=identifier,
        name=identifier,
        world_id="sokol",
        x=0.0,
        y=0.0,
        z=0.0,
        heading_rad=0.0,
        distance_m=0.0,
        speed_ms=0.0,
    )


def test_a_peloton_is_everyone_from_everywhere() -> None:
    """A club ride with a partner to chase is two sources and one road."""
    partners = Fixed((companion("partner-0"),))
    people = Fixed((companion("askar"), companion("dana")))

    peloton = Peloton((partners, people))

    assert [rider.id for rider in peloton.companions()] == [
        "partner-0",
        "askar",
        "dana",
    ]


def test_every_source_is_moved_on() -> None:
    partners, people = Fixed(()), Fixed(())

    Peloton((partners, people)).advance(0.5)

    assert partners.advanced == 0.5
    assert people.advanced == 0.5


def test_every_source_is_told_where_we_are() -> None:
    partners, people = Fixed(()), Fixed(())

    Peloton((partners, people)).report(someone("me"))

    assert partners.told == ["me"]
    assert people.told == ["me"]


def test_an_empty_peloton_is_an_empty_road() -> None:
    peloton = Peloton()
    peloton.advance(1.0)
    peloton.report(someone("me"))

    assert peloton.companions() == ()


def test_the_made_up_riders_have_nowhere_to_send_anything() -> None:
    """Reporting to a pace partner is a no-op, not an error."""
    partners = PacePartners.holding(load("sokol"), (200.0,))

    partners.report(someone("me"))  # nothing to assert; it must simply not raise

    assert len(partners.companions()) == 1


def test_riding_alone_ignores_us_too() -> None:
    alone = NoCompany()

    alone.report(someone("me"))

    assert alone.companions() == ()
