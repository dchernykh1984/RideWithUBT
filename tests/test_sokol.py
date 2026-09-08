"""The circuit that ships, checked against what is known about the real one.

Sokol is drawn in OpenStreetMap as one closed way for the circuit and two short
ways for the alternatives, so its four published configurations fall out of the
generator rather than being written down anywhere. These tests are what say the
interpretation is right.
"""

from __future__ import annotations

import json
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
    rebuilt = build_from_files(BUILD_DATA / "recipe.json", BUILD_DATA / "overpass.json")

    shipped = json.loads(world_path(WORLD_ID).read_text(encoding="utf-8"))
    assert description.describe(rebuilt) == shipped


def test_the_circuit_is_one_loop_with_two_alternatives(sokol: TrackNetwork) -> None:
    assert len(sokol.junctions) == 2
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
    navigator = Navigator(sokol, route=route)
    start = navigator.point
    lap = lap_m(sokol, route)

    navigator.advance(lap * 2)

    assert navigator.point.distance_to(start) < 0.5
    assert navigator.travelled_m == pytest.approx(lap * 2)


def test_riding_past_the_line_carries_on_into_the_next_lap(
    sokol: TrackNetwork,
) -> None:
    route = sokol.route("big-ring")
    navigator = Navigator(sokol, route=route)
    lap = lap_m(sokol, route)

    navigator.advance(lap + 100.0)

    assert navigator.position.segment_id == route.start_segment
    assert navigator.position.distance_m == pytest.approx(100.0, abs=0.5)


def test_the_track_is_wide_enough_to_race_on(sokol: TrackNetwork) -> None:
    """FIA grade 2 wants twelve metres; the extract has no width, so it is set."""
    assert all(segment.width_m >= 12.0 for segment in sokol.segments)
    assert all(segment.surface == "asphalt" for segment in sokol.segments)


def test_the_circuit_is_flat_until_a_terrain_model_is_added(
    sokol: TrackNetwork,
) -> None:
    """Elevation is not in the extract. This test exists to be deleted."""
    assert all(point.z == 0.0 for segment in sokol.segments for point in segment.points)
