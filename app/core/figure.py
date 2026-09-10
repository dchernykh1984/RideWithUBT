"""The rider you can see, and their legs going round.

A red triangle told you where you were and nothing else. A cyclist tells you
something a number cannot: whether you are turning the pedals, and how fast.

Everything here is worked out rather than drawn: the shape of the bicycle and
the rider in the bike's own side plane, and the legs following the pedals by
the same two-bone geometry a knee actually uses. The renderer places what this
produces and decides nothing, which is what lets a pedal stroke be checked
without a window.

**None of the measurements are in this file.** They are in
`app/data/figure.json` - the frame as a list of tubes, the rider as a set of
lengths, and each bicycle as a posture. A figure is a set of measurements, and
measurements are data: changing how the rider looks is changing that file, the
same rule the worlds and the catalogues already follow.

Everything is measured from the bottom bracket, the axis the cranks turn on,
with x along the bike and z up. That is what a bicycle is actually built
around, and the origin that puts the wheels on the road rather than through it.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import cache
from typing import Any

from app import paths


@cache
def described() -> dict[str, Any]:
    """The figure as it is written down, read once."""
    return json.loads(paths.packaged("figure.json").read_text(encoding="utf-8"))


def _bicycle(key: str) -> Any:
    return described()["bicycle"][key]


def _rider(key: str) -> Any:
    return described()["rider"][key]


def colour(name: str) -> tuple[float, float, float, float]:
    """A colour from the description, as the renderer wants it."""
    red, green, blue = described()["colours"][name]
    return (float(red), float(green), float(blue), 1.0)


#: What a rider turns the pedals at when nothing is measuring it. Between the
#: 60-70 of somebody riding to the shops and the 90-100 of a racing cyclist:
#: this application is for training, and its rider is somewhere in between.
DEFAULT_CADENCE_RPM: float = float(_rider("default_cadence_rpm"))

#: How high the bottom bracket sits above the road. Everything about the
#: figure is measured from the bottom bracket, so this is what puts the whole
#: thing on the tarmac instead of through it - without it the pedals swing
#: seventeen centimetres below the road at the bottom of every stroke.
BOTTOM_BRACKET_M: float = float(_bicycle("bottom_bracket_m"))
#: A road wheel with a tyre on it, how far apart the two are, and how far
#: ahead of the cranks the front one sits.
WHEEL_RADIUS_M: float = float(_bicycle("wheel_radius_m"))
WHEELBASE_M: float = float(_bicycle("wheelbase_m"))
FRONT_AXLE_M: float = float(_bicycle("front_axle_m"))

#: How wide a rider is. These are what a cyclist looks like from behind, which
#: is the view from the saddle and the one that was unreadable: a narrow column
#: of blocks, because the shoulders were as wide as the hips and the legs
#: almost touching.
SHOULDER_WIDTH_M: float = float(_rider("shoulder_width_m"))
HIP_WIDTH_M: float = float(_rider("hip_width_m"))
#: How far apart the pedals are - the q-factor of a road crankset - and so how
#: far apart the feet, and the knees, are.
FOOT_SPACING_M: float = float(_rider("foot_spacing_m"))

#: How much bend a leg keeps at the bottom of the stroke. A rider sets their
#: saddle so the knee never quite straightens, and one that does looks wrong.
KNEE_MARGIN_M: float = float(_rider("knee_margin_m"))

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
class Tube:
    """One tube of a frame: where it runs, and how fat it is."""

    name: str
    start: Joint
    end: Joint
    thickness_m: float


def frame_tubes() -> tuple[Tube, ...]:
    """The bicycle, as the tubes it is welded from."""
    return tuple(
        Tube(
            name=str(tube.get("name", "tube")),
            start=Joint(*tube["from"]),
            end=Joint(*tube["to"]),
            thickness_m=float(tube["thickness"]),
        )
        for tube in _bicycle("tubes")
    )


@dataclass(frozen=True)
class LegPose:
    """Where one leg is at this moment: three points and two bones."""

    hip: Joint
    knee: Joint
    pedal: Joint
    #: Which way the foot is pointing, in radians above horizontal. An ankle
    #: is a joint too: a foot bolted rigidly to the pedal is the thing that
    #: makes a pedalling figure look like a machine.
    foot_rad: float = 0.0


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
    #: How far apart the hands are. On the bars they are shoulder width; on
    #: extensions they are almost touching, which is the point of them.
    hand_spacing_m: float = 0.20
    #: Extensions to rest the forearms on, drawn ahead of the bars.
    aerobars: bool = False


def _postures() -> tuple[Posture, ...]:
    return tuple(
        Posture(
            bike_id=str(item["bike_id"]),
            hip=Joint(*item["hip"]),
            shoulder=Joint(*item["shoulder"]),
            hands=Joint(*item["hands"]),
            hand_spacing_m=float(item.get("hand_spacing_m", 0.20)),
            aerobars=bool(item.get("aerobars", False)),
        )
        for item in described()["postures"]
    )


POSTURES: tuple[Posture, ...] = _postures()
DEFAULT_BIKE = "road"


def posture(bike_id: str) -> Posture:
    """How a rider sits on this bicycle, or on a road one if it is not listed."""
    for known in POSTURES:
        if known.bike_id == bike_id:
            return known
    return next(known for known in POSTURES if known.bike_id == DEFAULT_BIKE)


@dataclass(frozen=True)
class Rider:
    """The rider's own dimensions, and which bicycle they are on.

    The legs have to reach the pedal at its lowest with something left to bend
    with, which is what a rider sets their saddle height for.
    """

    crank_m: float = float(_rider("crank_m"))
    thigh_m: float = float(_rider("thigh_m"))
    shin_m: float = float(_rider("shin_m"))
    foot_m: float = float(_rider("foot_m"))
    #: How far the ankle swings through the stroke, in degrees.
    ankle_swing_deg: float = float(_rider("ankle_swing_deg"))
    upper_arm_m: float = float(_rider("upper_arm_m"))
    forearm_m: float = float(_rider("forearm_m"))
    #: Which bicycle they are on, which is what decides how they sit on it.
    bike_id: str = DEFAULT_BIKE

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

    def ankle_at(self, angle_rad: float) -> float:
        """Which way the foot points, in radians above horizontal.

        A rider's ankle is not locked. The heel drops through the top of the
        stroke and the toe points down over the bottom of it, by about fifteen
        degrees either way - small, and the difference between a person
        pedalling and a linkage going round.
        """
        return math.radians(self.ankle_swing_deg) * math.sin(angle_rad - math.pi / 2)

    def leg_at(self, angle_rad: float) -> LegPose:
        """One leg, with its pedal at this crank angle."""
        pedal = self.pedal_at(angle_rad)
        return LegPose(
            hip=self.hip,
            knee=knee(self.hip, pedal, self.thigh_m, self.shin_m),
            pedal=pedal,
            foot_rad=self.ankle_at(angle_rad),
        )

    def arm(self) -> tuple[Joint, Joint, Joint]:
        """Shoulder, elbow and hand, for the posture this rider is in."""
        posture = self.posture
        return (
            posture.shoulder,
            elbow(posture.shoulder, posture.hands, self.upper_arm_m, self.forearm_m),
            posture.hands,
        )

    def legs(self, angle_rad: float) -> tuple[LegPose, LegPose]:
        """Both legs. The cranks are half a turn apart, which is why pedalling
        works at all."""
        return self.leg_at(angle_rad), self.leg_at(angle_rad + math.pi)


def knee(hip: Joint, pedal: Joint, thigh_m: float, shin_m: float) -> Joint:
    """Where the knee is, given where the hip and the pedal are.

    A knee bends forwards, so of the two places the circles cross it is the
    forward one; the other solution is a leg bending the wrong way, which is a
    thing to notice rather than to draw.
    """
    return _bend(hip, pedal, thigh_m, shin_m, towards=(1.0, 0.0))


def elbow(shoulder: Joint, hand: Joint, upper_m: float, fore_m: float) -> Joint:
    """Where the elbow is, given where the shoulder and the hand are.

    Downwards, which is where a rider's elbows go on every bicycle. Down
    rather than "away from the bars": with the arms nearly level, as they are
    on time trial extensions, away-from-the-bars puts the elbow above the
    shoulder and the arm over the rider's own head.

    It matters more than it sounds: an arm is nearly sixty centimetres from
    shoulder to wrist and a rider's hands are forty from their shoulders, so
    the elbow is bent hard - and a straight line between the two is not an arm,
    it is a stick.
    """
    return _bend(shoulder, hand, upper_m, fore_m, towards=(0.0, -1.0))


def _bend(
    start: Joint,
    end: Joint,
    first_m: float,
    second_m: float,
    towards: tuple[float, float],
) -> Joint:
    """The joint between two bones of fixed length reaching from one point to
    another: it is on both circles, so it is one of the two places they cross.

    `towards` says which of the two - the one on that side of the line between
    the ends. A knee goes forwards along the bike; an elbow goes down.
    """
    hip, pedal, thigh_m, shin_m = start, end, first_m, second_m
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
    normal = (-unit[1], unit[0])
    if normal[0] * towards[0] + normal[1] * towards[1] < 0:
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
