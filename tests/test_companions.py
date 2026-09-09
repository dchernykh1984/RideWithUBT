"""Other riders on the same track.

The point of this is not the pace partners. It is that there is somewhere for
other riders to be and a protocol for saying where they are, so riding with real
people over a network is something to add rather than to retrofit - while the
application still works with the cable pulled."""

from __future__ import annotations

import pytest

from app.core.companions import (
    DEFAULT_PARTNER_WATTS,
    Companion,
    NoCompany,
    PacePartners,
    air_for,
    parse_partners,
)
from app.core.physics import Air, Bike, steady_speed_ms
from app.core.ride import Ride, RideSetup
from app.world.description import load
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
