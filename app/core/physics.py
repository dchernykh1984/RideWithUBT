"""How many watts it takes to go how fast.

The standard cycling power model: what the rider puts into the pedals goes into
rolling resistance, gravity, pushing air out of the way, and whatever is left
over accelerates them.

    P = (Crr * m * g * cos(a) + m * g * sin(a) + 0.5 * rho * CdA * v^2) * v

The numbers here matter to a rider in a way most numbers in this project do not:
they decide whether the speed on screen matches the speed the same effort gives
outdoors. Every default below is a measured, quotable figure rather than one
picked to feel right, and each says where it comes from.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

GRAVITY_MS2 = 9.80665

# Air density at sea level, 15 degrees, in the international standard atmosphere.
SEA_LEVEL_DENSITY_KGM3 = 1.225
# The standard atmosphere's temperature lapse rate and the constants that go with
# it, for thinning the air with altitude - which is worth doing here, because a
# circuit outside Almaty sits some six hundred metres up and that is a couple of
# percent of drag.
LAPSE_RATE_KM = 0.0065
SEA_LEVEL_TEMPERATURE_K = 288.15
DENSITY_EXPONENT = 4.25588

# Below this the propulsive force P/v runs away to infinity, so a rider starting
# from a standstill is treated as already rolling this slowly.
MIN_SPEED_MS = 0.3
# What P/v says at walking pace is not what a bicycle can actually do: down there
# the limit is the torque the legs and the tyre can put down, not the power. A
# strong rider leaves the lights at about this, so that is the ceiling.
MAX_ACCELERATION_MS2 = 3.0
# Solving the cubic by bisection needs an upper bound. No cyclist gets here.
MAX_SPEED_MS = 40.0
BISECTION_STEPS = 60


@dataclass(frozen=True)
class VirtualBike:
    """The bicycle the rider is riding in the world, and the drag it costs.

    Weight decides how fast they climb; what they are riding, and how they sit
    on it, decides how fast they go on the flat - and on a circuit that is
    nearly all of it. A rider on clip-on bars is not a rider on a time trial
    bicycle, and neither is one on the hoods: between the ends of this list
    lies several kilometres an hour at the same effort.

    The figures are for a rider of about eighty kilograms; a larger rider
    pushes a larger hole, and any of them can be replaced by a number a rider
    measured for themselves.
    """

    id: str
    name: str
    cda_m2: float


#: What there is to ride. `road-aerobars` is measured, not quoted: it is what
#: came out of a real ride at this circuit - 8.9 km in 866 s at 266 W average,
#: a rider of 83 kg on a road bicycle with clip-on time trial bars, in air at
#: 645 m and 27 degrees. Solving that ride's whole energy budget for drag, with
#: rolling resistance at 0.005, gives 0.267 m2.
#:
#: The rest sit around it in the proportions the literature gives. A proper
#: time trial bicycle is lower again, because the frame and the rider's whole
#: position are built for it rather than a pair of bars being added to a road
#: bike - so the measured figure is emphatically not the one to use for it.
BIKES: tuple[VirtualBike, ...] = (
    VirtualBike("upright", "Sitting up", 0.40),
    VirtualBike("road", "Road bicycle, on the hoods", 0.32),
    VirtualBike("road-drops", "Road bicycle, in the drops", 0.29),
    VirtualBike("road-aerobars", "Road bicycle with time trial bars", 0.267),
    VirtualBike("tt", "Time trial bicycle", 0.23),
)
DEFAULT_BIKE = "road"

#: What a rider and a bicycle weigh when nobody has said. A road bicycle with
#: pedals, bottles and a bit of kit is about nine.
DEFAULT_RIDER_KG = 75.0
DEFAULT_BIKE_KG = 9.0


def virtual_bike(bike_id: str) -> VirtualBike:
    """The named bicycle, or the default when it is not one of them."""
    for known in BIKES:
        if known.id == bike_id:
            return known
    return next(known for known in BIKES if known.id == DEFAULT_BIKE)


@dataclass(frozen=True)
class Bike:
    """The rider and their bicycle, as the four numbers that decide their speed.

    ``cda_m2`` is frontal area times drag coefficient - see `BIKES`.
    ``crr`` is rolling resistance: about 0.005 for good tyres on smooth asphalt.
    ``drivetrain_efficiency`` is what survives the chain, which is a few percent.
    """

    total_mass_kg: float = DEFAULT_RIDER_KG + DEFAULT_BIKE_KG
    cda_m2: float = 0.32
    crr: float = 0.005
    drivetrain_efficiency: float = 0.975

    def __post_init__(self) -> None:
        if self.total_mass_kg <= 0:
            raise ValueError("a rider and bicycle have to weigh something")
        if not 0.0 < self.drivetrain_efficiency <= 1.0:
            raise ValueError("a drivetrain cannot return more than it is given")

    @classmethod
    def ridden_by(
        cls,
        rider_kg: float = DEFAULT_RIDER_KG,
        bike_kg: float = DEFAULT_BIKE_KG,
        bike_id: str = DEFAULT_BIKE,
        cda_m2: float | None = None,
        crr: float | None = None,
    ) -> Bike:
        """The bicycle a particular rider is on, as they described it.

        A measured `cda_m2` wins over the catalogue's figure, the same way a
        measured wheel rollout wins over the catalogue's: somebody who has been
        in a wind tunnel or done the maths knows better than a table.
        """
        return cls(
            total_mass_kg=rider_kg + bike_kg,
            cda_m2=cda_m2 if cda_m2 is not None else virtual_bike(bike_id).cda_m2,
            crr=crr if crr is not None else 0.005,
        )


@dataclass(frozen=True)
class Air:
    """The air being pushed out of the way."""

    density_kgm3: float = SEA_LEVEL_DENSITY_KGM3

    @classmethod
    def at_altitude(cls, metres: float, temperature_c: float = 15.0) -> Air:
        """Thinner air higher up, by the international standard atmosphere."""
        temperature_k = temperature_c + 273.15
        ratio = 1 - LAPSE_RATE_KM * metres / SEA_LEVEL_TEMPERATURE_K
        if ratio <= 0:  # pragma: no cover - above the stratosphere
            raise ValueError("that is not an altitude anyone rides at")
        density = (
            SEA_LEVEL_DENSITY_KGM3
            * ratio**DENSITY_EXPONENT
            * (SEA_LEVEL_TEMPERATURE_K / temperature_k)
        )
        return cls(density_kgm3=density)


# The air the model assumes when nobody says otherwise.
STANDARD_AIR = Air()


def resistance_n(speed_ms: float, gradient: float, bike: Bike, air: Air) -> float:
    """Everything holding the rider back, in newtons.

    ``gradient`` is rise over run, so a five percent climb is 0.05. The cosine and
    sine come from that as an angle: on anything a bicycle can climb the cosine is
    within a percent of one, but writing it out costs nothing and stops the model
    quietly breaking on a wall.
    """
    angle = math.atan(gradient)
    rolling = bike.crr * bike.total_mass_kg * GRAVITY_MS2 * math.cos(angle)
    gravity = bike.total_mass_kg * GRAVITY_MS2 * math.sin(angle)
    drag = 0.5 * air.density_kgm3 * bike.cda_m2 * speed_ms**2
    return rolling + gravity + drag


def power_needed_w(speed_ms: float, gradient: float, bike: Bike, air: Air) -> float:
    """The watts a rider must produce to hold this speed on this slope."""
    at_the_wheel = resistance_n(speed_ms, gradient, bike, air) * speed_ms
    return at_the_wheel / bike.drivetrain_efficiency


def steady_speed_ms(
    power_w: float, gradient: float, bike: Bike, air: Air = STANDARD_AIR
) -> float:
    """The speed a rider settles at holding this power on this slope.

    The relationship is a cubic in speed, and inverting it by bisection is both
    shorter and harder to get wrong than the closed form - which needs care with
    the sign of the discriminant on a descent.
    """
    if power_w <= 0.0:
        return 0.0
    low, high = 0.0, MAX_SPEED_MS
    for _ in range(BISECTION_STEPS):
        middle = (low + high) / 2
        if power_needed_w(middle, gradient, bike, air) < power_w:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def step_speed_ms(
    speed_ms: float,
    power_w: float,
    gradient: float,
    seconds: float,
    bike: Bike,
    air: Air = STANDARD_AIR,
) -> float:
    """Advance the speed by one time step, given the power being pushed.

    A rider who stops pedalling coasts down rather than stopping dead, and one who
    cannot hold a climb slows to a standstill rather than rolling backwards -
    there is no reverse on a virtual course.
    """
    effective = max(speed_ms, MIN_SPEED_MS)
    propulsion = power_w * bike.drivetrain_efficiency / effective
    resistance = resistance_n(effective, gradient, bike, air)
    acceleration = min(
        (propulsion - resistance) / bike.total_mass_kg, MAX_ACCELERATION_MS2
    )
    return max(0.0, speed_ms + acceleration * seconds)
