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

from dataclasses import dataclass
from itertools import pairwise

from app.world.network import Segment, TrackNetwork
from app.world.offset import offset_polyline

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

    def __post_init__(self) -> None:
        if len(self.vertices) != len(self.tex_coords):
            raise ValueError("every vertex needs a texture coordinate")

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
