"""The circuit that ships, checked against what is known about the real one.

Sokol is drawn in OpenStreetMap as one closed way for the circuit and two short
ways for the alternatives, so its four published configurations fall out of the
generator rather than being written down anywhere. These tests are what say the
interpretation is right.
"""

from __future__ import annotations

import json
import math
from itertools import pairwise
from pathlib import Path

import pytest

from app.world import description
from app.world.description import world_path
from app.world.navigation import Navigator, lap_segments
from app.world.navigation import lap_length_m as lap_m
from app.world.network import TrackNetwork
from app.world.osm import build_from_files

WORLD_ID = "sokol"
BUILD_DATA = Path(__file__).resolve().parent.parent / "build-data" / WORLD_ID

# Sokol's published configurations, in metres. OpenStreetMap traces the centre of
# the track while a circuit is measured along its racing line, so the built world
# comes out consistently a little shorter; the tolerance below is that gap, and
# it is one-sided on purpose - a build that came out *longer* would mean
# something else had gone wrong.
PUBLISHED_M = {
    "big-ring": 4495,
    "big-ring-chicane": 4548,
    "small-ring": 3535,
    "small-ring-chicane": 3588,
}
SHORTFALL_LIMIT = 0.025


@pytest.fixture(scope="module")
def sokol() -> TrackNetwork:
    return description.load(WORLD_ID)


def test_the_shipped_world_is_what_the_tracked_inputs_produce(
    sokol: TrackNetwork,
) -> None:
    """Nobody can hand-edit the built world: it has to come from the extract."""
    rebuilt = build_from_files(
        BUILD_DATA / "recipe.json",
        BUILD_DATA / "overpass.json",
        BUILD_DATA / "elevation.json",
    )

    shipped = json.loads(world_path(WORLD_ID).read_text(encoding="utf-8"))
    assert description.describe(rebuilt) == shipped


def test_the_circuit_is_one_loop_with_its_alternatives(sokol: TrackNetwork) -> None:
    # Two racing alternatives - the small ring cut and the chicane - plus the
    # pit lane, which is a third place the rider can leave the circuit.
    assert len(sokol.junctions) == 3
    assert len(sokol.routes) == 4
    assert sokol.name == "Sokol International Racetrack"


def test_every_junction_offers_the_circuit_and_one_way_off_it(
    sokol: TrackNetwork,
) -> None:
    for junction in sokol.junctions:
        assert len(junction.exits) == 2
        assert junction.default_exit.startswith("main-"), (
            "the circuit proper has to be the default"
        )


@pytest.mark.parametrize("route_id", sorted(PUBLISHED_M))
def test_each_configuration_closes_and_measures_about_right(
    sokol: TrackNetwork, route_id: str
) -> None:
    route = sokol.route(route_id)
    built = lap_m(sokol, route)
    published = PUBLISHED_M[route_id]

    assert lap_segments(sokol, route)[0] == route.start_segment
    assert built <= published, "a lap longer than the published one means a wrong turn"
    assert built >= published * (1 - SHORTFALL_LIMIT)


def test_the_chicane_is_the_longer_way_round(sokol: TrackNetwork) -> None:
    plain = lap_m(sokol, sokol.route("big-ring"))
    chicane = lap_m(sokol, sokol.route("big-ring-chicane"))

    assert chicane > plain
    # The published pair differ by 53 m; the traced geometry should agree closely.
    assert chicane - plain == pytest.approx(53, abs=15)


def test_the_small_ring_cuts_about_a_kilometre_out(sokol: TrackNetwork) -> None:
    big = lap_m(sokol, sokol.route("big-ring"))
    small = lap_m(sokol, sokol.route("small-ring"))

    assert big - small == pytest.approx(960, abs=80)


def test_every_configuration_starts_at_the_same_place(sokol: TrackNetwork) -> None:
    """All four are laps of one circuit, so they share a start and finish."""
    starts = {route.start_segment for route in sokol.routes}

    assert len(starts) == 1


def test_a_lap_of_the_small_ring_skips_the_section_it_cuts(
    sokol: TrackNetwork,
) -> None:
    big = lap_segments(sokol, sokol.route("big-ring"))
    small = lap_segments(sokol, sokol.route("small-ring"))

    assert "small-ring-cut-0" in small
    assert "small-ring-cut-0" not in big
    assert set(small) - {"small-ring-cut-0"} < set(big)


