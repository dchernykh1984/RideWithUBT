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


def _normal(start: Point, end: Point) -> tuple[float, float]:
    """The unit vector ninety degrees to the left of this edge."""
    dx, dy = end.x - start.x, end.y - start.y
    length = math.hypot(dx, dy)
    if length == 0.0:  # pragma: no cover - segments reject zero-length edges
        return (0.0, 0.0)
    return (-dy / length, dx / length)


def offset_polyline(points: Sequence[Point], offset_m: float) -> tuple[Point, ...]:
    """A parallel line, ``offset_m`` to the left; negative offsets go right.

    Elevation is carried across unchanged: a lane beside the track is at the
    track's height, not at zero.
    """
    if len(points) < 2:
        raise ValueError("a line needs at least two points to be offset")
    normals = [_normal(start, end) for start, end in pairwise(points)]
    moved = [_move(points[0], normals[0], offset_m)]
    for index in range(1, len(points) - 1):
        direction, scale = _mitre(normals[index - 1], normals[index])
        moved.append(_move(points[index], direction, offset_m * scale))
    moved.append(_move(points[-1], normals[-1], offset_m))
    return tuple(moved)


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
