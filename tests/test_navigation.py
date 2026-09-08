from __future__ import annotations

import math

import pytest

from app.world.navigation import Navigator, Steer, normalise_angle
from app.world.network import NetworkError, Point
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