def test_riding_it_comes_back_round(sokol: TrackNetwork) -> None:
    """The real check on the topology: ride two laps and end up where you began.

    Checked as a place rather than as a segment and an offset - after two laps of
    rounding, the rider is either just before the start line or just after it, and
    those are the same point on the track.
    """
    route = sokol.route("big-ring")
    # From the lap's own start, not from the pits: these are about the shape
    # of the circuit, and a session beginning in the pit lane is a different
    # question with its own tests.
    navigator = Navigator(sokol, start_segment=route.start_segment, route=route)
    start = navigator.point
    lap = lap_m(sokol, route)

    navigator.advance(lap * 2)

    assert navigator.point.distance_to(start) < 0.5
    assert navigator.travelled_m == pytest.approx(lap * 2)


def test_riding_past_the_line_carries_on_into_the_next_lap(
    sokol: TrackNetwork,
) -> None:
    route = sokol.route("big-ring")
    # From the lap's own start, not from the pits: these are about the shape
    # of the circuit, and a session beginning in the pit lane is a different
    # question with its own tests.
    navigator = Navigator(sokol, start_segment=route.start_segment, route=route)
    lap = lap_m(sokol, route)

    navigator.advance(lap + 100.0)

    assert navigator.position.segment_id == route.start_segment
    assert navigator.position.distance_m == pytest.approx(100.0, abs=0.5)


def test_the_track_is_wide_enough_to_race_on(sokol: TrackNetwork) -> None:
    """FIA grade 2 wants twelve metres; the extract has no width, so it is set."""
    racing = [s for s in sokol.segments if not s.id.startswith("pit-lane")]

    assert all(segment.width_m >= 12.0 for segment in racing)
    assert all(segment.surface == "asphalt" for segment in sokol.segments)


# The pit lane, which OpenStreetMap does not have for this circuit.


def test_the_pit_lane_runs_alongside_the_circuit(sokol: TrackNetwork) -> None:
    lane = sokol.segment("pit-lane-0")
    entry = sokol.segment(sokol.exit_from(lane.start_node) or "")

    assert lane.width_m == 8.0
    assert lane.length_m == pytest.approx(entry.length_m, rel=0.05)


def test_the_pit_lane_sits_beside_the_track_not_on_it(sokol: TrackNetwork) -> None:
    """Fourteen metres off the centre line clears a twelve metre wide track."""
    lane = sokol.segment("pit-lane-0")
    beside = sokol.segment(sokol.exit_from(lane.start_node) or "")

    gap = lane.point_at(lane.length_m / 2).distance_to(
        beside.point_at(beside.length_m / 2)
    )
    assert gap == pytest.approx(14.0, abs=1.0)


def test_the_circuit_runs_clockwise(sokol: TrackNetwork) -> None:
    """Which way round decides which side of the track everything is on.

    A refreshed extract with the way drawn the other way round would reverse the
    lap, and the pit lane would silently move to the other side of the track.
    """
    points = [
        point
        for segment in sokol.segments
        if segment.id.startswith("main-")
        for point in segment.points
    ]
    twice_area = sum(a.x * b.y - b.x * a.y for a, b in pairwise(points))

    assert twice_area < 0, "a clockwise loop encloses a negative signed area"


def test_the_pit_lane_is_on_the_left_of_the_track(sokol: TrackNetwork) -> None:
    """Where the maintainer says it is - and the circuit runs clockwise, so the
    left is the outside of the loop."""
    lane = sokol.segment("pit-lane-0")
    beside = sokol.segment(sokol.exit_from(lane.start_node) or "")

    middle = beside.length_m / 2
    on_track = beside.point_at(middle)
    heading = beside.heading_at(middle)
    towards_lane = lane.point_at(lane.length_m / 2)
    across = (towards_lane.x - on_track.x, towards_lane.y - on_track.y)
    # The left of a heading is that heading turned a quarter turn anticlockwise.
    left = (-math.sin(heading), math.cos(heading))

    assert across[0] * left[0] + across[1] * left[1] > 0


