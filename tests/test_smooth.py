"""A road that can be ridden round a corner without the view snapping.

Open data records a corner as a handful of points, and joining them with
straight lines makes a corner out of flats meeting at angles. The rider's
heading then really does jump - by up to twenty-six degrees at a time on this
circuit - which is what "the turns are jerky" meant.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise

import pytest

from app.world.description import load
from app.world.network import Point, Segment
from app.world.smooth import DEFAULT_SPACING_M, relax, smooth_polyline


def quarter_circle(radius: float = 100.0, points: int = 6) -> list[Point]:
    """A corner surveyed coarsely, the way open data gives one."""
    return [
        Point(
            x=radius * math.cos(math.pi / 2 * index / (points - 1)),
            y=radius * math.sin(math.pi / 2 * index / (points - 1)),
            z=0.0,
        )
        for index in range(points)
    ]


def as_segment(points: list[Point] | tuple[Point, ...]) -> Segment:
    return Segment(id="s", start_node="a", end_node="b", points=tuple(points))


def turn_rates(segment: Segment, step: float = 1.0) -> list[float]:
    headings = [
        segment.heading_at(index * step)
        for index in range(int(segment.length_m / step))
    ]
    return [
        math.degrees(math.remainder(after - before, 2 * math.pi))
        for before, after in pairwise(headings)
    ]


def worst_jerk(segment: Segment) -> float:
    """The biggest change in how fast the road is turning: the snap itself."""
    return max(abs(after - before) for before, after in pairwise(turn_rates(segment)))


def corners(points: Sequence[Point]) -> list[float]:
    """How much the road turns at each of its own vertices, in degrees."""
    headings = [
        math.atan2(after.y - before.y, after.x - before.x)
        for before, after in pairwise(points)
    ]
    return [
        math.degrees(math.remainder(after - before, 2 * math.pi))
        for before, after in pairwise(headings)
    ]


def worst_corner(points: Sequence[Point]) -> float:
    """The sharpest angle in the road's own shape, in degrees."""
    return max(abs(turn) for turn in corners(points))


def worst_curvature_step(points: Sequence[Point]) -> float:
    """The biggest change in how sharply the road turns, vertex to vertex.

    This is the number that matters. A road may turn hard - a hairpin does -
    and that is not a jerk. A jerk is the road turning *differently* from one
    step to the next, which is what a rider feels as a flick of the bars, and
    what a curve built to pass through coarse survey points still has.
    """
    return max(abs(after - before) for before, after in pairwise(corners(points)))


# The curve.


def test_the_road_stays_where_the_survey_put_it() -> None:
    """Not exactly on every surveyed point - easing the curve leaves them by
    about a metre where the road bends hardest, which is a tenth of the width
    of the track. But nowhere else."""
    surveyed = quarter_circle()

    curve = smooth_polyline(surveyed)

    for point in surveyed:
        nearest = min(
            math.dist((point.x, point.y), (other.x, other.y)) for other in curve
        )
        assert nearest < 1.5, f"{point} is {nearest:.1f} m from the road now"


def test_the_ends_do_not_move() -> None:
    """They are junctions: a segment has to still meet what it joins."""
    surveyed = quarter_circle()

    curve = smooth_polyline(surveyed)

    assert curve[0] == surveyed[0]
    assert curve[-1] == surveyed[-1]


def test_a_corner_stops_snapping() -> None:
    """The shape open data actually gives: long edges meeting at an angle.

    A quarter circle sampled evenly is already smooth and proves nothing; the
    snap comes from a straight running into a turn with nothing in between.
    """
    kinked = [
        Point(0.0, 0.0, 0.0),
        Point(100.0, 0.0, 0.0),
        Point(180.0, 60.0, 0.0),
        Point(240.0, 160.0, 0.0),
    ]

    before = worst_corner(kinked)
    after = worst_corner(smooth_polyline(kinked))

    assert before > 30.0, "the surveyed road really does turn a corner at once"
    assert after < 5.0, f"{before:.1f} deg at a vertex became {after:.1f}, not enough"


def test_the_road_turns_the_whole_way_round_the_corner() -> None:
    """Not just at the surveyed points: everywhere in between as well."""
    curve = as_segment(smooth_polyline(quarter_circle()))

    turning = [abs(rate) for rate in turn_rates(curve)]

    assert sum(1 for rate in turning if rate > 0.1) > len(turning) * 0.8


def test_a_straight_stays_straight() -> None:
    """A smoother that invents a curve where the survey shows none is wrong."""
    straight = [Point(float(x) * 50.0, 0.0, 0.0) for x in range(5)]

    curve = smooth_polyline(straight)

    assert all(abs(point.y) < 1e-9 for point in curve)


def test_height_is_carried_along_the_curve() -> None:
    climbing = [Point(float(x) * 50.0, 0.0, float(x)) for x in range(5)]

    curve = smooth_polyline(climbing)

    assert curve[-1].z == pytest.approx(4.0)
    assert all(-0.1 <= point.z <= 4.1 for point in curve)


