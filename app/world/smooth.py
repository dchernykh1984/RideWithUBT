"""Turning a surveyed line into a road that can be ridden round.

Open data records a corner as a handful of points - about one every thirteen
metres on this circuit - and joining them with straight lines makes a corner
that is a sequence of flats meeting at angles. Riding it, the view snaps round
by up to twenty-six degrees at a time. That is not a rendering artefact to be
hidden; the rider's heading really does jump, because the road really is a
polygon.

So the road is rebuilt as a curve through the same points. A centripetal
Catmull-Rom spline passes exactly through every surveyed point - the survey is
the evidence and none of it is discarded - and fills in between them with a
curve that has a continuous tangent, which is what makes the heading turn
instead of snap.

Centripetal rather than uniform: with points spaced as unevenly as a survey
leaves them, a uniform spline overshoots and can loop back on itself, putting
a kink in the road where the data had none.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from app.world.network import Point

#: How far apart the points of a rebuilt road are. Fine enough that the heading
#: turns smoothly at racing speed, coarse enough that a 4.4 km circuit stays a
#: few thousand points rather than a hundred thousand.
DEFAULT_SPACING_M = 4.0

#: Centripetal parameterisation. 0.5 is the exponent that gives it its name and
#: its behaviour; 0 would be the uniform spline that overshoots.
ALPHA = 0.5

#: How hard each point is pulled towards the middle of its neighbours, and how
#: many times. Measured on this circuit: the step in curvature at a surveyed
#: point falls from sixteen degrees to under two, and the road moves at most
#: 1.3 m - a tenth of the width of the track, at the sharpest hairpin only.
RELAX_WEIGHT = 0.5
RELAX_ROUNDS = 8


def smooth_polyline(
    points: Sequence[Point], spacing_m: float = DEFAULT_SPACING_M
) -> tuple[Point, ...]:
    """The same road as a curve, sampled every ``spacing_m``.

    The ends are left exactly where they were, because they are junctions: a
    segment has to still start and finish on the node it is joined to.
    """
    if len(points) < 3:
        return tuple(points)
    # A spline needs a point before the first and after the last to have a
    # tangent there. Reflecting the neighbour keeps the ends straight rather
    # than inventing a curve the survey does not show.
    padded = [_reflect(points[1], points[0]), *points, _reflect(points[-2], points[-1])]
    curve: list[Point] = [points[0]]
    for index in range(1, len(padded) - 2):
        curve.extend(_span(padded[index - 1 : index + 3], spacing_m))
    # The ends are nodes that other segments are joined to, so they are put back
    # exactly rather than left as whatever the interpolation arrived at. The
    # difference is a fraction of a nanometre and the guarantee is worth more.
    curve[-1] = points[-1]
    # The spline turns smoothly but changes *how sharply* it turns in one step
    # at every surveyed point, because it is built to pass exactly through them
    # and a coarse survey does not sit on a smooth curve. A rider feels that
    # step as a flick of the bars. Easing the dense curve towards itself takes
    # it out, at the cost of leaving the surveyed points by about a metre where
    # the road bends hardest - which is a tenth of the width of the track, and
    # closer to the asphalt than the survey was.
    return relax(curve, RELAX_WEIGHT, RELAX_ROUNDS)


def relax(
    points: Sequence[Point], weight: float = RELAX_WEIGHT, rounds: int = RELAX_ROUNDS
) -> tuple[Point, ...]:
    """Ease each point towards the middle of its neighbours, ends held fast."""
    eased = list(points)
    for _ in range(rounds):
        moved = [eased[0]]
        for before, here, after in zip(eased, eased[1:], eased[2:], strict=False):
            moved.append(
                Point(
                    x=_ease(before.x, here.x, after.x, weight),
                    y=_ease(before.y, here.y, after.y, weight),
                    z=_ease(before.z, here.z, after.z, weight),
                )
            )
        moved.append(eased[-1])
        eased = moved
    return tuple(eased)


def _ease(before: float, here: float, after: float, weight: float) -> float:
    return (1.0 - weight) * here + weight * (before + after) / 2.0


def _span(control: Sequence[Point], spacing_m: float) -> list[Point]:
    """The piece of curve between the middle two of four control points."""
    before, start, end, after = control
    t0 = 0.0
    t1 = t0 + _knot(before, start)
    t2 = t1 + _knot(start, end)
    t3 = t2 + _knot(end, after)
    if t2 - t1 <= 0.0:  # pragma: no cover - segments reject repeated points
        return [end]
    # Measured on the chord, so the curve between two points comes out a little
    # coarser than asked for - by however much it bulges, which on a road is a
    # few percent.
    straight = math.dist((start.x, start.y), (end.x, end.y))
    steps = max(1, math.ceil(straight / spacing_m))
    return [
        _at(before, start, end, after, (t0, t1, t2, t3), t1 + (t2 - t1) * step / steps)
        for step in range(1, steps + 1)
    ]


def _knot(start: Point, end: Point) -> float:
    """The centripetal spacing between two control points."""
    distance = math.dist((start.x, start.y, start.z), (end.x, end.y, end.z))
    return max(distance, 1e-9) ** ALPHA


def _at(
    p0: Point,
    p1: Point,
    p2: Point,
    p3: Point,
    knots: tuple[float, float, float, float],
    t: float,
) -> Point:
    """One point on the curve, by repeated linear interpolation (de Boor)."""
    t0, t1, t2, t3 = knots
    a1 = _mix(p0, p1, t0, t1, t)
    a2 = _mix(p1, p2, t1, t2, t)
    a3 = _mix(p2, p3, t2, t3, t)
    b1 = _mix(a1, a2, t0, t2, t)
    b2 = _mix(a2, a3, t1, t3, t)
    return _mix(b1, b2, t1, t2, t)


def _mix(start: Point, end: Point, from_t: float, to_t: float, t: float) -> Point:
    span = to_t - from_t
    if span <= 0.0:  # pragma: no cover - knots are strictly increasing
        return start
    weight = (t - from_t) / span
    return Point(
        x=start.x + (end.x - start.x) * weight,
        y=start.y + (end.y - start.y) * weight,
        z=start.z + (end.z - start.z) * weight,
    )


def _reflect(neighbour: Point, edge: Point) -> Point:
    """A point mirrored through the end of the line, to give it a tangent."""
    return Point(
        x=2 * edge.x - neighbour.x,
        y=2 * edge.y - neighbour.y,
        z=2 * edge.z - neighbour.z,
    )