def test_the_pit_lane_is_a_choice_and_never_the_default(sokol: TrackNetwork) -> None:
    lane = sokol.segment("pit-lane-0")
    junction = sokol.junction_at(lane.start_node)

    assert junction is not None
    assert lane.id in junction.exits
    assert junction.default_exit != lane.id


def test_the_pit_lane_is_on_no_lap(sokol: TrackNetwork) -> None:
    """Riding a configuration must not send anyone through the pits."""
    for route in sokol.routes:
        assert "pit-lane-0" not in lap_segments(sokol, route)


def test_a_rider_can_turn_into_the_pits_and_come_back_out(
    sokol: TrackNetwork,
) -> None:
    """The whole point of the lane: leave the circuit, run through, rejoin it."""
    lane = sokol.segment("pit-lane-0")
    approach = next(
        segment
        for segment in sokol.segments
        if segment.end_node == lane.start_node and segment.id.startswith("main-")
    )
    navigator = Navigator(sokol, route=sokol.route("big-ring"))

    for _ in range(1000):
        if navigator.position.segment_id == approach.id:
            break
        navigator.advance(25.0)
    else:  # pragma: no cover - a lap is far shorter than this
        pytest.fail("never reached the pit entry")

    navigator.choose(lane.id)
    navigator.advance(approach.length_m)
    assert navigator.position.segment_id == lane.id

    navigator.advance(lane.length_m)
    assert navigator.position.segment_id.startswith("main-"), "the lane rejoins"


# The ground, which comes from an elevation model rather than from the extract.


def _lap_gradients(world: TrackNetwork) -> list[float]:
    route = world.route("big-ring")
    navigator = Navigator(world, route=route)
    gradients = []
    for _ in range(int(lap_m(world, route) / 5)):
        navigator.advance(5.0)
        gradients.append(navigator.gradient)
    return gradients


def test_the_circuit_sits_where_it_really_does(sokol: TrackNetwork) -> None:
    """Sokol is on a plain about 650 m up, and a recording of it says so."""
    heights = [point.z for segment in sokol.segments for point in segment.points]

    assert 600 < min(heights) < 700
    assert max(heights) - min(heights) < 15, "it is a plain, not a mountain"


def test_the_ground_is_gentle_enough_to_be_real(sokol: TrackNetwork) -> None:
    """The raw elevation model contains a 22% wall on this flat circuit.

    That is its own rounding, not terrain, and it would reach the rider's legs
    through a smart trainer. A circuit that rises and falls four metres cannot
    have a gradient like that anywhere on it.
    """
    gradients = [abs(gradient) for gradient in _lap_gradients(sokol)]

    assert max(gradients) < 0.02
    assert max(gradients) > 0.002, "and it is not flattened into nothing either"


def test_a_lap_climbs_something_but_not_much(sokol: TrackNetwork) -> None:
    route = sokol.route("big-ring")
    # From the lap's own start, not from the pits: these are about the shape
    # of the circuit, and a session beginning in the pit lane is a different
    # question with its own tests.
    navigator = Navigator(sokol, start_segment=route.start_segment, route=route)
    climb, last = 0.0, navigator.point.z
    for _ in range(int(lap_m(sokol, route) / 5)):
        navigator.advance(5.0)
        climb += max(0.0, navigator.point.z - last)
        last = navigator.point.z

    assert 2 < climb < 30, "a few metres a lap, as the ground there does"


def test_the_ground_makes_a_difference_worth_having(sokol: TrackNetwork) -> None:
    """If the slope changed nothing, modelling it would be decoration."""
    from app.core.physics import Bike, steady_speed_ms

    gradients = _lap_gradients(sokol)

    fastest = steady_speed_ms(200, min(gradients), Bike()) * 3.6
    slowest = steady_speed_ms(200, max(gradients), Bike()) * 3.6
    assert fastest - slowest > 5, "the same effort is worth several km/h either way"


def test_the_pit_lane_is_on_the_same_ground_as_the_track(
    sokol: TrackNetwork,
) -> None:
    """It runs beside the circuit, so it cannot be at a different height."""
    lane = sokol.segment("pit-lane-0")
    beside = sokol.segment(sokol.exit_from(lane.start_node) or "")

    assert abs(lane.points[0].z - beside.points[0].z) < 0.5
