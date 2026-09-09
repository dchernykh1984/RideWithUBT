"""Other riders on the same track.

Riding with other people is meant to be possible one day, over a network, and
this is the shape that has to exist for it to be added rather than retrofitted:
somewhere for other riders to be, a way to say where they are, and a renderer
that draws whoever is there without asking where they came from.

The one source that exists now needs no network at all. A **pace partner** is a
rider holding a steady power round the circuit - the same physics, the same
track, the same junctions - which is useful on its own and, more to the point,
proves the machinery works. When a network source arrives it implements the same
protocol and nothing above it changes.

Nothing here knows about a server, and the application still works with the cable
pulled: with no companions, there is simply nobody else on the road.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # presence imports Companion from here; the arrow goes one way
    from app.core.presence import RiderState

from app.core.physics import STANDARD_AIR, Air, Bike, step_speed_ms
from app.world.navigation import Navigator
from app.world.network import Point, Route, TrackNetwork

#: Watts a pace partner will hold, when nobody says otherwise. Three groups, the
#: way a club ride splits: one to sit in with, one to work at, one to chase.
DEFAULT_PARTNER_WATTS = (150.0, 220.0, 290.0)


@dataclass(frozen=True)
class Companion:
    """Another rider, as everything else needs to see them."""

    id: str
    name: str
    point: Point
    heading_rad: float
    distance_m: float
    speed_ms: float
    power_w: float | None = None

    @property
    def speed_kmh(self) -> float:
        return self.speed_ms * 3.6


class CompanionSource(Protocol):
    """Where other riders come from. A network client is one of these."""

    def companions(self) -> Sequence[Companion]: ...

    def advance(self, seconds: float) -> None:
        """Move them on by one step of the ride."""
        ...

    def report(self, me: RiderState) -> None:
        """Take where *we* are, for sources that have somewhere to send it.

        A source that invents its riders locally has nowhere to send this and
        ignores it. A network client needs it, and asking every source for it
        is what keeps the ride from having to know which kind it is holding.
        """
        ...


@dataclass
class PacePartner:
    """One rider holding a steady power, going round on their own."""

    name: str
    power_w: float
    navigator: Navigator
    bike: Bike = field(default_factory=Bike)
    air: Air | None = None
    speed_ms: float = 0.0

    def advance(self, seconds: float) -> None:
        elevation = self.navigator.point.z
        air = self.air or Air.at_altitude(elevation)
        self.speed_ms = step_speed_ms(
            self.speed_ms,
            self.power_w,
            self.navigator.gradient,
            seconds,
            self.bike,
            air,
        )
        self.navigator.advance(self.speed_ms * seconds)

    def as_companion(self, identifier: str) -> Companion:
        return Companion(
            id=identifier,
            name=self.name,
            point=self.navigator.point,
            heading_rad=self.navigator.heading_rad,
            distance_m=self.navigator.travelled_m,
            speed_ms=self.speed_ms,
            power_w=self.power_w,
        )


@dataclass
class PacePartners:
    """A handful of steady riders to share the circuit with."""

    riders: tuple[PacePartner, ...] = ()

    @classmethod
    def holding(
        cls,
        network: TrackNetwork,
        watts: Sequence[float] = DEFAULT_PARTNER_WATTS,
        route: Route | None = None,
        bike: Bike | None = None,
    ) -> PacePartners:
        """Partners at the given powers, all starting where the rider does."""
        return cls(
            tuple(
                PacePartner(
                    name=f"{power:.0f} W",
                    power_w=power,
                    navigator=Navigator(network, route=route),
                    bike=bike or Bike(),
                )
                for power in watts
            )
        )

    def advance(self, seconds: float) -> None:
        for rider in self.riders:
            rider.advance(seconds)

    def companions(self) -> Sequence[Companion]:
        return tuple(
            rider.as_companion(f"partner-{number}")
            for number, rider in enumerate(self.riders)
        )

    def report(self, me: RiderState) -> None:
        """Nobody to tell: these riders are made up here and stay here."""
        return


@dataclass
class Peloton:
    """Several sources at once, because a road holds more than one kind of rider.

    A club ride with a pace partner to chase is two sources and one road, and
    everything above here should go on seeing one list of people.
    """

    sources: tuple[CompanionSource, ...] = ()

    def advance(self, seconds: float) -> None:
        for source in self.sources:
            source.advance(seconds)

    def report(self, me: RiderState) -> None:
        for source in self.sources:
            source.report(me)

    def companions(self) -> Sequence[Companion]:
        return tuple(
            companion for source in self.sources for companion in source.companions()
        )


@dataclass
class NoCompany:
    """Riding alone, which is what happens with the cable pulled."""

    def advance(self, seconds: float) -> None:
        return

    def companions(self) -> Sequence[Companion]:
        return ()

    def report(self, me: RiderState) -> None:
        return


def parse_partners(text: str) -> tuple[float, ...]:
    """Read a list of powers, as a rider would write it: `150,220,290`."""
    watts = []
    for piece in text.split(","):
        stripped = piece.strip()
        if not stripped:
            continue
        try:
            power = float(stripped)
        except ValueError:
            raise ValueError(f"{stripped!r} is not a number of watts") from None
        if not 0 < power <= 2000:
            raise ValueError(f"{power:.0f} W is not a pace anyone holds")
        watts.append(power)
    return tuple(watts)


def air_for(network: TrackNetwork) -> Air:
    """The air a companion rides in, which is the air of the world."""
    heights = [point.z for segment in network.segments for point in segment.points]
    if not heights:  # pragma: no cover - a world always has segments
        return STANDARD_AIR
    return Air.at_altitude(sum(heights) / len(heights))
