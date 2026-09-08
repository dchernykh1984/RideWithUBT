from __future__ import annotations

import math

import pytest

from app.world.network import (
    Junction,
    NetworkError,
    Point,
    Route,
    Segment,
    TrackNetwork,
)
from tests.worlds import climbing_network, forked_network, line, loop_network


def test_length_is_the_sum_of_the_gaps_between_points() -> None:
    segment = line("l", "a", "b", [(0, 0, 0), (30, 40, 0), (30, 40, 0.0)])

    assert segment.length_m == pytest.approx(50.0)


def test_a_position_is_interpolated_between_the_described_points() -> None:
    segment = line("l", "a", "b", [(0, 0, 0), (100, 0, 0), (100, 100, 0)])

    assert segment.point_at(50.0) == Point(50.0, 0.0, 0.0)
    assert segment.point_at(150.0) == Point(100.0, 50.0, 0.0)


def test_a_position_past_either_end_is_clamped_to_the_track() -> None:
    """Overshoot is handled by the navigator; the geometry never extrapolates."""
    segment = line("l", "a", "b", [(0, 0, 0), (100, 0, 0)])

    assert segment.point_at(-10.0) == Point(0.0, 0.0, 0.0)
    assert segment.point_at(500.0) == Point(100.0, 0.0, 0.0)


def test_gradient_is_rise_over_run_not_over_distance() -> None:
    climb = climbing_network().segment("climb")

    assert climb.gradient_at(50.0) == pytest.approx(0.1)


def test_a_flat_track_has_no_gradient() -> None:
    assert line("l", "a", "b", [(0, 0, 0), (100, 0, 0)]).gradient_at(10.0) == 0.0


def test_heading_follows_the_track() -> None:
    segment = line("l", "a", "b", [(0, 0, 0), (100, 0, 0), (100, 100, 0)])

    assert segment.heading_at(50.0) == pytest.approx(0.0)
    assert segment.heading_at(150.0) == pytest.approx(math.pi / 2)


def test_a_segment_needs_two_points_and_some_length() -> None:
    with pytest.raises(NetworkError, match="at least two points"):
        Segment(id="l", start_node="a", end_node="b", points=(Point(0, 0),))
    with pytest.raises(NetworkError, match="no length"):
        Segment(id="l", start_node="a", end_node="b", points=(Point(0, 0), Point(0, 0)))


def test_the_network_indexes_its_segments_and_junctions() -> None:
    network = forked_network()

    assert network.segment("approach").start_node == "start"
    assert network.junction_at("fork") is not None
    assert network.junction_at("start") is None
    assert network.total_length_m == pytest.approx(800.0)
    assert [segment.id for segment in network] == [
        "approach",
        "straight",
        "left",
        "right",
    ]


def test_exits_are_indexed_by_the_node_they_leave() -> None:
    network = forked_network()

    assert network.exits_by_node["fork"] == ("straight", "left", "right")
    assert network.exits_by_node["start"] == ("approach",)


def test_asking_for_something_that_is_not_there() -> None:
    network = forked_network()

    with pytest.raises(NetworkError, match="unknown segment"):
        network.segment("nonesuch")
    with pytest.raises(NetworkError, match="unknown route"):
        network.route("nonesuch")


def test_routes_are_looked_up_by_id() -> None:
    assert forked_network().route("left-route").choices == {"fork": "left"}


def test_a_dead_end_has_no_exit() -> None:
    assert forked_network().exit_from("finish") is None


def test_the_only_way_out_is_taken_without_asking() -> None:
    assert forked_network().exit_from("start") == "approach"


def test_a_junction_falls_back_to_its_default() -> None:
    assert forked_network().exit_from("fork") == "straight"


def test_a_chosen_exit_is_honoured() -> None:
    assert forked_network().exit_from("fork", preferred="left") == "left"


def test_a_choice_that_does_not_leave_this_node_is_ignored() -> None:
    assert forked_network().exit_from("fork", preferred="approach") == "straight"


def test_a_node_with_several_exits_and_no_junction_still_rides() -> None:
    """A generator that forgot to declare a junction should not strand the rider."""
    network = TrackNetwork(
        id="undeclared",
        name="Undeclared fork",
        segments=(
            line("in", "a", "b", [(0, 0, 0), (100, 0, 0)]),
            line("one", "b", "c", [(100, 0, 0), (200, 0, 0)]),
            line("two", "b", "d", [(100, 0, 0), (100, 100, 0)]),
        ),
    )

    assert network.exit_from("b") == "one"


def test_two_segments_cannot_share_an_id() -> None:
    with pytest.raises(NetworkError, match="two segments with one id"):
        TrackNetwork(
            id="clash",
            name="Clash",
            segments=(
                line("same", "a", "b", [(0, 0, 0), (1, 0, 0)]),
                line("same", "b", "c", [(1, 0, 0), (2, 0, 0)]),
            ),
        )


def test_a_junction_must_leave_by_real_segments() -> None:
    with pytest.raises(NetworkError, match="not a segment"):
        TrackNetwork(
            id="bad",
            name="Bad",
            segments=(line("in", "a", "b", [(0, 0, 0), (1, 0, 0)]),),
            junctions=(Junction(node="b", exits=("in", "ghost"), default_exit="in"),),
        )


def test_a_junction_needs_something_to_choose_between() -> None:
    with pytest.raises(NetworkError, match="nothing to choose from"):
        Junction(node="b", exits=("only",), default_exit="only")


def test_a_junction_cannot_default_to_an_exit_it_does_not_have() -> None:
    with pytest.raises(NetworkError, match="not one of its exits"):
        Junction(node="b", exits=("a", "c"), default_exit="elsewhere")


def test_a_route_must_start_somewhere_real() -> None:
    with pytest.raises(NetworkError, match="not a segment"):
        TrackNetwork(
            id="bad",
            name="Bad",
            segments=(line("in", "a", "b", [(0, 0, 0), (1, 0, 0)]),),
            routes=(Route(id="r", name="R", start_segment="ghost"),),
        )


def test_a_closed_loop_leaves_every_node_by_exactly_one_way() -> None:
    network = loop_network()

    assert all(len(exits) == 1 for exits in network.exits_by_node.values())
    assert network.total_length_m == pytest.approx(400.0)
