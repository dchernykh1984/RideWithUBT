"""One ride: sensors in, a rider moving through the world out.

The loop is short and worth stating plainly. Every step, the hub says how hard
the rider is pushing, the track under them says how steep it is, the physics says
how fast that makes them go, and the navigator moves them that far.

**Speed is computed, never read.** A trainer reports the speed of its own flywheel,
which is a fact about the trainer and not about the virtual course: believing it
would leave the gradient doing nothing, so a climb would cost effort and change
no number the rider sees. Power is the input; speed is the result.

The air comes from the world too. Sokol sits about 650 m up, where the air is
five percent thinner than at sea level - worth the better part of a kilometre an
hour at 200 W, which is more than the difference between a good day and a bad
one. A world that does not say how high it is gets sea level.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.physics import Air, Bike, step_speed_ms
from app.sensors.hub import SensorHub
from app.world.navigation import Navigator, UpcomingJunction
from app.world.network import Point


@dataclass(frozen=True)
class RideState:
    """Everything a screen, a workout or a recorder needs about this instant."""

    elapsed_s: float
    distance_m: float
    speed_ms: float
    gradient: float
    point: Point
    heading_rad: float
    power_w: float
    power_estimated: bool
    cadence_rpm: float | None = None
    heart_rate_bpm: float | None = None
    upcoming: UpcomingJunction | None = None
    #: Where the rider is on the globe, when the world says where it is.
    latitude: float | None = None
    longitude: float | None = None

    @property
    def speed_kmh(self) -> float:
        return self.speed_ms * 3.6

    @property
    def has_sensors(self) -> bool:
        """False when nothing is connected and the rider is standing still."""
        return self.power_w > 0.0 or self.cadence_rpm is not None


class RideSession:
    """A ride in progress."""

    def __init__(
        self,
        navigator: Navigator,
        hub: SensorHub | None = None,
        bike: Bike | None = None,
        air: Air | None = None,
    ) -> None:
        self.navigator = navigator
        self.hub = hub or SensorHub()
        self.bike = bike or Bike()
        #: None means "whatever the air is where the rider is", which is what a
        #: world with a real elevation should give them. A fixed value is for
        #: tests and for anyone who wants to hold one thing still.
        self.air = air
        self.fixed_air = air is not None
        self.speed_ms = 0.0
        self.elapsed_s = 0.0

    @property
    def distance_m(self) -> float:
        return self.navigator.travelled_m

    def air_here(self, elevation_m: float) -> Air:
        """The air at the rider's own height, unless one was fixed for them."""
        if self.air is not None:
            return self.air
        return Air.at_altitude(elevation_m)

    def update(self, seconds: float, now: float) -> RideState:
        """Advance the ride by one step and report where it got to."""
        snapshot = self.hub.snapshot(now)
        power = snapshot.power
        watts = power.value if power is not None else 0.0
        gradient = self.navigator.gradient

        self.speed_ms = step_speed_ms(
            self.speed_ms,
            watts,
            gradient,
            seconds,
            self.bike,
            self.air_here(self.navigator.point.z),
        )
        self.elapsed_s += seconds
        self.navigator.advance(self.speed_ms * seconds)

        cadence = snapshot.cadence
        heart_rate = snapshot.heart_rate
        point = self.navigator.point
        coordinate = self.navigator.network.coordinate(point)
        return RideState(
            elapsed_s=self.elapsed_s,
            distance_m=self.distance_m,
            speed_ms=self.speed_ms,
            gradient=gradient,
            point=point,
            heading_rad=self.navigator.heading_rad,
            latitude=coordinate[0] if coordinate else None,
            longitude=coordinate[1] if coordinate else None,
            power_w=watts,
            power_estimated=power.estimated if power is not None else False,
            cadence_rpm=cadence.value if cadence is not None else None,
            heart_rate_bpm=heart_rate.value if heart_rate is not None else None,
            upcoming=self.navigator.upcoming,
        )
