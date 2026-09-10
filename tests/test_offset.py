from __future__ import annotations

import math
from itertools import pairwise

import pytest

from app.world.description import load
from app.world.network import Point
from app.world.offset import (
    MAX_MITRE,
    densify,
    offset_polyline,
    offset_varying,
    ramps,
)


def test_a_straight_line_moves_sideways_by_exactly_the_offset() -> None:
    line = [Point(0, 0), Point(100, 0)]

    left = offset_polyline(line, 10.0)

    assert left == (Point(0.0, 10.0, 0.0), Point(100.0, 10.0, 0.0))


def test_a_negative_offset_goes_the_other_way() -> None:
    """Left is positive, so the inside of a clockwise circuit is negative."""
    right = offset_polyline([Point(0, 0), Point(100, 0)], -10.0)

    assert right == (Point(0.0, -10.0, 0.0), Point(100.0, -10.0, 0.0))


def test_the_lane_stays_at_the_height_of_the_track() -> None:
    line = [Point(0, 0, 5.0), Point(100, 0, 9.0)]

    offset = offset_polyline(line, 10.0)

    assert [point.z for point in offset] == [5.0, 9.0]


def test_a_corner_is_mitred_so_the_lane_does_not_come_apart() -> None:
    """Offsetting the two edges separately would leave a gap at the corner.

    East then north, offset ten metres to the left - which is the inside here.
    Both halves have to meet at one point ten metres in from the corner.
    """
    corner = [Point(0, 0), Point(100, 0), Point(100, 100)]

    inside = offset_polyline(corner, 10.0)

    assert inside[0] == Point(0.0, 10.0, 0.0)
    assert inside[1].x == pytest.approx(90.0)
    assert inside[1].y == pytest.approx(10.0)
    assert inside[2].x == pytest.approx(90.0)
    assert inside[2].y == pytest.approx(100.0)


def test_the_outside_of_a_corner_is_mitred_the_same_way() -> None:
    corner = [Point(0, 0), Point(100, 0), Point(100, 100)]

    outside = offset_polyline(corner, -10.0)

    assert outside[1].x == pytest.approx(110.0)
    assert outside[1].y == pytest.approx(-10.0)


def test_a_gentle_bend_barely_stretches_the_mitre() -> None:
    bend = [Point(0, 0), Point(100, 0), Point(200, 10)]

    offset = offset_polyline(bend, 10.0)

    # A shallow turn moves the point almost straight out from the track.
    assert offset[1].y == pytest.approx(10.0, abs=0.3)


def test_a_hairpin_mitre_is_capped_rather_than_running_away() -> None:
    """The exact mitre goes to infinity as the corner closes; the lane must not."""
    hairpin = [Point(0, 0), Point(100, 0), Point(0, 1)]

    offset = offset_polyline(hairpin, 10.0)

    assert offset[1].distance_to(Point(100, 0)) <= 10.0 * MAX_MITRE + 1e-6


def test_offsetting_by_nothing_leaves_the_line_alone() -> None:
    line = [Point(0, 0), Point(100, 0), Point(100, 100)]

    assert offset_polyline(line, 0.0) == tuple(line)


def test_a_line_needs_two_points() -> None:
    with pytest.raises(ValueError, match="at least two points"):
        offset_polyline([Point(0, 0)], 10.0)


# Leaving the track and coming back to it.


def test_a_tapered_line_starts_and_ends_on_the_one_it_left() -> None:
    """A pit lane that keeps its full offset to the last metre stops in the
    grass, which is exactly what it looked like."""
    straight = (Point(0.0, 0.0, 0.0), Point(400.0, 0.0, 0.0))

    lane = offset_polyline(straight, 14.0, taper_m=60.0)

    assert lane[0].y == pytest.approx(0.0)
    assert lane[-1].y == pytest.approx(0.0)


