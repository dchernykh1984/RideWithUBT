from __future__ import annotations

import pytest

from app.world.network import Point
from app.world.offset import MAX_MITRE, offset_polyline


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
