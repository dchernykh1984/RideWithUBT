"""The rider you can see, and their legs going round.

A red triangle told you where you were and nothing else. A cyclist tells you
something a number cannot: whether you are turning the pedals, and how fast.

Everything here is worked out rather than drawn. The shape of the bicycle and
the rider is a handful of boxes and tubes in the bike's own side plane; the
legs follow the pedals by the same two-bone geometry a knee actually uses. The
renderer places what this produces and decides nothing, which is what lets a
pedal stroke be checked without a window.

Dimensions are a road bicycle's, in metres, measured from the bottom bracket:
they are what makes the figure read as a person on a bicycle rather than a
shape that happens to move.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: What a rider turns the pedals at when nothing is measuring it. Between the
#: 60-70 of somebody riding to the shops and the 90-100 of a racing cyclist:
#: this application is for training, and its rider is somewhere in between.
DEFAULT_CADENCE_RPM = 85.0

#: How high the bottom bracket sits above the road. Everything about the
#: figure is measured from the bottom bracket, so this is what puts the whole
#: thing on the tarmac instead of through it - without it the pedals swing
#: seventeen centimetres below the road at the bottom of every stroke.
BOTTOM_BRACKET_M = 0.27
#: A road wheel with a tyre on it, and how far apart the two are.
WHEEL_RADIUS_M = 0.34
WHEELBASE_M = 1.02
#: How far ahead of the bottom bracket the front axle sits. Nothing a rider
#: holds on to should be beyond it by more than the length of an extension.
FRONT_AXLE_M = 0.60

#: How wide a rider is, in metres. These are what a cyclist looks like from
#: behind, which is the view from the saddle and the one that was unreadable:
#: a narrow column of blocks, because the shoulders were as wide as the hips
#: and the legs almost touching.
SHOULDER_WIDTH_M = 0.42
HIP_WIDTH_M = 0.30
#: How far apart the pedals are - the q-factor of a road crankset - and so how
#: far apart the feet, and the knees, are.
FOOT_SPACING_M = 0.15

#: How much bend a leg keeps at the bottom of the stroke. A rider sets their
#: saddle so the knee never quite straightens, and one that does looks wrong.
KNEE_MARGIN_M = 0.02

#: Below this the pedals are stopped rather than turning slowly. A cadence
#: sensor reports small numbers as a wheel coasts to a halt, and legs still
#: going round on a bicycle nobody is pedalling is worse than legs held still.
STOPPED_RPM = 5.0


@dataclass(frozen=True)
class Joint:
    """A point in the bicycle's side plane: along the bike, and up from the
    bottom bracket."""

    along_m: float
    up_m: float

    def distance_to(self, other: Joint) -> float:
        return math.hypot(other.along_m - self.along_m, other.up_m - self.up_m)


@dataclass(frozen=True)
class LegPose:
    """Where one leg is at this moment: three points and two bones."""

    hip: Joint
    knee: Joint
    pedal: Joint


@dataclass(frozen=True)
class Posture:
    """How a rider sits on a particular bicycle.

    The same person on a time trial bicycle and sitting up on the hoods is two
    quite different shapes, and the difference is the whole reason one is
    faster than the other. Drawing them the same would say the choice does not
    matter, when it is worth six kilometres an hour.

    The torso is the same length in all of them - it is the same rider - so
    what changes is where the shoulders and the hands are.
    """

    bike_id: str
    hip: Joint
    shoulder: Joint
    hands: Joint
    #: Extensions to rest the forearms on, drawn ahead of the bars.
    aerobars: bool = False


#: The postures, from sitting up to a time trial bicycle. The lean angles are
#: the usual ones: about sixty-five degrees off horizontal sitting up, forty-
#: five on the hoods, and flat enough on a time trial bicycle that the back is
#: nearly level.
POSTURES: tuple[Posture, ...] = (
    Posture(
        "upright",
        hip=Joint(-0.12, 0.710),
        shoulder=Joint(0.13, 1.24),
        hands=Joint(0.46, 1.00),
    ),
    Posture(
        "road",
        hip=Joint(-0.10, 0.715),
        shoulder=Joint(0.31, 1.13),
        hands=Joint(0.64, 0.90),
    ),
    Posture(
        "road-drops",
        hip=Joint(-0.10, 0.715),
        shoulder=Joint(0.38, 1.05),
        hands=Joint(0.66, 0.72),
    ),
    Posture(
        "road-aerobars",
        hip=Joint(-0.06, 0.718),
        shoulder=Joint(0.47, 0.96),
        hands=Joint(0.74, 0.90),
        aerobars=True,
    ),
    Posture(
        "tt",
        hip=Joint(-0.02, 0.720),
        shoulder=Joint(0.54, 0.87),
        hands=Joint(0.78, 0.88),
        aerobars=True,
    ),
)


def posture(bike_id: str) -> Posture:
    """How a rider sits on this bicycle, or on a road one if it is not listed."""
    for known in POSTURES:
        if known.bike_id == bike_id:
            return known
    return next(known for known in POSTURES if known.bike_id == "road")


@dataclass(frozen=True)
class Rider:
    """The rider's dimensions. A bicycle is measured from its bottom bracket.

    The legs have to reach the pedal at its lowest, which for these numbers is
    0.90 m from the hip - so thigh plus shin is a little more than that and the
    knee stays bent all the way round, which is what a rider's does.
    """

    crank_m: float = 0.1725
    thigh_m: float = 0.45
    shin_m: float = 0.48
    #: Which bicycle they are on, which is what decides how they sit on it.
    bike_id: str = "road"

    @property
    def posture(self) -> Posture:
        return posture(self.bike_id)

    def __post_init__(self) -> None:
        # A margin, not just a reach: a leg that only just gets there locks
        # straight at the bottom of every stroke and looks like a mannequin.
        lowest = Joint(0.0, -self.crank_m).distance_to(self.hip) + KNEE_MARGIN_M
        if self.thigh_m + self.shin_m <= lowest:
            raise ValueError(
                f"a leg of {self.thigh_m + self.shin_m:.2f} m cannot reach a pedal "
                f"{lowest:.2f} m away at the bottom of the stroke"
            )

    @property
    def hip(self) -> Joint:
        return self.posture.hip

    def pedal_at(self, angle_rad: float) -> Joint:
        """Where a pedal is, with the crank at this angle.

        Zero is the crank straight forward, and the angle grows the way the
        cranks actually turn on a bicycle going forwards.
        """
        return Joint(
            self.crank_m * math.cos(angle_rad),
            self.crank_m * math.sin(angle_rad),
        )

    def leg_at(self, angle_rad: float) -> LegPose:
        """One leg, with its pedal at this crank angle."""
        pedal = self.pedal_at(angle_rad)
        return LegPose(
            hip=self.hip,
            knee=knee(self.hip, pedal, self.thigh_m, self.shin_m),
            pedal=pedal,
        )

    def legs(self, angle_rad: float) -> tuple[LegPose, LegPose]:
        """Both legs. The cranks are half a turn apart, which is why pedalling
        works at all."""
        return self.leg_at(angle_rad), self.leg_at(angle_rad + math.pi)


def knee(hip: Joint, pedal: Joint, thigh_m: float, shin_m: float) -> Joint:
    """Where the knee is, given where the hip and the pedal are.

    Two bones of fixed length between two known points: the knee is on both
    circles, so it is one of the two places they cross. A knee bends forwards,
    so it is the forward one - the other solution is a leg bending the wrong
    way, which is a thing to notice rather than to draw.
    """
    span = hip.distance_to(pedal)
    reach = thigh_m + shin_m
    if span >= reach:  # pragma: no cover - Rider refuses dimensions that do this
        # Straightened out and pointing at the pedal: as close as it can get.
        towards = (
            (pedal.along_m - hip.along_m) / span,
            (pedal.up_m - hip.up_m) / span,
        )
        return Joint(
            hip.along_m + towards[0] * thigh_m, hip.up_m + towards[1] * thigh_m
        )
    # How far along the hip-to-pedal line the knee sits, and how far off it.
    along = (span * span + thigh_m * thigh_m - shin_m * shin_m) / (2 * span)
    off = math.sqrt(max(thigh_m * thigh_m - along * along, 0.0))
    unit = ((pedal.along_m - hip.along_m) / span, (pedal.up_m - hip.up_m) / span)
    # The normal pointing forwards along the bike, which is the way a knee goes.
    normal = (-unit[1], unit[0])
    if normal[0] < 0:
        normal = (-normal[0], -normal[1])
    return Joint(
        hip.along_m + unit[0] * along + normal[0] * off,
        hip.up_m + unit[1] * along + normal[1] * off,
    )


@dataclass
class Cranks:
    """How far round the pedals have got.

    Kept as an angle that only ever grows with time, rather than worked out
    from distance travelled: a rider on a trainer can turn the pedals while the
    bicycle is held still, and can freewheel while it is moving.
    """

    angle_rad: float = 0.0

    def advance(self, seconds: float, cadence_rpm: float | None = None) -> float:
        """Turn the cranks for this long at this cadence, and say where they got.

        With no cadence sensor connected the rider turns them at a plain
        average, so the figure pedals rather than sitting frozen on a moving
        bicycle - which looks broken, and is the state most riders will see
        first.
        """
        turning = DEFAULT_CADENCE_RPM if cadence_rpm is None else cadence_rpm
        if turning < STOPPED_RPM:
            return self.angle_rad
        self.angle_rad = (self.angle_rad + turning * math.tau / 60.0 * seconds) % (
            math.tau
        )
        return self.angle_rad
