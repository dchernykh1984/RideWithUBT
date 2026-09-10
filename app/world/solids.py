"""Boxes and tubes, as triangles.

The track is a ribbon and the buildings are extruded outlines; a bicycle and
the person on it are neither. These are the two shapes everything else here is
made of - a box for a limb or a frame tube, a tube for a wheel or a crank - and
they are built rather than loaded, so a frozen application carries no model
file it could fail to find.

Each is made in its own local frame with its origin where a scene node would
want to hold it, so placing one is a position and a rotation and never a
correction for where the shape happens to sit.
"""

from __future__ import annotations

import math

from app.world.mesh import Mesh, TexCoord, Triangle, Vertex

#: How many flat sides a tube is drawn with. Enough that a wheel seen from ten
#: metres reads as round, few enough that a bicycle is not more triangles than
#: the circuit it is riding on.
TUBE_SIDES = 16


def _face_normal(a: Vertex, b: Vertex, c: Vertex) -> Vertex:
    """Which way three corners face, taken in the order they are wound."""
    first = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    second = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    cross = (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )
    length = math.sqrt(sum(part * part for part in cross))
    if length == 0.0:  # pragma: no cover - solids are built from real corners
        return (0.0, 0.0, 1.0)
    return (cross[0] / length, cross[1] / length, cross[2] / length)


def box(length: float, width: float, height: float) -> Mesh:
    """A rectangular solid, its origin at the middle of one end.

    Held at the end rather than the centre because everything made of these is
    a limb or a tube joined to something at one end: a thigh is placed at the
    hip and pointed at the knee.
    """
    half_w, half_h = width / 2.0, height / 2.0
    corners = [
        (0.0, -half_w, -half_h),
        (0.0, half_w, -half_h),
        (0.0, half_w, half_h),
        (0.0, -half_w, half_h),
        (length, -half_w, -half_h),
        (length, half_w, -half_h),
        (length, half_w, half_h),
        (length, -half_w, half_h),
    ]
    faces = (
        (0, 1, 2, 3),  # the near end
        (7, 6, 5, 4),  # the far end
        (0, 4, 5, 1),
        (1, 5, 6, 2),
        (2, 6, 7, 3),
        (3, 7, 4, 0),
    )
    vertices: list[Vertex] = []
    tex_coords: list[TexCoord] = []
    triangles: list[Triangle] = []
    normals: list[Vertex] = []
    for face in faces:
        first = len(vertices)
        corner_points = [corners[corner] for corner in face]
        vertices += corner_points
        tex_coords += [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        # Its own normal per face, so the six sides of a box take the light
        # differently and it reads as a solid rather than a silhouette.
        normals += [_face_normal(*corner_points[:3])] * 4
        triangles += [
            (first, first + 1, first + 2),
            (first, first + 2, first + 3),
        ]
    return Mesh(tuple(vertices), tuple(tex_coords), tuple(triangles), tuple(normals))


def tube(
    length: float, radius: float, sides: int = TUBE_SIDES, hollow: bool = False
) -> Mesh:
    """A cylinder along +X, its origin at the middle of one end.

    `hollow` leaves the ends open, which is what a wheel rim wants: a wheel is
    seen edge-on as often as not and a capped one reads as a drum.
    """
    ring = [
        (
            radius * math.cos(math.tau * step / sides),
            radius * math.sin(math.tau * step / sides),
        )
        for step in range(sides)
    ]
    vertices: list[Vertex] = []
    tex_coords: list[TexCoord] = []
    triangles: list[Triangle] = []
    normals: list[Vertex] = []
    for step in range(sides):
        y1, z1 = ring[step]
        y2, z2 = ring[(step + 1) % sides]
        first = len(vertices)
        vertices += [
            (0.0, y1, z1),
            (0.0, y2, z2),
            (length, y2, z2),
            (length, y1, z1),
        ]
        # Straight out from the axis, so a tube shades round rather than in
        # flat strips.
        normals += [
            (0.0, y1 / radius, z1 / radius),
            (0.0, y2 / radius, z2 / radius),
            (0.0, y2 / radius, z2 / radius),
            (0.0, y1 / radius, z1 / radius),
        ]
        left, right = step / sides, (step + 1) / sides
        tex_coords += [(left, 0.0), (right, 0.0), (right, 1.0), (left, 1.0)]
        triangles += [
            (first, first + 1, first + 2),
            (first, first + 2, first + 3),
        ]
    if not hollow:
        for end, x in ((0, 0.0), (1, length)):
            centre = len(vertices)
            facing = (1.0 if end else -1.0, 0.0, 0.0)
            vertices.append((x, 0.0, 0.0))
            tex_coords.append((0.5, 0.5))
            normals.append(facing)
            for step in range(sides):
                vertices.append((x, *ring[step]))
                tex_coords.append((0.5, 0.5))
                normals.append(facing)
            for step in range(sides):
                here = centre + 1 + step
                after = centre + 1 + (step + 1) % sides
                triangles.append(
                    (centre, here, after) if end else (centre, after, here)
                )
    return Mesh(tuple(vertices), tuple(tex_coords), tuple(triangles), tuple(normals))
