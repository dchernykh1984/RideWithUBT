"""Cutting a flat outline into triangles.

A building is a footprint and a height. The walls are easy - each edge becomes
a rectangle - but the roof is a polygon, and a graphics card draws triangles.

The pit garages at this circuit are an L, so a fan of triangles from the middle
is not good enough: on anything that is not convex, a fan puts triangles
outside the building. Ear clipping handles any outline that does not cross
itself, which is what a surveyed footprint is.
"""

from __future__ import annotations

from collections.abc import Sequence

#: A corner sharper than this is treated as a straight line and dropped. Real
#: survey data has near-duplicate points, and a zero-area ear stalls the cut.
FLAT = 1e-9


def signed_area(outline: Sequence[tuple[float, float]]) -> float:
    """Twice the area, negative if the outline runs clockwise."""
    total = 0.0
    for index, (x, y) in enumerate(outline):
        next_x, next_y = outline[(index + 1) % len(outline)]
        total += x * next_y - next_x * y
    return total / 2.0


def triangulate(
    outline: Sequence[tuple[float, float]],
) -> tuple[tuple[int, int, int], ...]:
    """The outline as triangles, given as indices into it.

    Indices rather than points, so a caller can carry heights or anything else
    alongside without this having to know about them.
    """
    corners = list(range(len(_without_repeats(outline))))
    points = _without_repeats(outline)
    if len(points) < 3:
        return ()
    if signed_area(points) < 0:  # ear clipping wants them anticlockwise
        corners.reverse()
    triangles: list[tuple[int, int, int]] = []
    guard = 0
    while len(corners) > 2 and guard < len(outline) * len(outline) + 10:
        guard += 1
        for position in range(len(corners)):
            before = corners[position - 1]
            here = corners[position]
            after = corners[(position + 1) % len(corners)]
            if _is_ear(points, corners, before, here, after):
                triangles.append((before, here, after))
                corners.pop(position)
                break
        else:
            # Nothing left that can be cut off cleanly: the outline crosses
            # itself or is otherwise not a building. Return what was managed
            # rather than looping, so a bad footprint costs a wonky roof and
            # not a hung application.
            break
    return tuple(triangles)


def _without_repeats(
    outline: Sequence[tuple[float, float]],
) -> list[tuple[float, float]]:
    """The outline with a repeated closing point and any duplicates dropped."""
    points: list[tuple[float, float]] = []
    for point in outline:
        if (
            not points
            or abs(point[0] - points[-1][0]) + abs(point[1] - points[-1][1]) > 1e-9
        ):
            points.append(point)
    if (
        len(points) > 1
        and abs(points[0][0] - points[-1][0]) + abs(points[0][1] - points[-1][1]) < 1e-9
    ):
        points.pop()
    return points


def _is_ear(
    points: Sequence[tuple[float, float]],
    corners: Sequence[int],
    before: int,
    here: int,
    after: int,
) -> bool:
    """Whether this corner can be cut off without taking anything else with it."""
    if _cross(points[before], points[here], points[after]) <= FLAT:
        return False  # a reflex corner, or three points in a line
    return not any(
        other not in (before, here, after)
        and _inside(points[before], points[here], points[after], points[other])
        for other in corners
    )


def _cross(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]
) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _inside(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    point: tuple[float, float],
) -> bool:
    return (
        _cross(a, b, point) >= 0
        and _cross(b, c, point) >= 0
        and _cross(c, a, point) >= 0
    )
