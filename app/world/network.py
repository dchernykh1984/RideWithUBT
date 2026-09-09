"""The track network: segments, nodes and the graph they form.

A segment is a one-way run of track between two nodes, described by the points
it passes through. Nodes are where segments meet; a node with more than one exit
is a junction, and which exit the rider takes is decided by them, in advance.

Points carry elevation as well as position, so a gradient is a property of the
track rather than something the physics has to be told separately.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from functools import cached_property
from itertools import pairwise

from app.world.geo import Origin

# How much track a gradient is measured across. Short enough that a real ramp is
# still felt where it starts, long enough that the elevation model's metre of
# rounding is not a hill.
GRADIENT_BASELINE_M = 20.0


class NetworkError(ValueError):
    """A network that does not describe a track anyone could ride."""


@dataclass(frozen=True)
class Point:
    """A point on the track surface, in metres, in the world's local frame."""

    x: float
    y: float
    z: float = 0.0

    def distance_to(self, other: Point) -> float:
        return math.dist((self.x, self.y, self.z), (other.x, other.y, other.z))


@dataclass(frozen=True)
class Segment:
    """A one-way run of track from one node to another.

    ``points`` includes both ends. ``width_m`` is the drivable width, which the
    renderer needs and the rider never leaves - there is no steering model here,
    only which branch to take.
    """

    id: str
    start_node: str
    end_node: str
    points: tuple[Point, ...]
    width_m: float = 10.0
    surface: str = "asphalt"

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise NetworkError(f"segment {self.id!r} needs at least two points")
        if self.length_m <= 0.0:
            raise NetworkError(f"segment {self.id!r} has no length")

    @cached_property
    def cumulative_m(self) -> tuple[float, ...]:
        """Distance from the start of the segment at each point."""
        distances = [0.0]
        for previous, current in pairwise(self.points):
            distances.append(distances[-1] + previous.distance_to(current))
        return tuple(distances)

    @cached_property
    def length_m(self) -> float:
        return self.cumulative_m[-1]

    def point_at(self, distance_m: float) -> Point:
        """Where the rider is, interpolated between the described points."""
        clamped = min(max(distance_m, 0.0), self.length_m)
        marks = self.cumulative_m
        index = _segment_index(marks, clamped)
        before, after = self.points[index], self.points[index + 1]
        span = marks[index + 1] - marks[index]
        if span <= 0.0:  # pragma: no cover - duplicate points are filtered on build
            return before
        fraction = (clamped - marks[index]) / span
        return Point(
            x=before.x + (after.x - before.x) * fraction,
            y=before.y + (after.y - before.y) * fraction,
            z=before.z + (after.z - before.z) * fraction,
        )

    def gradient_at(
        self, distance_m: float, baseline_m: float = GRADIENT_BASELINE_M
    ) -> float:
        """The slope under the rider, as a fraction: 0.05 is a five percent climb.

        Measured over a fixed length of track rather than between whichever two
        described points happen to be adjacent. How far apart those points are is
        a fact about how the circuit was mapped - three metres in one corner and
        eight hundred down a straight - and dividing a height difference by three
        metres turns the elevation model's rounding into a wall.
        """
        half = baseline_m / 2
        middle = min(max(distance_m, 0.0), self.length_m)
        low = max(0.0, middle - half)
        high = min(self.length_m, middle + half)
        if high <= low:  # pragma: no cover - a segment always has length
            return 0.0
        before, after = self.point_at(low), self.point_at(high)
        run = math.dist((before.x, before.y), (after.x, after.y))
        if run <= 0.0:  # pragma: no cover - a vertical step is not a track
            return 0.0
        return (after.z - before.z) / run

    def heading_at(self, distance_m: float) -> float:
        """Which way the track is pointing, in radians, for the camera to follow."""
        clamped = min(max(distance_m, 0.0), self.length_m)
        index = _segment_index(self.cumulative_m, clamped)
        before, after = self.points[index], self.points[index + 1]
        return math.atan2(after.y - before.y, after.x - before.x)


def _segment_index(marks: Sequence[float], distance_m: float) -> int:
    """Which pair of points a distance falls between."""
    for index in range(len(marks) - 1):
        if distance_m <= marks[index + 1]:
            return index
    # Callers clamp to the segment's length, so this is only reached if that ever
    # stops being true; the last pair is the right answer either way.
    return len(marks) - 2  # pragma: no cover


@dataclass(frozen=True)
class Junction:
    """A node with more than one way out.

    ``default_exit`` is the segment taken unless the rider says otherwise - the
    big ring, where the two share a node. ``announce_m`` is how far ahead the
    choice is shown; a fast approach deserves more warning than a slow one, so it
    belongs to the junction rather than being one number for the whole world.
    """

    node: str
    exits: tuple[str, ...]
    default_exit: str
    announce_m: float = 150.0

    def __post_init__(self) -> None:
        if len(self.exits) < 2:
            raise NetworkError(f"junction at {self.node!r} has nothing to choose from")
        if self.default_exit not in self.exits:
            raise NetworkError(
                f"junction at {self.node!r} defaults to {self.default_exit!r}, "
                "which is not one of its exits"
            )


