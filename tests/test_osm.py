from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.world import osm
from app.world.network import NetworkError

# A square circuit with one corner cut off, which is the shape every alternative
# racing configuration has: a main loop and a shorter way across it.
#
#   (0,1000) ----------- (1000,1000)
#       |        cut  \       |
#       |              \      |
#   (0,0) ------------- (1000,0)  <- start/finish at (0,0)
MAIN_NODES = [1, 2, 3, 4, 5, 1]
MAIN_COORDS = [
    (0.0000, 0.0000),
    (0.0000, 0.0090),
    (0.0045, 0.0090),
    (0.0090, 0.0090),
    (0.0090, 0.0000),
    (0.0000, 0.0000),
]
CUT_NODES = [2, 9, 4]
CUT_COORDS = [(0.0000, 0.0090), (0.0020, 0.0110), (0.0090, 0.0090)]


def extract() -> dict[int, osm.Way]:
    return {
        100: osm.Way(
            id=100,
            nodes=tuple(MAIN_NODES),
            coordinates=tuple(MAIN_COORDS),
            tags={"surface": "asphalt"},
        ),
        200: osm.Way(id=200, nodes=tuple(CUT_NODES), coordinates=tuple(CUT_COORDS)),
    }


def recipe(**overrides: object) -> osm.Recipe:
    fields: dict[str, object] = {
        "id": "square",
        "name": "Square",
        "main_way": 100,
        "links": {"cut": 200},
        "routes": (
            osm.RouteRecipe(id="full", name="Full lap"),
            osm.RouteRecipe(id="short", name="Short lap", links=("cut",)),
        ),
    }
    fields.update(overrides)
    return osm.Recipe(**fields)  # type: ignore[arg-type]


def test_a_way_needs_matching_nodes_and_geometry() -> None:
    with pytest.raises(NetworkError, match="different sizes"):
        osm.Way(id=1, nodes=(1, 2), coordinates=((0.0, 0.0),))


def test_a_way_needs_two_nodes() -> None:
    with pytest.raises(NetworkError, match="fewer than two nodes"):
        osm.Way(id=1, nodes=(1,), coordinates=((0.0, 0.0),))


