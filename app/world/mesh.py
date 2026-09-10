"""Turning a track network into triangles.

Plain arrays of vertices, texture coordinates and indices - no Panda3D, no
graphics anything. The renderer turns these into a scene node; keeping the
arithmetic out here is what lets the shape of the track be tested without a
window, which matters because a mesh bug looks like a rendering bug and is
usually not one.

A segment becomes a ribbon: its centre line pushed out to each side by half the
track's width, and the resulting pairs of points joined into quads. The sideways
push reuses the same mitred offset the pit lane is built with, so the two edges
of the track stay parallel through corners instead of pinching.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

from app.world.buildings import Building
from app.world.network import Segment, TrackNetwork
from app.world.offset import offset_polyline
from app.world.polygon import triangulate

# How many metres of track one repeat of the surface texture covers.
DEFAULT_TEXTURE_LENGTH_M = 8.0

Vertex = tuple[float, float, float]
TexCoord = tuple[float, float]
Triangle = tuple[int, int, int]


@dataclass(frozen=True)
class Mesh:
    """A triangle mesh, ready to be handed to a renderer."""

    vertices: tuple[Vertex, ...]
    tex_coords: tuple[TexCoord, ...]
    triangles: tuple[Triangle, ...]
    #: Which way each vertex faces, for anything that is not a flat surface.
    #: The track and the ground are lit as if facing straight up and look
    #: right; a person on a bicycle lit that way is a flat cut-out, because
    #: every face of every box takes the same light.
    normals: tuple[Vertex, ...] | None = None

    def __post_init__(self) -> None:
        if len(self.vertices) != len(self.tex_coords):
            raise ValueError("every vertex needs a texture coordinate")
        if self.normals is not None and len(self.normals) != len(self.vertices):
            raise ValueError("every vertex needs a normal, or none of them do")

    @property
    def is_empty(self) -> bool:
        return not self.triangles

    def merged_with(self, other: Mesh) -> Mesh:
        """Append another mesh, shifting its indices to follow this one's."""
        shift = len(self.vertices)
        return Mesh(
            vertices=self.vertices + other.vertices,
            tex_coords=self.tex_coords + other.tex_coords,
            triangles=self.triangles
            + tuple((a + shift, b + shift, c + shift) for a, b, c in other.triangles),
            # Normals only survive if both sides have them: half a mesh lit one
            # way and half the other is worse than all of it lit flat.
            normals=(
                self.normals + other.normals
                if self.normals is not None and other.normals is not None
                else None
            ),
        )


EMPTY = Mesh(vertices=(), tex_coords=(), triangles=())


def ribbon(
    segment: Segment, texture_length_m: float = DEFAULT_TEXTURE_LENGTH_M
) -> Mesh:
    """One segment as a flat ribbon of its own width.

    Texture coordinates run across the ribbon and along it, so a surface texture
    repeats every ``texture_length_m`` however long the segment is - the same
    asphalt looks the same on a two hundred metre straight and a ten metre link.
    """
    half = segment.width_m / 2.0
    left = offset_polyline(segment.points, half)
    right = offset_polyline(segment.points, -half)
    along = segment.cumulative_m

    vertices: list[Vertex] = []
    tex_coords: list[TexCoord] = []
    for index, (edge_left, edge_right) in enumerate(zip(left, right, strict=True)):
        v = along[index] / texture_length_m
        vertices.append((edge_left.x, edge_left.y, edge_left.z))
        tex_coords.append((0.0, v))
        vertices.append((edge_right.x, edge_right.y, edge_right.z))
        tex_coords.append((1.0, v))

    triangles: list[Triangle] = []
    for first, _ in pairwise(range(len(left))):
        base = first * 2
        # Two triangles per quad, wound the same way so the surface faces up.
        triangles.append((base, base + 1, base + 3))
        triangles.append((base, base + 3, base + 2))

    return Mesh(
        vertices=tuple(vertices),
        tex_coords=tuple(tex_coords),
        triangles=tuple(triangles),
    )


def ground_plane(network: TrackNetwork, size_m: float, drop_m: float) -> Mesh:
    """A backdrop under a world, a touch below its lowest point.

    Below the *track*, not below zero. A circuit sits at whatever height its
    ground really is - Sokol is 645 m up - and a backdrop pinned to sea level
    would leave the track floating in the sky above it, which is what happened
    the day the circuit stopped being flat.
    """
    half = size_m / 2.0
    lowest = min(
        (point.z for segment in network.segments for point in segment.points),
        default=0.0,
    )
    height = lowest - drop_m
    return Mesh(
        vertices=(
            (-half, -half, height),
            (half, -half, height),
            (half, half, height),
            (-half, half, height),
        ),
        tex_coords=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
        triangles=((0, 1, 2), (0, 2, 3)),
    )


#: How many metres of wall one repeat of the wall texture covers, across and up.
WALL_TEXTURE_M = 4.0


def building_mesh(building: Building) -> Mesh:
    """One building: four walls to a side, and a flat roof.

    The walls are the easy part - each edge of the footprint becomes a
    rectangle. The roof is a polygon and a graphics card draws triangles, so it
    is cut up properly rather than fanned from the middle: the pit garages here
    are an L, and a fan would put roof outside the building.
    """
    base = building.base_m
    top = base + building.height_m
    outline = [(point.x, point.y) for point in building.footprint]
    if len(outline) > 1 and outline[0] == outline[-1]:
        outline = outline[:-1]
    vertices: list[Vertex] = []
    tex_coords: list[TexCoord] = []
    triangles: list[Triangle] = []

    along = 0.0
    for (x1, y1), (x2, y2) in pairwise([*outline, outline[0]]):
        width = math.hypot(x2 - x1, y2 - y1)
        if width < 0.01:
            continue
        first = len(vertices)
        left, right = along / WALL_TEXTURE_M, (along + width) / WALL_TEXTURE_M
        high = building.height_m / WALL_TEXTURE_M
        vertices += [(x1, y1, base), (x2, y2, base), (x2, y2, top), (x1, y1, top)]
        tex_coords += [(left, 0.0), (right, 0.0), (right, high), (left, high)]
        # Both windings, so a wall is solid whichever side it is seen from -
        # cheaper than working out which way a surveyed footprint runs.
        triangles += [
            (first, first + 1, first + 2),
            (first, first + 2, first + 3),
            (first + 2, first + 1, first),
            (first + 3, first + 2, first),
        ]
        along += width

    roof_start = len(vertices)
    for x, y in outline:
        vertices.append((x, y, top))
        tex_coords.append((x / WALL_TEXTURE_M, y / WALL_TEXTURE_M))
    for a, b, c in triangulate(outline):
        triangles.append((roof_start + a, roof_start + b, roof_start + c))
        triangles.append((roof_start + c, roof_start + b, roof_start + a))

    return Mesh(tuple(vertices), tuple(tex_coords), tuple(triangles))


def buildings_mesh(network: TrackNetwork) -> Mesh:
    """Everything standing beside this track, in one mesh."""
    mesh = EMPTY
    for building in network.buildings:
        mesh = mesh.merged_with(building_mesh(building))
    return mesh


def network_mesh(
    network: TrackNetwork, texture_length_m: float = DEFAULT_TEXTURE_LENGTH_M
) -> Mesh:
    """Every segment of a world in one mesh.

    One mesh rather than one per segment because the whole surface shares a
    material, and a circuit is a few thousand triangles - small enough that
    handing the renderer a single node beats handing it a node per segment.
    """
    mesh = EMPTY
    for segment in network.segments:
        mesh = mesh.merged_with(ribbon(segment, texture_length_m))
    return mesh
