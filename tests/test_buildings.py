"""What stands beside the track, and how it gets there.

A circuit is not a ribbon of asphalt in an empty field. The thing that tells a
rider where they are on a lap is what is beside them - the pit garages, the
grandstand - and the world had none of it.

None of this is invented scenery. The footprints are surveyed, in the same
trace as the track itself, so the buildings stand where they really stand and
are the shape they really are.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import pytest

from app.world import solids
from app.world.buildings import (
    DEFAULT_HEIGHTS,
    Building,
    height_for,
    kind_of,
    sorted_by_size,
)
from app.world.description import load
from app.world.mesh import building_mesh, buildings_mesh
from app.world.network import Point
from app.world.polygon import signed_area, triangulate


def box(width: float = 10.0, depth: float = 6.0, base: float = 0.0) -> Building:
    return Building(
        id="b",
        kind="garage",
        footprint=(
            Point(0.0, 0.0, base),
            Point(width, 0.0, base),
            Point(width, depth, base),
            Point(0.0, depth, base),
        ),
        height_m=5.0,
    )


# Cutting an outline into triangles.


def test_a_rectangle_becomes_two_triangles() -> None:
    assert len(triangulate([(0, 0), (4, 0), (4, 2), (0, 2)])) == 2


def test_an_l_shape_is_cut_up_properly() -> None:
    """The pit garages here are an L, and a fan of triangles from the middle
    would put roof outside the building."""
    outline = [(0, 0), (6, 0), (6, 2), (2, 2), (2, 6), (0, 6)]

    triangles = triangulate(outline)

    assert len(triangles) == 4  # a polygon of n corners cuts into n - 2
    assert _area_of(outline, triangles) == pytest.approx(abs(signed_area(outline)))


def test_an_outline_drawn_the_other_way_round_still_works() -> None:
    clockwise = [(0, 2), (4, 2), (4, 0), (0, 0)]

    assert signed_area(clockwise) < 0
    assert len(triangulate(clockwise)) == 2


def test_a_closed_outline_does_not_grow_a_stray_triangle() -> None:
    """Open data repeats the first point at the end to close the ring."""
    closed = [(0, 0), (4, 0), (4, 2), (0, 2), (0, 0)]

    assert len(triangulate(closed)) == 2


def test_repeated_points_do_not_stall_the_cut() -> None:
    doubled = [(0, 0), (0, 0), (4, 0), (4, 2), (4, 2), (0, 2)]

    assert len(triangulate(doubled)) == 2


def test_something_that_is_not_a_polygon_gives_nothing() -> None:
    assert triangulate([(0, 0), (1, 1)]) == ()


def test_a_footprint_that_crosses_itself_gives_up_rather_than_hanging() -> None:
    """A bad footprint should cost a wonky roof, not a hung application."""
    bowtie = [(0, 0), (4, 4), (4, 0), (0, 4)]

    triangulate(bowtie)  # must simply return


def _area_of(
    outline: Sequence[tuple[float, float]],
    triangles: tuple[tuple[int, int, int], ...],
) -> float:
    total = 0.0
    for a, b, c in triangles:
        total += abs(signed_area([outline[a], outline[b], outline[c]]))
    return total


# What a building is.


def test_a_building_needs_an_outline_and_a_height() -> None:
    with pytest.raises(ValueError, match="no outline"):
        Building("b", "garage", (Point(0, 0, 0), Point(1, 0, 0)), 5.0)

    with pytest.raises(ValueError, match="no height"):
        Building("b", "garage", box().footprint, 0.0)


def test_a_building_stands_on_its_own_ground() -> None:
    """Not at zero: this circuit sits 645 m up."""
    standing = box(base=645.0)

    assert standing.base_m == 645.0
    assert standing.centre.z == 645.0


def test_how_wide_a_building_is() -> None:
    assert box(width=30.0, depth=8.0).span_m == 30.0


def test_the_biggest_come_first() -> None:
    ordered = sorted_by_size(
        [box(width=8.0, depth=4.0), box(width=50.0), box(width=20.0)]
    )

    assert [round(building.span_m) for building in ordered] == [50, 20, 8]


# What open data says a building is.


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"building": "grandstand"}, "grandstand"),
        ({"building": "garage"}, "garage"),
        ({"building": "hotel"}, "hotel"),
        ({"man_made": "tower"}, "tower"),
    ],
)
def test_the_kind_is_read_from_the_survey(tags: dict[str, str], expected: str) -> None:
    assert kind_of(tags) == expected


def test_building_yes_means_nobody_said_what_sort() -> None:
    """Which is most of them, so it is read as exactly that."""
    assert kind_of({"building": "yes"}) == "building"


def test_a_grandstand_is_not_a_garage() -> None:
    assert height_for("grandstand") > height_for("garage")


def test_a_world_may_say_how_tall_its_own_buildings_are() -> None:
    """Open data has the footprints and hardly ever the heights."""
    assert height_for("garage", {"garage": 12.0}) == 12.0


def test_a_kind_nobody_listed_gets_a_plain_building_height() -> None:
    assert height_for("lighthouse") == DEFAULT_HEIGHTS["building"]


# Turning one into triangles.


def test_a_building_gets_walls_and_a_roof() -> None:
    mesh = building_mesh(box())

    assert len(mesh.triangles) > 8
    tops = [vertex for vertex in mesh.vertices if vertex[2] == pytest.approx(5.0)]
    assert tops, "there is a roof"


def test_a_building_stands_up_from_its_base_to_its_height() -> None:
    mesh = building_mesh(box(base=645.0))

    heights = {round(vertex[2], 3) for vertex in mesh.vertices}

    assert heights == {645.0, 650.0}


def test_a_wall_is_solid_from_both_sides() -> None:
    """Cheaper than working out which way a surveyed footprint runs."""
    mesh = building_mesh(box())
    wall = mesh.triangles[:4]

    assert wall[0] == tuple(reversed(wall[2]))


def test_the_roof_covers_the_footprint() -> None:
    building = box(width=10.0, depth=6.0)

    mesh = building_mesh(building)
    roof = [
        (mesh.vertices[a], mesh.vertices[b], mesh.vertices[c])
        for a, b, c in mesh.triangles
        if all(mesh.vertices[corner][2] == pytest.approx(5.0) for corner in (a, b, c))
    ]
    covered = (
        sum(abs(signed_area([(v[0], v[1]) for v in triangle])) for triangle in roof)
        / 2  # each roof triangle is drawn both ways round
    )

    assert covered == pytest.approx(60.0)


def test_a_world_with_nothing_beside_it_makes_an_empty_mesh() -> None:
    from tests.worlds import loop_network

    assert buildings_mesh(loop_network()).triangles == ()


# The circuit a rider actually loads.


def test_sokol_has_the_buildings_that_are_really_there() -> None:
    network = load("sokol")

    kinds = {building.kind for building in network.buildings}

    assert len(network.buildings) >= 10
    assert "grandstand" in kinds
    assert "garage" in kinds


def test_the_pit_garages_stand_beside_the_pit_lane() -> None:
    """Not somewhere in a field: where a rider rolling out actually sees them."""
    network = load("sokol")
    lane = network.segment("pit-lane-0")
    garage = next(b for b in network.buildings if b.kind == "garage")

    nearest = min(
        math.hypot(garage.centre.x - point.x, garage.centre.y - point.y)
        for point in lane.points
    )

    assert nearest < 150.0


def test_the_buildings_stand_on_the_ground_the_track_is_on() -> None:
    """A building floating above the field, or sunk into it, is worse than one
    a metre out."""
    network = load("sokol")
    lowest_track = min(
        point.z for segment in network.segments for point in segment.points
    )

    for building in network.buildings:
        assert building.base_m == pytest.approx(lowest_track, abs=1.0)


def test_the_buildings_travel_with_the_map() -> None:
    """Everything about a map belongs in the map: there will be other maps."""
    import json

    from app.world import description

    raw = json.loads(
        (description.WORLDS_DIR / "sokol.json").read_text(encoding="utf-8")
    )

    assert len(raw["buildings"]) == len(load("sokol").buildings)
    assert raw["buildings"][0]["footprint"]
    assert raw["buildings"][0]["height_m"] > 0


def test_the_whole_circuit_is_a_reasonable_number_of_triangles() -> None:
    """Scenery that costs more than the track would be the wrong trade."""
    network = load("sokol")

    assert len(buildings_mesh(network).triangles) < 5000


# The solids everything that is not a road is made of.


def test_a_box_is_held_at_one_end() -> None:
    """Everything made of these is a limb or a frame tube joined to something
    at one end: a thigh is placed at the hip and pointed at the knee."""
    solid = solids.box(0.5, 0.1, 0.2)

    xs = [vertex[0] for vertex in solid.vertices]

    assert min(xs) == 0.0
    assert max(xs) == pytest.approx(0.5)


def test_a_box_is_the_size_it_was_asked_for() -> None:
    solid = solids.box(0.5, 0.1, 0.2)

    ys = [vertex[1] for vertex in solid.vertices]
    zs = [vertex[2] for vertex in solid.vertices]

    assert max(ys) - min(ys) == pytest.approx(0.1)
    assert max(zs) - min(zs) == pytest.approx(0.2)


def test_a_box_has_six_sides() -> None:
    assert len(solids.box(1.0, 1.0, 1.0).triangles) == 12


def test_every_face_of_a_box_faces_its_own_way() -> None:
    """A figure lit as if every surface pointed straight up is a flat cut-out."""
    solid = solids.box(1.0, 1.0, 1.0)

    assert solid.normals is not None
    assert len({tuple(normal) for normal in solid.normals}) == 6


def test_a_tube_is_round_about_its_axis() -> None:
    solid = solids.tube(0.2, 0.5, sides=24)

    for _, y, z in solid.vertices:
        assert math.hypot(y, z) == pytest.approx(0.5, abs=1e-9) or math.hypot(
            y, z
        ) == pytest.approx(0.0, abs=1e-9)


def test_a_tube_points_straight_out_from_its_axis() -> None:
    """So it shades round instead of in flat strips."""
    solid = solids.tube(0.2, 0.5, sides=8, hollow=True)

    assert solid.normals is not None
    for _, y, z in solid.normals:
        assert math.hypot(y, z) == pytest.approx(1.0, abs=1e-9)


def test_a_hollow_tube_has_no_ends() -> None:
    """A wheel is seen edge-on as often as not, and a capped one is a drum."""
    hollow = solids.tube(0.05, 0.34, sides=12, hollow=True)
    capped = solids.tube(0.05, 0.34, sides=12)

    assert len(hollow.triangles) == 24
    assert len(capped.triangles) == 24 + 24


def test_a_solid_carries_a_texture_coordinate_for_every_corner() -> None:
    for solid in (solids.box(1.0, 1.0, 1.0), solids.tube(1.0, 0.5)):
        assert len(solid.tex_coords) == len(solid.vertices)
        assert len(solid.normals or ()) == len(solid.vertices)


def test_a_mesh_with_the_wrong_number_of_normals_is_refused() -> None:
    from app.world.mesh import Mesh

    with pytest.raises(ValueError, match="normal"):
        Mesh(
            vertices=((0.0, 0.0, 0.0),),
            tex_coords=((0.0, 0.0),),
            triangles=(),
            normals=((0.0, 0.0, 1.0), (0.0, 0.0, 1.0)),
        )


def test_merging_keeps_normals_only_when_both_sides_have_them() -> None:
    """Half a mesh lit one way and half the other is worse than all of it flat."""
    solid = solids.box(1.0, 1.0, 1.0)
    flat = building_mesh(box())

    assert solid.merged_with(solid).normals is not None
    assert solid.merged_with(flat).normals is None


def test_a_sphere_is_round() -> None:
    """A box with a face on it is a box; the one part of a person that has to
    be round for them to read as a person is their head."""
    solid = solids.sphere(0.5, rings=6, sides=8)

    for x, y, z in solid.vertices:
        assert math.sqrt(x * x + y * y + z * z) == pytest.approx(0.5, abs=1e-9)


def test_a_sphere_points_out_of_itself() -> None:
    solid = solids.sphere(0.5, rings=6, sides=8)

    assert solid.normals is not None
    for normal in solid.normals:
        assert math.sqrt(sum(part * part for part in normal)) == pytest.approx(1.0)


def test_a_ring_is_flat_and_hollow() -> None:
    """A wheel's rim, seen from the side."""
    solid = solids.annulus(0.2, 0.34, sides=12)

    assert all(vertex[0] == 0.0 for vertex in solid.vertices)
    radii = {round(math.hypot(y, z), 6) for _, y, z in solid.vertices}
    assert radii == {0.2, 0.34}


def test_a_ring_is_drawn_from_both_sides() -> None:
    """A wheel is looked at from both sides and nothing about a rim tells them
    apart."""
    solid = solids.annulus(0.2, 0.34, sides=4)
    first, third = solid.triangles[0], solid.triangles[2]

    assert first == tuple(reversed(third))
