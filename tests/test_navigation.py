from __future__ import annotations

import math
from dataclasses import replace

import pytest

from app.world.description import load
from app.world.navigation import (
    Navigator,
    Steer,
    UpcomingJunction,
    lap_length_m,
    lap_segments,
    normalise_angle,
)
from app.world.network import NetworkError, Point, Start
from tests.worlds import climbing_network, forked_network, loop_network


def approaching(distance_to_fork: float = 100.0) -> Navigator:
    """A navigator that has ridden to within a given distance of the junction."""
    navigator = Navigator(forked_network(), start_segment="approach")
    navigator.advance(200.0 - distance_to_fork)
    return navigator


def test_angles_fold_into_a_half_turn_either_way() -> None:
    assert normalise_angle(math.pi / 2) == pytest.approx(math.pi / 2)
    assert normalise_angle(3 * math.pi / 2) == pytest.approx(-math.pi / 2)
    assert normalise_angle(-3 * math.pi / 2) == pytest.approx(math.pi / 2)
    # An exact half turn is the same distance either way; only its size is fixed.
    assert abs(normalise_angle(3 * math.pi)) == pytest.approx(math.pi)


def test_a_navigator_starts_at_the_beginning_of_its_route() -> None:
    navigator = Navigator(forked_network(), route=forked_network().route("default"))

    assert navigator.position.segment_id == "approach"
    assert navigator.position.distance_m == 0.0
    assert navigator.travelled_m == 0.0
    assert navigator.point == Point(0.0, 0.0, 0.0)


def test_starting_on_a_segment_that_does_not_exist_is_refused() -> None:
    with pytest.raises(NetworkError, match="unknown segment"):
        Navigator(forked_network(), start_segment="nonesuch")


def test_a_world_with_no_segments_cannot_be_ridden() -> None:
    from app.world.network import TrackNetwork

    with pytest.raises(NetworkError, match="no segments"):
        Navigator(TrackNetwork(id="empty", name="Empty", segments=()))


def test_advancing_moves_along_the_segment() -> None:
    navigator = Navigator(forked_network(), start_segment="approach")

    navigator.advance(50.0)

    assert navigator.position.distance_m == pytest.approx(50.0)
    assert navigator.point.x == pytest.approx(50.0)
    assert navigator.travelled_m == pytest.approx(50.0)


def test_the_odometer_keeps_counting_across_segments() -> None:
    navigator = Navigator(forked_network(), start_segment="approach")

    navigator.advance(350.0)

    assert navigator.position.segment_id == "straight"
    assert navigator.position.distance_m == pytest.approx(150.0)
    assert navigator.travelled_m == pytest.approx(350.0)


def test_gradient_and_heading_come_from_the_track_underneath() -> None:
    navigator = Navigator(climbing_network(), start_segment="climb")

    navigator.advance(50.0)

    assert navigator.gradient == pytest.approx(0.1)
    assert navigator.heading_rad == pytest.approx(0.0)


def test_a_rider_can_go_round_a_loop_forever() -> None:
    navigator = Navigator(loop_network(), start_segment="north")

    navigator.advance(1000.0)  # two and a half laps of a 400 m square

    assert navigator.travelled_m == pytest.approx(1000.0)
    assert navigator.position.segment_id == "south"


def test_at_a_dead_end_the_rider_stops_rather_than_overshooting() -> None:
    navigator = Navigator(forked_network(), start_segment="straight")

    navigator.advance(10_000.0)

    assert navigator.position.segment_id == "straight"
    assert navigator.position.distance_m == pytest.approx(200.0)
    assert navigator.travelled_m == pytest.approx(200.0)


def test_going_nowhere_is_allowed() -> None:
    navigator = Navigator(forked_network(), start_segment="approach")

    navigator.advance(-5.0)

    assert navigator.position.distance_m == 0.0


# The junction: announcing, steering, and committing.


def test_a_junction_is_announced_only_once_it_is_close_enough() -> None:
    far = approaching(distance_to_fork=160.0)
    near = approaching(distance_to_fork=140.0)

    assert far.upcoming is None
    assert near.upcoming is not None
    assert near.upcoming.distance_m == pytest.approx(140.0)


def test_the_announcement_starts_on_the_default_exit() -> None:
    upcoming = approaching().upcoming

    assert upcoming is not None
    assert upcoming.chosen_exit == "straight"
    assert upcoming.bearing_rad == pytest.approx(0.0)
    assert upcoming.alternatives == 3


def test_a_route_can_pre_select_a_different_exit() -> None:
    network = forked_network()
    navigator = Navigator(
        network, start_segment="approach", route=network.route("left-route")
    )
    navigator.advance(100.0)

    upcoming = navigator.upcoming
    assert upcoming is not None
    assert upcoming.chosen_exit == "left"


