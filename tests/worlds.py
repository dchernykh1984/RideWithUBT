"""A small network shared by the world tests.

Deliberately hand-drawn on a grid so every distance and angle in the assertions
can be checked by eye:

        n_top ---- top (west) ----+
          |                       |
      left_fork                   |
          |                       |
    start --- approach --> fork --+--- straight ---> finish
                            |
                            +---- right_fork ---> loop_back
"""

from __future__ import annotations

from app.world.network import Junction, Point, Route, Segment, TrackNetwork


def line(name: str, start: str, end: str, points: list[tuple[float, float, float]]):
    return Segment(
        id=name,
        start_node=start,
        end_node=end,
        points=tuple(Point(*point) for point in points),
    )


def forked_network() -> TrackNetwork:
    """One junction with three exits: hard left, straight on, and right."""
    return TrackNetwork(
        id="test-fork",
        name="Fork",
        segments=(
            # Heading due east along the x axis, 200 m of approach.
            line("approach", "start", "fork", [(0, 0, 0), (200, 0, 0)]),
            # Straight on, still east.
            line("straight", "fork", "finish", [(200, 0, 0), (400, 0, 0)]),
            # Left: north, which is a positive turn.
            line("left", "fork", "north", [(200, 0, 0), (200, 200, 0)]),
            # Right: south.
            line("right", "fork", "south", [(200, 0, 0), (200, -200, 0)]),
        ),
        junctions=(
            Junction(
                node="fork",
                exits=("straight", "left", "right"),
                default_exit="straight",
                announce_m=150.0,
            ),
        ),
        routes=(
            Route(id="default", name="Straight on", start_segment="approach"),
            Route(
                id="left-route",
                name="Left at the fork",
                start_segment="approach",
                choices={"fork": "left"},
            ),
        ),
    )


def climbing_network() -> TrackNetwork:
    """A single segment that rises ten metres over a hundred: a ten percent climb."""
    return TrackNetwork(
        id="test-climb",
        name="Climb",
        segments=(line("climb", "bottom", "top", [(0, 0, 0), (100, 0, 10)]),),
    )


def loop_network() -> TrackNetwork:
    """A closed square, so a rider can keep going without reaching an end."""
    return TrackNetwork(
        id="test-loop",
        name="Loop",
        segments=(
            line("north", "sw", "nw", [(0, 0, 0), (0, 100, 0)]),
            line("east", "nw", "ne", [(0, 100, 0), (100, 100, 0)]),
            line("south", "ne", "se", [(100, 100, 0), (100, 0, 0)]),
            line("west", "se", "sw", [(100, 0, 0), (0, 0, 0)]),
        ),
    )
