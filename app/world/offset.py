"""Offsetting a line of track sideways.

Used to draw a lane that runs alongside another one - a pit lane, most of all -
where open data has the circuit but not the lane beside it. Offsetting the
circuit's own points keeps the two exactly parallel, which is what they are.

At each point the line turns, so the offset has to follow the corner rather than
the two edges separately, or the lane would come apart at every bend. The
standard fix is a mitre: offset along the bisector of the two edges, lengthened
by how sharply they meet.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise

from app.world.network import Point

# A hairpin's mitre runs away to infinity, so it is capped. Past this the corner
# is cut square instead, which is visibly wrong but bounded - and a pit lane is
# never offset around a hairpin.
MAX_MITRE = 4.0

# How finely a line is resampled before a taper is applied to it. Fine enough
# that the curve leaving the track reads as a curve, coarse enough not to turn a
# kilometre of pit lane into ten thousand points.
TAPER_STEP_M = 5.0


def _normal(start: Point, end: Point) -> tuple[float, float]:
    """The unit vector ninety degrees to the left of this edge."""
    dx, dy = end.x - start.x, end.y - start.y
    length = math.hypot(dx, dy)
    if length == 0.0:  # pragma: no cover - segments reject zero-length edges
        return (0.0, 0.0)
    return (-dy / length, dx / length)


def offset_polyline(
    points: Sequence[Point], offset_m: float, taper_m: float = 0.0
) -> tuple[Point, ...]:
    """A parallel line, ``offset_m`` to the left; negative offsets go right.

    With a ``taper_m`` the line starts and ends *on* the one it is offset from
    and eases out to the full offset over that distance. That is what a pit lane
    actually does - it leaves the track and rejoins it - and without it the lane
    runs alongside at full width and then simply stops in the grass, which is
    what it looked like.

    Elevation is carried across unchanged: a lane beside the track is at the
    track's height, not at zero.
    """
    if len(points) < 2:
        raise ValueError("a line needs at least two points to be offset")
    # A taper needs points to happen at. Open data gives a straight between two
    # nodes as exactly two points, and a lane that eases away from the track over
    # sixty metres has nowhere to do it - it would simply lie on the track.
    if taper_m > 0.0:
        points = densify(points, TAPER_STEP_M)
    normals = [_normal(start, end) for start, end in pairwise(points)]
    along = _distances(points)
    total = along[-1]
    moved = [_move(points[0], normals[0], offset_m * _ramp(0.0, total, taper_m))]
    for index in range(1, len(points) - 1):
        direction, scale = _mitre(normals[index - 1], normals[index])
        reach = offset_m * scale * _ramp(along[index], total, taper_m)
        moved.append(_move(points[index], direction, reach))
    moved.append(
        _move(points[-1], normals[-1], offset_m * _ramp(total, total, taper_m))
    )
    return tuple(moved)


def densify(points: Sequence[Point], spacing_m: float) -> tuple[Point, ...]:
    """The same line with points added, no further apart than ``spacing_m``.

    The shape does not change - every added point sits on an edge that was
    already there. It is the resolution that changes, which is what anything
    varying along a line needs to have somewhere to vary.
    """
    if spacing_m <= 0.0:  # pragma: no cover - callers pass a real spacing
        return tuple(points)
    dense: list[Point] = [points[0]]
    for start, end in pairwise(points):
        length = math.hypot(end.x - start.x, end.y - start.y)
        steps = max(1, math.ceil(length / spacing_m))
        for step in range(1, steps + 1):
            t = step / steps
            dense.append(
                Point(
                    x=start.x + (end.x - start.x) * t,
                    y=start.y + (end.y - start.y) * t,
                    z=start.z + (end.z - start.z) * t,
                )
            )
    return tuple(dense)


def _distances(points: Sequence[Point]) -> list[float]:
    """How far along the line each point sits."""
    along = [0.0]
    for start, end in pairwise(points):
        along.append(along[-1] + math.hypot(end.x - start.x, end.y - start.y))
    return along


def _ramp(distance_m: float, total_m: float, taper_m: float) -> float:
    """How much of the full offset applies this far along: 0 at each end, 1 in
    the middle.

    Smooth rather than linear, so the lane leaves the track at a tangent the way
    a real one does instead of kinking away from it at a visible corner.
    """
    if taper_m <= 0.0:
        return 1.0
    reach = min(taper_m, total_m / 2)
    if reach <= 0.0:  # pragma: no cover - a line with no length is refused above
        return 1.0
    from_either_end = min(distance_m, total_m - distance_m)
    t = max(0.0, min(1.0, from_either_end / reach))
    return t * t * (3.0 - 2.0 * t)


def _mitre(
    before: tuple[float, float], after: tuple[float, float]
) -> tuple[tuple[float, float], float]:
    """The bisector of two edge normals, and how far along it to travel.

    On a straight the two normals agree and the answer is "this way, exactly the
    offset". The sharper the corner, the further along the bisector the offset
    line has to sit for its two halves to meet.
    """
    bisector = (before[0] + after[0], before[1] + after[1])
    length = math.hypot(*bisector)
    if length == 0.0:  # pragma: no cover - a full reversal is not a track
        return (before, 1.0)
    unit = (bisector[0] / length, bisector[1] / length)
    # The cosine of half the turn: one on a straight, smaller the sharper it gets.
    cosine = unit[0] * before[0] + unit[1] * before[1]
    scale = 1.0 / cosine if cosine > 1.0 / MAX_MITRE else MAX_MITRE
    return (unit, scale)


def _move(point: Point, direction: tuple[float, float], distance: float) -> Point:
    return Point(
        x=point.x + direction[0] * distance,
        y=point.y + direction[1] * distance,
        z=point.z,
    )
