from __future__ import annotations

import math

import pytest

from app.world import description
from app.world.mesh import EMPTY, Mesh, ground_plane, network_mesh, ribbon
from app.world.network import Point, Segment
from tests.worlds import forked_network, line


def straight(width_m: float = 10.0, length_m: float = 100.0) -> Segment:
    return Segment(
        id="s",
        start_node="a",
        end_node="b",
        points=(Point(0, 0), Point(length_m, 0)),
        width_m=width_m,
    )


def area_of(mesh: Mesh) -> float:
    """Total area of every triangle, for checking a ribbon covers what it should."""
    total = 0.0
    for a, b, c in mesh.triangles:
        (ax, ay, _), (bx, by, _), (cx, cy, _) = (
            mesh.vertices[a],
            mesh.vertices[b],
            mesh.vertices[c],
        )
        total += abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay)) / 2.0
    return total


def test_a_straight_segment_is_one_quad() -> None:
    mesh = ribbon(straight())

    assert len(mesh.vertices) == 4
    assert len(mesh.triangles) == 2
    assert not mesh.is_empty


def test_the_ribbon_is_the_width_of_the_track() -> None:
    mesh = ribbon(straight(width_m=12.0))

    left, right = mesh.vertices[0], mesh.vertices[1]
    assert left[1] == pytest.approx(6.0)
    assert right[1] == pytest.approx(-6.0)


def test_the_ribbon_covers_the_area_of_the_track() -> None:
    mesh = ribbon(straight(width_m=12.0, length_m=250.0))

    assert area_of(mesh) == pytest.approx(12.0 * 250.0)


def test_a_corner_is_covered_without_pinching() -> None:
    """Offsetting each edge on its own would overlap or gap at the bend."""
    corner = line("c", "a", "b", [(0, 0, 0), (100, 0, 0), (100, 100, 0)])
    corner = Segment(
        id=corner.id,
        start_node=corner.start_node,
        end_node=corner.end_node,
        points=corner.points,
        width_m=10.0,
    )

    mesh = ribbon(corner)

    # Two quads of 100 m each, less the wedge the inside of the corner shares.
    assert area_of(mesh) == pytest.approx(10.0 * 200.0, rel=0.06)
    assert len(mesh.triangles) == 4


def test_the_texture_runs_across_and_along_the_track() -> None:
    mesh = ribbon(straight(length_m=100.0), texture_length_m=8.0)

    across = [u for u, _ in mesh.tex_coords]
    along = [v for _, v in mesh.tex_coords]
    assert across == [0.0, 1.0, 0.0, 1.0]
    assert along[0] == 0.0
    assert along[-1] == pytest.approx(100.0 / 8.0)


def test_the_texture_repeats_at_the_same_rate_on_any_length() -> None:
    """A short link and a long straight have to look like the same asphalt."""
    short = ribbon(straight(length_m=10.0), texture_length_m=8.0)
    long = ribbon(straight(length_m=400.0), texture_length_m=8.0)

    assert short.tex_coords[-1][1] == pytest.approx(10.0 / 8.0)
    assert long.tex_coords[-1][1] == pytest.approx(400.0 / 8.0)


def test_every_triangle_is_wound_the_same_way() -> None:
    """A triangle wound the other way faces down and vanishes when seen from above.

    Counter-clockwise seen from above is the up-facing winding, so the signed
    area of every triangle has to be positive.
    """
    mesh = ribbon(straight())

    for a, b, c in mesh.triangles:
        (ax, ay, _), (bx, by, _), (cx, cy, _) = (
            mesh.vertices[a],
            mesh.vertices[b],
            mesh.vertices[c],
        )
        cross = (bx - ax) * (cy - ay) - (cx - ax) * (by - ay)
        assert cross > 0, "the surface has to face up"


def test_a_climb_keeps_its_height() -> None:
    climb = Segment(
        id="c",
        start_node="a",
        end_node="b",
        points=(Point(0, 0, 0), Point(100, 0, 10)),
        width_m=10.0,
    )

    heights = {round(z, 3) for _, _, z in ribbon(climb).vertices}

    assert heights == {0.0, 10.0}


def test_merging_shifts_the_second_mesh_indices() -> None:
    one = ribbon(straight())

    merged = one.merged_with(one)

    assert len(merged.vertices) == 8
    assert len(merged.triangles) == 4
    assert max(index for triangle in merged.triangles for index in triangle) == 7
    assert area_of(merged) == pytest.approx(area_of(one) * 2)


def test_merging_onto_nothing_changes_nothing() -> None:
    one = ribbon(straight())

    assert EMPTY.merged_with(one) == one
    assert EMPTY.is_empty


def test_a_mesh_needs_a_texture_coordinate_for_every_vertex() -> None:
    with pytest.raises(ValueError, match="texture coordinate"):
        Mesh(vertices=((0, 0, 0),), tex_coords=(), triangles=())


def test_a_whole_network_becomes_one_mesh() -> None:
    network = forked_network()

    mesh = network_mesh(network)

    expected_quads = sum(len(segment.points) - 1 for segment in network.segments)
    assert len(mesh.triangles) == expected_quads * 2


def test_the_shipped_circuit_builds_a_mesh_of_a_sensible_size() -> None:
    """A few thousand triangles: small enough to hand the renderer in one node."""
    mesh = network_mesh(description.load("sokol"))

    assert 200 < len(mesh.triangles) < 20_000
    assert not any(math.isnan(value) for vertex in mesh.vertices for value in vertex)


def test_the_ground_sits_under_the_track_not_under_zero() -> None:
    """Sokol is 645 m up. A backdrop pinned to sea level leaves the track in the
    sky above it - which is exactly what a screenshot showed the day the circuit
    stopped being flat."""
    world = description.load("sokol")
    lowest = min(point.z for segment in world.segments for point in segment.points)

    ground = ground_plane(world, size_m=8000.0, drop_m=0.15)

    heights = {round(z, 3) for _, _, z in ground.vertices}
    assert heights == {round(lowest - 0.15, 3)}
    assert lowest > 600, "the circuit really is that high up"


def test_the_ground_covers_the_world_it_is_under() -> None:
    world = description.load("sokol")
    reach = max(
        abs(value)
        for segment in world.segments
        for point in segment.points
        for value in (point.x, point.y)
    )

    ground = ground_plane(world, size_m=8000.0, drop_m=0.15)

    assert min(x for x, _, _ in ground.vertices) < -reach
    assert max(x for x, _, _ in ground.vertices) > reach


def test_a_world_with_no_segments_still_gets_a_backdrop() -> None:
    from app.world.network import TrackNetwork

    ground = ground_plane(TrackNetwork(id="e", name="E", segments=()), 100.0, 0.5)

    assert {round(z, 3) for _, _, z in ground.vertices} == {-0.5}