def test_exits_are_ordered_left_to_right_not_as_written() -> None:
    """The file lists straight, left, right; the rider sees left, straight, right."""
    navigator = approaching()
    upcoming = navigator.upcoming

    assert upcoming is not None
    assert upcoming.exits == ("left", "straight", "right")


def test_pressing_left_moves_the_arrow_one_exit_anticlockwise() -> None:
    navigator = approaching()

    assert navigator.steer(Steer.LEFT) == "left"

    upcoming = navigator.upcoming
    assert upcoming is not None
    assert upcoming.bearing_rad == pytest.approx(math.pi / 2)


def test_pressing_right_moves_the_arrow_the_other_way() -> None:
    navigator = approaching()

    assert navigator.steer(Steer.RIGHT) == "right"

    upcoming = navigator.upcoming
    assert upcoming is not None
    assert upcoming.bearing_rad == pytest.approx(-math.pi / 2)


def test_holding_left_stops_at_the_leftmost_exit_rather_than_wrapping() -> None:
    """Wrapping would flick a rider holding left across to the far right."""
    navigator = approaching()

    navigator.steer(Steer.LEFT)
    navigator.steer(Steer.LEFT)
    navigator.steer(Steer.LEFT)

    upcoming = navigator.upcoming
    assert upcoming is not None
    assert upcoming.chosen_exit == "left"


def test_the_arrow_can_be_changed_back_before_the_junction() -> None:
    navigator = approaching()

    navigator.steer(Steer.LEFT)
    navigator.steer(Steer.RIGHT)

    upcoming = navigator.upcoming
    assert upcoming is not None
    assert upcoming.chosen_exit == "straight"


def test_the_rider_takes_whichever_way_the_arrow_points_on_arrival() -> None:
    navigator = approaching()
    navigator.steer(Steer.LEFT)

    navigator.advance(100.0)

    assert navigator.position.segment_id == "left"


def test_steering_with_no_junction_ahead_does_nothing() -> None:
    navigator = Navigator(loop_network(), start_segment="north")

    assert navigator.steer(Steer.LEFT) is None
    assert navigator.upcoming is None


def test_the_choice_resets_after_the_junction_is_passed() -> None:
    navigator = approaching()
    navigator.steer(Steer.LEFT)

    navigator.advance(100.0)

    assert navigator.upcoming is None, "there is no junction at the end of 'left'"


def test_choosing_an_exit_outright() -> None:
    navigator = approaching()

    navigator.choose("right")
    navigator.advance(100.0)

    assert navigator.position.segment_id == "right"


def test_choosing_something_that_is_not_an_exit_is_refused() -> None:
    navigator = approaching()

    with pytest.raises(NetworkError, match="not an exit"):
        navigator.choose("approach")


def test_choosing_with_no_junction_ahead_is_refused() -> None:
    navigator = Navigator(loop_network(), start_segment="north")

    with pytest.raises(NetworkError, match="not an exit"):
        navigator.choose("east")


def test_a_junction_crossed_in_one_long_step_still_honours_the_arrow() -> None:
    """A slow frame must not skip the decision the rider already made."""
    navigator = Navigator(forked_network(), start_segment="approach")
    navigator.advance(100.0)
    navigator.steer(Steer.RIGHT)

    navigator.advance(150.0)

    assert navigator.position.segment_id == "right"
    assert navigator.position.distance_m == pytest.approx(50.0)


def test_with_no_route_or_start_the_rider_begins_on_the_first_segment() -> None:
    navigator = Navigator(loop_network())

    assert navigator.position.segment_id == "north"


# Where a ride begins.


def test_a_world_says_where_a_ride_begins() -> None:
    """A session at an autodrome starts in the pits, not wherever the survey
    data happened to begin."""
    network = loop_network()
    with_start = replace(
        network, start=Start(segment_id=network.segments[1].id, offset_m=25.0)
    )

    navigator = Navigator(with_start)

    assert navigator.position.segment_id == network.segments[1].id
    assert navigator.position.distance_m == pytest.approx(25.0)


def test_the_start_does_not_move_the_finish() -> None:
    """Starting somewhere is not the same as measuring a lap from there."""
    network = loop_network()
    with_start = replace(
        network, start=Start(segment_id=network.segments[1].id, offset_m=25.0)
    )

    navigator = Navigator(with_start)

    assert navigator.travelled_m == 0.0, "a ride has gone nowhere when it begins"


def test_a_caller_naming_a_segment_means_it() -> None:
    """Pace partners and pictures ask for a particular segment; that wins."""
    network = loop_network()
    with_start = replace(
        network, start=Start(segment_id=network.segments[1].id, offset_m=25.0)
    )

    navigator = Navigator(with_start, start_segment=network.segments[0].id)

    assert navigator.position.segment_id == network.segments[0].id
    assert navigator.position.distance_m == 0.0