def test_the_middle_still_runs_at_the_full_offset() -> None:
    straight = (Point(0.0, 0.0, 0.0), Point(400.0, 0.0, 0.0))

    lane = offset_polyline(straight, 14.0, taper_m=60.0)
    middle = lane[len(lane) // 2]

    assert middle.y == pytest.approx(14.0, abs=0.1)


def test_the_taper_only_moves_sideways_never_along() -> None:
    """The lane must still run between the same two nodes."""
    straight = (Point(0.0, 0.0, 0.0), Point(400.0, 0.0, 0.0))

    lane = offset_polyline(straight, 14.0, taper_m=60.0)

    assert lane[0].x == pytest.approx(0.0)
    assert lane[-1].x == pytest.approx(400.0)


def test_the_lane_leaves_smoothly_rather_than_kinking_away() -> None:
    """A linear ramp would put a visible corner where the lane departs."""
    straight = (Point(0.0, 0.0, 0.0), Point(400.0, 0.0, 0.0))

    lane = offset_polyline(straight, 14.0, taper_m=60.0)
    early = [point.y for point in lane[:6]]
    steps = [b - a for a, b in pairwise(early)]

    assert all(later >= earlier for earlier, later in pairwise(steps)), (
        "the lane should ease away, each step wider than the last"
    )


def test_a_short_lane_still_reaches_the_track_at_both_ends() -> None:
    """A taper longer than the lane must not leave one end hanging."""
    straight = (Point(0.0, 0.0, 0.0), Point(50.0, 0.0, 0.0))

    lane = offset_polyline(straight, 14.0, taper_m=200.0)

    assert lane[0].y == pytest.approx(0.0)
    assert lane[-1].y == pytest.approx(0.0)
    assert max(point.y for point in lane) > 0.0, "it still has to be a lane"


def test_no_taper_is_the_parallel_line_it_always_was() -> None:
    straight = (Point(0.0, 0.0, 0.0), Point(400.0, 0.0, 0.0))

    lane = offset_polyline(straight, 14.0)

    assert [point.y for point in lane] == pytest.approx([14.0, 14.0])


def test_densifying_adds_points_without_moving_the_line() -> None:
    line = (Point(0.0, 0.0, 10.0), Point(100.0, 0.0, 20.0))

    dense = densify(line, 10.0)

    assert len(dense) == 11
    assert dense[0] == line[0]
    assert dense[-1].x == pytest.approx(100.0)
    assert all(point.y == 0.0 for point in dense)
    assert dense[5].z == pytest.approx(15.0), "height is carried along too"


def test_densifying_leaves_a_line_that_is_already_fine_enough() -> None:
    line = (Point(0.0, 0.0, 0.0), Point(3.0, 0.0, 0.0))

    assert len(densify(line, 10.0)) == 2


def test_sokol_pit_lane_joins_the_track_at_both_ends() -> None:
    """The one that matters: the world a rider actually loads."""
    network = load("sokol")
    lane = network.segment("pit-lane-0")
    track = network.segment("main-1")

    def gap(fraction: float) -> float:
        here = lane.point_at(lane.length_m * fraction)
        there = track.point_at(track.length_m * fraction)
        return math.hypot(here.x - there.x, here.y - there.y)

    assert gap(0.0) == pytest.approx(0.0, abs=0.5)
    assert gap(1.0) == pytest.approx(0.0, abs=0.5)
    assert gap(0.5) == pytest.approx(14.0, abs=0.5), "and still a lane in between"


# A lane that changes width along its length.


def test_a_line_can_be_offset_by_a_different_reach_at_each_point() -> None:
    straight = (Point(0.0, 0.0, 0.0), Point(10.0, 0.0, 0.0), Point(20.0, 0.0, 0.0))

    moved = offset_varying(straight, (1.0, 5.0, 2.0))

    assert [round(point.y, 6) for point in moved] == [1.0, 5.0, 2.0]


def test_every_point_needs_a_reach() -> None:
    straight = (Point(0.0, 0.0, 0.0), Point(10.0, 0.0, 0.0))

    with pytest.raises(ValueError, match="reach of its own"):
        offset_varying(straight, (1.0,))


def test_a_ramp_eases_from_nothing_to_the_full_reach() -> None:
    straight = densify((Point(0.0, 0.0, 0.0), Point(400.0, 0.0, 0.0)), 5.0)

    reaches = ramps(straight, 60.0, 14.0)

    assert reaches[0] == pytest.approx(0.0)
    assert reaches[-1] == pytest.approx(0.0)
    assert max(reaches) == pytest.approx(14.0)


def test_a_ramp_can_ease_between_two_reaches() -> None:
    """A pit lane's inner edge leaves the kerb rather than the centre line."""
    straight = densify((Point(0.0, 0.0, 0.0), Point(400.0, 0.0, 0.0)), 5.0)

    reaches = ramps(straight, 60.0, 6.0, 10.0)

    assert reaches[0] == pytest.approx(6.0)
    assert max(reaches) == pytest.approx(10.0)


def test_sokol_pit_lane_has_no_width_where_it_meets_the_track() -> None:
    """A lane still at full width where it merges paints its own edge lines
    across the racing surface, which is what was on screen."""
    lane = load("sokol").segment("pit-lane-0")

    assert lane.width_profile is not None
    assert lane.width_profile[0] == pytest.approx(0.0)
    assert lane.width_profile[-1] == pytest.approx(0.0)
    assert max(lane.width_profile) == pytest.approx(8.0)


def test_the_pit_lane_still_starts_and_ends_on_the_track() -> None:
    """Its width may go to nothing; its centre may not. A rider coming off it
    onto the circuit must not step sideways to do so."""
    network = load("sokol")
    lane = network.segment("pit-lane-0")
    entry = network.segment("main-0")
    exit_to = network.segment("main-2")

    assert (
        math.dist(
            (lane.points[0].x, lane.points[0].y),
            (entry.points[-1].x, entry.points[-1].y),
        )
        < 0.5
    )
    assert (
        math.dist(
            (lane.points[-1].x, lane.points[-1].y),
            (exit_to.points[0].x, exit_to.points[0].y),
        )
        < 0.5
    )