def test_reading_an_extract_keeps_only_ways_with_geometry(tmp_path: Path) -> None:
    path = tmp_path / "extract.json"
    path.write_text(
        json.dumps(
            {
                "elements": [
                    {"type": "node", "id": 1, "lat": 0.0, "lon": 0.0},
                    {"type": "way", "id": 7},  # no geometry: an unresolved reference
                    {
                        "type": "way",
                        "id": 8,
                        "nodes": [1, 2],
                        "geometry": [
                            {"lat": 0.0, "lon": 0.0},
                            {"lat": 0.0, "lon": 0.001},
                        ],
                        "tags": {"highway": "raceway"},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    ways = osm.load_extract(path)

    assert list(ways) == [8]
    assert ways[8].tags["highway"] == "raceway"


def test_the_junctions_are_found_not_declared() -> None:
    """The recipe never says where the choices are; shared nodes say it."""
    network = osm.build(recipe(), extract())

    assert [junction.node for junction in network.junctions] == ["n2"]
    assert set(network.junction_at("n2").exits) == {"main-1", "cut-0"}  # type: ignore[union-attr]


def test_the_circuit_proper_is_the_default_at_every_junction() -> None:
    network = osm.build(recipe(), extract())

    junction = network.junction_at("n2")
    assert junction is not None
    assert junction.default_exit == "main-1"


def test_the_main_way_is_split_at_everything_that_joins_it() -> None:
    network = osm.build(recipe(), extract())

    main = [s.id for s in network.segments if s.id.startswith("main-")]
    assert main == ["main-0", "main-1", "main-2"]
    assert network.segment("main-0").start_node == "n1"
    assert network.segment("main-0").end_node == "n2"
    assert network.segment("main-2").end_node == "n1", "the loop closes"


def test_the_announce_distance_and_width_come_from_the_recipe() -> None:
    network = osm.build(recipe(width_m=15.0, announce_m=90.0), extract())

    assert network.segment("main-0").width_m == 15.0
    assert network.junction_at("n2").announce_m == 90.0  # type: ignore[union-attr]


def test_a_way_keeps_its_own_surface_over_the_recipe_default() -> None:
    network = osm.build(recipe(surface="concrete"), extract())

    assert network.segment("main-0").surface == "asphalt", "the way says asphalt"
    assert network.segment("cut-0").surface == "concrete", "the cut says nothing"


def test_routes_become_choices_at_the_junctions_they_pass() -> None:
    network = osm.build(recipe(), extract())

    assert network.route("full").choices == {}
    assert network.route("short").choices == {"n2": "cut-0"}
    assert network.route("short").start_segment == "main-0"


def test_a_closed_way_is_turned_to_begin_at_the_start_node() -> None:
    """A lap should be one run of segments, not a lap that wraps mid-segment."""
    network = osm.build(recipe(start_node=3), extract())

    assert network.segment("main-0").start_node == "n3"
    assert network.route("full").start_segment == "main-0"


def test_a_recipe_naming_a_way_that_is_not_in_the_extract() -> None:
    with pytest.raises(NetworkError, match="no way 999"):
        osm.build(recipe(links={"ghost": 999}), extract())


def test_a_route_taking_a_link_the_recipe_never_named() -> None:
    broken = recipe(routes=(osm.RouteRecipe(id="r", name="R", links=("nonesuch",)),))

    with pytest.raises(NetworkError, match="does not name"):
        osm.build(broken, extract())


def test_a_route_taking_a_link_that_branches_off_nowhere() -> None:
    """A way that touches the circuit at one end only is not a choice."""
    ways = extract()
    ways[300] = osm.Way(
        id=300, nodes=(500, 501), coordinates=((0.02, 0.02), (0.021, 0.021))
    )
    broken = recipe(
        links={"cut": 200, "stray": 300},
        routes=(osm.RouteRecipe(id="r", name="R", links=("stray",)),),
    )

    with pytest.raises(NetworkError, match="does not branch off"):
        osm.build(broken, ways)


def test_building_from_files(tmp_path: Path) -> None:
    (tmp_path / "recipe.json").write_text(
        json.dumps(
            {
                "id": "square",
                "name": "Square",
                "main_way": 100,
                "links": {"cut": 200},
                "routes": [{"id": "short", "name": "Short", "links": ["cut"]}],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "extract.json").write_text(
        json.dumps(
            {
                "elements": [
                    {
                        "type": "way",
                        "id": way.id,
                        "nodes": list(way.nodes),
                        "geometry": [
                            {"lat": lat, "lon": lon} for lat, lon in way.coordinates
                        ],
                        "tags": way.tags,
                    }
                    for way in extract().values()
                ]
            }
        ),
        encoding="utf-8",
    )

    network = osm.build_from_files(tmp_path / "recipe.json", tmp_path / "extract.json")
    origin = osm.describe_origin(tmp_path / "recipe.json", tmp_path / "extract.json")

    assert network.id == "square"
    assert network.route("short").choices == {"n2": "cut-0"}
    assert origin == {"lat": 0.0, "lon": 0.0}


# The pit lane, which open data usually does not have and the generator builds.


def pit(**overrides: object) -> osm.PitLane:
    fields: dict[str, object] = {
        "entry_node": 2,
        "exit_node": 3,
        "offset_m": -14.0,
    }
    fields.update(overrides)
    return osm.PitLane(**fields)  # type: ignore[arg-type]


def test_a_span_runs_forwards_along_the_way() -> None:
    way = extract()[100]

    assert osm.span(way, 2, 4) == [1, 2, 3]


def test_a_span_may_wrap_round_a_closed_way() -> None:
    """A pit lane can sit across the point where the mapper started drawing."""
    way = extract()[100]

    assert osm.span(way, 4, 2) == [3, 4, 0, 1]


def test_a_span_off_the_end_of_an_open_way_is_refused() -> None:
    way = extract()[200]

    with pytest.raises(NetworkError, match="does not run from"):
        osm.span(way, 4, 2)


def test_a_span_between_nodes_that_are_not_on_the_way() -> None:
    with pytest.raises(NetworkError, match="node 999 is not on way"):
        osm.span(extract()[100], 999, 2)


def test_the_pit_lane_becomes_a_segment_alongside_the_circuit() -> None:
    network = osm.build(recipe(pit_lane=pit(width_m=8.0)), extract())

    lane = network.segment("pit-lane-0")
    assert lane.start_node == "n2"
    assert lane.end_node == "n3"
    assert lane.width_m == 8.0
    # It runs beside the circuit, so it is about as long as the stretch it follows.
    beside = network.segment("main-1")
    assert lane.length_m == pytest.approx(beside.length_m, rel=0.05)


def test_turning_into_the_pit_lane_is_a_choice_like_any_other() -> None:
    network = osm.build(recipe(pit_lane=pit()), extract())

    junction = network.junction_at("n2")
    assert junction is not None
    assert "pit-lane-0" in junction.exits
    assert junction.default_exit == "main-1", "the circuit stays the default"


def test_the_pit_lane_rejoins_the_circuit() -> None:
    network = osm.build(recipe(pit_lane=pit()), extract())

    assert network.exit_from("n3") is not None
    assert network.segment("pit-lane-0").end_node == "n3"


def test_no_pit_lane_is_the_normal_case() -> None:
    network = osm.build(recipe(), extract())

    assert not [s for s in network.segments if s.id.startswith("pit")]


# The ground, which the extract does not carry.


def heights(**by_node: float) -> dict[int, float]:
    return {int(node.lstrip("n")): height for node, height in by_node.items()}


def test_without_elevation_a_world_is_flat() -> None:
    """Wrong, but not misleading - and it says so by being exactly zero."""
    network = osm.build(recipe(), extract())

    assert all(
        point.z == 0.0 for segment in network.segments for point in segment.points
    )


def test_sampled_ground_reaches_the_points() -> None:
    sampled = {node: 650.0 for node in (1, 2, 3, 4, 5, 9)}

    network = osm.build(recipe(), extract(), sampled)

    assert all(
        point.z == pytest.approx(650.0)
        for segment in network.segments
        for point in segment.points
    )


def test_a_branch_is_joined_to_the_circuit_at_both_ends() -> None:
    """Smoothed on its own it would drift, and leave a step at the junction."""
    sampled = {1: 650.0, 2: 652.0, 3: 654.0, 4: 656.0, 5: 652.0, 9: 700.0}

    network = osm.build(recipe(elevation_window_m=1.0), extract(), sampled)

    circuit_at_the_fork = network.segment("main-1").points[0]
    branch_at_the_fork = network.segment("cut-0").points[0]
    circuit_at_the_rejoin = network.segment("main-2").points[0]
    branch_at_the_rejoin = network.segment("cut-0").points[-1]
    assert branch_at_the_fork.z == pytest.approx(circuit_at_the_fork.z)
    assert branch_at_the_rejoin.z == pytest.approx(circuit_at_the_rejoin.z)


def test_a_node_the_model_never_sampled_sits_at_zero() -> None:
    """Missing is missing; inventing a height would be worse than admitting it."""
    network = osm.build(recipe(), extract(), {1: 650.0})

    assert network.segment("main-0").points[0].z == pytest.approx(650.0, abs=1.0)


def test_the_pit_lane_follows_the_ground_beside_it() -> None:
    sampled = {node: 640.0 + node for node in (1, 2, 3, 4, 5, 9)}
    network = osm.build(
        recipe(pit_lane=pit(), elevation_window_m=1.0), extract(), sampled
    )

    lane = network.segment("pit-lane-0")
    beside = network.segment("main-1")
    assert lane.points[0].z == pytest.approx(beside.points[0].z)


def test_reading_the_sampled_heights_from_a_file(tmp_path: Path) -> None:
    path = tmp_path / "elevation.json"
    path.write_text(
        json.dumps({"dataset": "srtm30m", "nodes": {"1": 650.5}}), encoding="utf-8"
    )

    assert osm.load_heights(path) == {1: 650.5}