def test_a_world_with_nothing_to_say_starts_where_it_always_did() -> None:
    network = loop_network()

    navigator = Navigator(network)

    assert navigator.position.segment_id == network.segments[0].id
    assert navigator.position.distance_m == 0.0


def test_a_start_on_a_segment_that_is_not_there_is_refused() -> None:
    network = loop_network()

    with pytest.raises(NetworkError, match="not a segment"):
        replace(network, start=Start(segment_id="nowhere"))


def test_a_start_past_the_end_of_its_segment_is_refused() -> None:
    """It would put the rider off the end of the road, silently."""
    network = loop_network()
    length = network.segments[0].length_m

    with pytest.raises(NetworkError, match="which is"):
        replace(
            network,
            start=Start(segment_id=network.segments[0].id, offset_m=length + 1.0),
        )


def test_sokol_starts_halfway_down_the_pit_lane() -> None:
    """Where a session at the autodrome actually begins."""
    network = load("sokol")
    pit = network.segment("pit-lane-0")

    assert network.start is not None
    assert network.start.segment_id == "pit-lane-0"
    assert network.start.offset_m == pytest.approx(pit.length_m / 2, rel=1e-6)


def test_leaving_the_pits_puts_you_on_the_circuit() -> None:
    """The point of starting there: roll out, and the track is what follows."""
    network = load("sokol")
    navigator = Navigator(network, route=network.route("big-ring"))
    assert navigator.position.segment_id == "pit-lane-0"

    navigator.advance(400.0)

    assert not navigator.position.segment_id.startswith("pit-lane")
    assert navigator.position.segment_id.startswith("main")


def test_a_lap_is_still_the_circuit_and_not_the_pit_lane() -> None:
    """The pit lane is how a ride begins, never part of the lap it measures."""
    network = load("sokol")

    for route in network.routes:
        segments = lap_segments(network, route)
        assert not any(name.startswith("pit-lane") for name in segments), route.id
    # Sokol publishes 4.495 km, measured along the racing line; open data
    # traces the centre of the track and a smoothed curve cuts the corners a
    # little more, so the built lap comes out consistently short of it.
    assert 4380 <= lap_length_m(network, network.route("big-ring")) <= 4460


# Which way the sign points.


def test_the_chosen_way_is_ranked_among_the_ways_out() -> None:
    """By its place in the order, not by its angle: the roads at a circuit
    part company by six or seven degrees, and drawn honestly that is a sign
    pointing straight up whichever way the rider is about to go."""
    network = load("sokol")
    navigator = Navigator(network, route=network.route("big-ring"))

    while navigator.upcoming is None:
        navigator.advance(10.0)
    upcoming = navigator.upcoming

    assert len(upcoming.exits) == 2
    assert upcoming.rank in (-1, 1)
    assert upcoming.exits.index(upcoming.chosen_exit) == (
        0 if upcoming.rank == -1 else 1
    )


def test_the_two_routes_through_a_junction_point_opposite_ways() -> None:
    network = load("sokol")

    ranks = []
    for route_id in ("big-ring", "small-ring"):
        navigator = Navigator(network, route=network.route(route_id))
        while navigator.upcoming is None:
            navigator.advance(10.0)
        ranks.append(navigator.upcoming.rank)

    assert ranks == [-1, 1] or ranks == [1, -1]


def test_a_junction_with_one_way_out_is_not_a_choice() -> None:
    upcoming = UpcomingJunction(
        node="n1",
        distance_m=50.0,
        chosen_exit="a",
        exits=("a",),
        bearing_rad=0.0,
        point=Point(0.0, 0.0, 0.0),
    )

    assert upcoming.rank == 0


def test_a_middle_way_out_is_neither_left_nor_right() -> None:
    upcoming = UpcomingJunction(
        node="n1",
        distance_m=50.0,
        chosen_exit="b",
        exits=("a", "b", "c"),
        bearing_rad=0.0,
        point=Point(0.0, 0.0, 0.0),
    )

    assert upcoming.rank == 0


def test_a_chosen_way_that_is_not_on_offer_points_nowhere() -> None:
    upcoming = UpcomingJunction(
        node="n1",
        distance_m=50.0,
        chosen_exit="gone",
        exits=("a", "b"),
        bearing_rad=0.0,
        point=Point(0.0, 0.0, 0.0),
    )

    assert upcoming.rank == 0


def test_the_sign_stands_at_the_junction_not_in_front_of_the_rider() -> None:
    """On a bend, a fixed distance straight ahead is out in the grass."""
    network = load("sokol")
    navigator = Navigator(network, route=network.route("big-ring"))
    while navigator.upcoming is None:
        navigator.advance(10.0)

    upcoming = navigator.upcoming
    segment = network.segment(navigator.position.segment_id)

    assert upcoming.point == segment.points[-1]