@dataclass(frozen=True)
class Route:
    """A named way round the network, for the rider to pick before starting."""

    id: str
    name: str
    start_segment: str
    # Which exit to prefer at each junction; anything unlisted uses the default.
    choices: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Start:
    """Where a rider is put when a ride begins.

    Deliberately not the same thing as a route's `start_segment`, which is
    where a *lap* is measured from. At an autodrome a session begins in the
    pits and the lap is the circuit; conflating the two would either put the
    rider on the track when they should be rolling out of a box, or count the
    pit lane as part of a lap that does not include it.
    """

    segment_id: str
    offset_m: float = 0.0


@dataclass(frozen=True)
class TrackNetwork:
    """Every segment of a world, and how they join.

    ``origin`` is where the world's (0, 0) sits on the globe. It is what lets a
    position in the world be written back out as a coordinate - into a ride
    recording, most of all - so a world without one records no positions rather
    than recording wrong ones.
    """

    id: str
    name: str
    segments: tuple[Segment, ...]
    junctions: tuple[Junction, ...] = ()
    routes: tuple[Route, ...] = ()
    origin: Origin | None = None
    #: Where a ride begins, when the world says. Without one a rider starts at
    #: the beginning of the first segment, which is wherever the data happened
    #: to start - fine for a test world, arbitrary for a real place.
    start: Start | None = None

    def __post_init__(self) -> None:
        self._check()

    def _check(self) -> None:
        ids = [segment.id for segment in self.segments]
        if len(ids) != len(set(ids)):
            raise NetworkError(f"world {self.id!r} has two segments with one id")
        for junction in self.junctions:
            for exit_id in junction.exits:
                if exit_id not in self.by_id:
                    raise NetworkError(
                        f"junction at {junction.node!r} leaves by {exit_id!r}, "
                        "which is not a segment"
                    )
        for route in self.routes:
            if route.start_segment not in self.by_id:
                raise NetworkError(
                    f"route {route.id!r} starts on {route.start_segment!r}, "
                    "which is not a segment"
                )
        if self.start is not None:
            if self.start.segment_id not in self.by_id:
                raise NetworkError(
                    f"world {self.id!r} starts on {self.start.segment_id!r}, "
                    "which is not a segment"
                )
            length = self.by_id[self.start.segment_id].length_m
            if not 0.0 <= self.start.offset_m <= length:
                raise NetworkError(
                    f"world {self.id!r} starts {self.start.offset_m:.0f} m along "
                    f"{self.start.segment_id!r}, which is {length:.0f} m long"
                )

    @cached_property
    def by_id(self) -> dict[str, Segment]:
        return {segment.id: segment for segment in self.segments}

    @cached_property
    def junction_by_node(self) -> dict[str, Junction]:
        return {junction.node: junction for junction in self.junctions}

    @cached_property
    def exits_by_node(self) -> dict[str, tuple[str, ...]]:
        """Every segment leaving each node, junction or not."""
        exits: dict[str, list[str]] = {}
        for segment in self.segments:
            exits.setdefault(segment.start_node, []).append(segment.id)
        return {node: tuple(leaving) for node, leaving in exits.items()}

    def coordinate(self, point: Point) -> tuple[float, float] | None:
        """Where a point in this world is on the globe, if the world says."""
        if self.origin is None:
            return None
        return self.origin.to_global(point.x, point.y)

    def segment(self, segment_id: str) -> Segment:
        try:
            return self.by_id[segment_id]
        except KeyError:
            raise NetworkError(f"unknown segment {segment_id!r}") from None

    def route(self, route_id: str) -> Route:
        for route in self.routes:
            if route.id == route_id:
                return route
        raise NetworkError(f"unknown route {route_id!r}")

    def junction_at(self, node: str) -> Junction | None:
        return self.junction_by_node.get(node)

    def exit_from(self, node: str, preferred: str | None = None) -> str | None:
        """Which segment to continue onto, or None at a dead end.

        A junction's chosen exit is honoured; anywhere else the only way out is
        taken, and where a node has several exits but no junction declared, the
        first is used so a network with a missing junction still rides.
        """
        leaving = self.exits_by_node.get(node, ())
        if not leaving:
            return None
        if preferred is not None and preferred in leaving:
            return preferred
        junction = self.junction_at(node)
        if junction is not None:
            return junction.default_exit
        return leaving[0]

    def __iter__(self) -> Iterator[Segment]:
        return iter(self.segments)

    @property
    def total_length_m(self) -> float:
        return sum(segment.length_m for segment in self.segments)