def test_the_curve_is_sampled_about_as_finely_as_asked() -> None:
    curve = smooth_polyline(quarter_circle(radius=100.0), spacing_m=5.0)

    spacings = [
        math.dist((before.x, before.y), (after.x, after.y))
        for before, after in pairwise(curve)
    ]

    assert max(spacings) <= 5.5


def test_two_points_are_already_as_smooth_as_a_line_gets() -> None:
    line = (Point(0.0, 0.0, 0.0), Point(100.0, 0.0, 0.0))

    assert smooth_polyline(line) == line


def test_easing_a_straight_leaves_it_alone() -> None:
    """The ends are held, so a straight cannot be pulled anywhere."""
    straight = [Point(float(x) * 10.0, 0.0, 0.0) for x in range(20)]

    eased = relax(straight)

    assert [point.x for point in eased] == pytest.approx([p.x for p in straight])
    assert all(abs(point.y) < 1e-9 for point in eased)


def test_easing_holds_both_ends_exactly() -> None:
    wandering = [Point(float(x) * 10.0, math.sin(x) * 5.0, 0.0) for x in range(20)]

    eased = relax(wandering)

    assert eased[0] == wandering[0]
    assert eased[-1] == wandering[-1]


def test_the_curve_does_not_overshoot_into_a_loop() -> None:
    """Unevenly spaced survey points make a uniform spline fold back on itself.

    Centripetal parameterisation is what prevents it, and this is the case that
    shows the difference: one very short edge between two long ones.
    """
    awkward = [
        Point(0.0, 0.0, 0.0),
        Point(100.0, 0.0, 0.0),
        Point(101.0, 2.0, 0.0),
        Point(200.0, 40.0, 0.0),
    ]

    curve = smooth_polyline(awkward)

    forward = [(after.x - before.x) for before, after in pairwise(curve)]
    assert all(step >= -0.01 for step in forward), "the road doubles back on itself"


# The heading, which is what the rider actually feels.


def test_the_heading_turns_between_edges_rather_than_at_them() -> None:
    """A road is straight pieces however finely it is drawn. Reading the
    heading off the current piece makes the view sit still and then snap."""
    corner = as_segment(
        [Point(0.0, 0.0, 0.0), Point(100.0, 0.0, 0.0), Point(200.0, 100.0, 0.0)]
    )

    before_corner = corner.heading_at(60.0)
    at_corner = corner.heading_at(100.0)
    after_corner = corner.heading_at(140.0)

    assert before_corner < at_corner < after_corner, "it should turn steadily"
    assert at_corner == pytest.approx(math.radians(22.5), abs=0.05)


def test_the_heading_at_the_very_ends_is_the_edge_it_is_on() -> None:
    """There is nothing before the first edge to blend towards."""
    corner = as_segment(
        [Point(0.0, 0.0, 0.0), Point(100.0, 0.0, 0.0), Point(200.0, 100.0, 0.0)]
    )

    assert corner.heading_at(0.0) == pytest.approx(0.0)
    assert corner.heading_at(corner.length_m) == pytest.approx(math.radians(45.0))


def test_the_heading_takes_the_short_way_round() -> None:
    """A road crossing due west must not spin the camera the long way."""
    crossing = as_segment(
        [Point(0.0, 0.0, 0.0), Point(-100.0, 1.0, 0.0), Point(-200.0, -1.0, 0.0)]
    )

    turns = [abs(rate) for rate in turn_rates(crossing, step=5.0)]

    assert max(turns) < 20.0, "a 350 degree spin means it went the wrong way"


# The circuit a rider actually loads.


def test_sokol_no_longer_snaps_round_its_corners() -> None:
    """Sixteen degrees of curvature in one step was what riding it looked like.

    The circuit still has a hairpin, and the road still turns hard there. What
    it no longer does is change how hard it is turning all at once.
    """
    network = load("sokol")

    for segment in network.segments:
        if len(segment.points) < 4:
            continue  # a straight between two nodes is two points and no corner
        step = worst_curvature_step(segment.points)
        assert step < 4.0, f"{segment.id} still snaps: {step:.1f} deg in one step"


def test_the_ride_never_jerks_round_the_whole_circuit() -> None:
    """End to end: the heading a rider is given, all the way round a lap."""
    network = load("sokol")

    for segment in network.segments:
        if segment.length_m < 50.0:
            continue
        assert worst_jerk(segment) < 4.0, f"{segment.id} still snaps"


def test_sokol_is_built_as_curves_rather_than_chords() -> None:
    network = load("sokol")
    longest = max(network.segments, key=lambda segment: segment.length_m)

    spacings = [
        math.dist((before.x, before.y), (after.x, after.y))
        for before, after in pairwise(longest.points)
    ]

    # The spacing is measured on the chord between two surveyed points, so a
    # curve between them comes out coarser by however much it bulges.
    assert max(spacings) <= DEFAULT_SPACING_M * 1.5


def test_smoothing_did_not_move_the_circuit() -> None:
    """A curve through the surveyed points is still the same circuit."""
    network = load("sokol")
    from app.world.navigation import lap_length_m

    assert 4400 <= lap_length_m(network, network.route("big-ring")) <= 4460
