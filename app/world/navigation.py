"""Moving along the network, and choosing at junctions.

The rider is never steering. They are on the racing line, they cannot crash and
they cannot miss a turn by reacting late. The only decision is which branch to
take, it is made in advance, and it is shown the whole time it is open:

* a junction announces itself while it is still ahead, with an arrow pointing at
  the exit currently selected - the default, which is the route's choice or the
  junction's own;
* left and right move the selection to the neighbouring exit, geometrically:
  left picks the one further anticlockwise from the way the rider is already
  going, right the one further clockwise;
* whichever exit the arrow points at when the rider reaches the node is the one
  they take, and the selection then resets for the next junction.

Ordering the exits by angle rather than by their order in the file is what makes
left mean left. A world with three ways out of a node needs no special case.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from app.world.network import Junction, NetworkError, Point, Route, TrackNetwork


class Steer(Enum):
    LEFT = -1
    RIGHT = 1


@dataclass(frozen=True)
class TrackPosition:
    segment_id: str
    distance_m: float


@dataclass(frozen=True)
class UpcomingJunction:
    """What the rider is being shown about the choice ahead."""

    node: str
    distance_m: float
    chosen_exit: str
    exits: tuple[str, ...]
    # Where to point the arrow, in radians relative to the way the rider is
    # facing: positive is to the left.
    bearing_rad: float

    @property
    def alternatives(self) -> int:
        return len(self.exits)


def normalise_angle(radians: float) -> float:
    """Fold an angle into [-pi, pi], so left and right stay meaningful.

    An exact half turn is equally far either way and comes back with whichever
    sign the rounding picks. That only arises for an exit doubling straight back
    on itself, which is not a junction anyone rides through.
    """
    return math.remainder(radians, 2 * math.pi)


class Navigator:
    """Where the rider is on the network, and where they are about to go."""

    def __init__(
        self,
        network: TrackNetwork,
        start_segment: str | None = None,
        route: Route | None = None,
    ) -> None:
        self.network = network
        self.route = route
        segment_id = start_segment or (
            route.start_segment if route else _first_segment(network)
        )
        network.segment(segment_id)
        self._segment_id = segment_id
        self._distance_m = 0.0
        self.travelled_m = 0.0
        self._chosen_exit: str | None = None
        self._arm_junction()

    # Where the rider is.

    @property
    def position(self) -> TrackPosition:
        return TrackPosition(self._segment_id, self._distance_m)

    @property
    def point(self) -> Point:
        return self.network.segment(self._segment_id).point_at(self._distance_m)

    @property
    def heading_rad(self) -> float:
        return self.network.segment(self._segment_id).heading_at(self._distance_m)

    @property
    def gradient(self) -> float:
        return self.network.segment(self._segment_id).gradient_at(self._distance_m)

    # The choice ahead.

    @property
    def upcoming(self) -> UpcomingJunction | None:
        """The junction being announced, or None when there is nothing to decide."""
        segment = self.network.segment(self._segment_id)
        junction = self.network.junction_at(segment.end_node)
        if junction is None or self._chosen_exit is None:
            return None
        remaining = segment.length_m - self._distance_m
        if remaining > junction.announce_m:
            return None
        order = self.exit_order(junction)
        return UpcomingJunction(
            node=junction.node,
            distance_m=remaining,
            chosen_exit=self._chosen_exit,
            exits=order,
            bearing_rad=self._bearing_to(self._chosen_exit),
        )

    def exit_order(self, junction: Junction) -> tuple[str, ...]:
        """The exits from leftmost to rightmost, as the rider approaches them."""
        return tuple(
            sorted(junction.exits, key=lambda exit_id: -self._bearing_to(exit_id))
        )

    def _bearing_to(self, exit_id: str) -> float:
        """How far the exit turns from the way the rider is already going."""
        segment = self.network.segment(self._segment_id)
        arriving = segment.heading_at(segment.length_m)
        leaving = self.network.segment(exit_id).heading_at(0.0)
        return normalise_angle(leaving - arriving)

    def steer(self, direction: Steer) -> str | None:
        """Move the selection one exit to the left or right.

        At the ends of the fan it stays put rather than wrapping: a rider holding
        left should end up on the leftmost exit and stay there, not flick back
        across to the far side.
        """
        segment = self.network.segment(self._segment_id)
        junction = self.network.junction_at(segment.end_node)
        if junction is None or self._chosen_exit is None:
            return None
        order = self.exit_order(junction)
        index = order.index(self._chosen_exit)
        moved = min(max(index + direction.value, 0), len(order) - 1)
        self._chosen_exit = order[moved]
        return self._chosen_exit

    def choose(self, exit_id: str) -> None:
        """Select an exit outright, for a menu or a test."""
        segment = self.network.segment(self._segment_id)
        junction = self.network.junction_at(segment.end_node)
        if junction is None or exit_id not in junction.exits:
            raise NetworkError(f"{exit_id!r} is not an exit of the junction ahead")
        self._chosen_exit = exit_id

    # Moving.

    def advance(self, metres: float) -> TrackPosition:
        """Move the rider forward, crossing as many nodes as the distance covers."""
        remaining = max(metres, 0.0)
        while remaining > 0.0:
            segment = self.network.segment(self._segment_id)
            room = segment.length_m - self._distance_m
            if remaining < room:
                self._distance_m += remaining
                self.travelled_m += remaining
                break
            self._distance_m = segment.length_m
            self.travelled_m += room
            remaining -= room
            if not self._cross(segment.end_node):
                break
        return self.position

    def _cross(self, node: str) -> bool:
        """Take the selected exit. False at a dead end, where the rider stops."""
        chosen = self._chosen_exit
        self._chosen_exit = None
        next_segment = self.network.exit_from(node, preferred=chosen)
        if next_segment is None:
            return False
        self._segment_id = next_segment
        self._distance_m = 0.0
        self._arm_junction()
        return True

    def _arm_junction(self) -> None:
        """Pre-select the default exit for whatever junction this segment ends at."""
        segment = self.network.segment(self._segment_id)
        junction = self.network.junction_at(segment.end_node)
        if junction is None:
            self._chosen_exit = None
            return
        preferred = self.route.choices.get(junction.node) if self.route else None
        self._chosen_exit = (
            preferred if preferred in junction.exits else junction.default_exit
        )


def _first_segment(network: TrackNetwork) -> str:
    if not network.segments:
        raise NetworkError(f"world {network.id!r} has no segments to start on")
    return network.segments[0].id


def lap_segments(network: TrackNetwork, route: Route) -> tuple[str, ...]:
    """The segments of one lap of a route, in the order they are ridden.

    Walked rather than ridden: following the route's choices from its start
    segment until it comes back gives the exact lap, where stepping a simulated
    rider round it would only give an answer as fine as the step.

    A configuration that does not close - a point-to-point course, or a network
    with a mistake in it - returns what it managed before running out.
    """
    start = route.start_segment
    order = [start]
    seen = {start}
    node = network.segment(start).end_node
    while True:
        next_id = network.exit_from(node, preferred=route.choices.get(node))
        if next_id is None or next_id in seen:
            return tuple(order)
        order.append(next_id)
        seen.add(next_id)
        node = network.segment(next_id).end_node


def lap_length_m(network: TrackNetwork, route: Route) -> float:
    """How long one lap of a route is."""
    return sum(
        network.segment(segment_id).length_m
        for segment_id in lap_segments(network, route)
    )
