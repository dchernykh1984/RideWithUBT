"""Building the rider, and turning their legs.

The shapes and the pedal stroke are worked out elsewhere - `app/world/solids.py`
and `app/core/figure.py` - and neither needs a window. This puts them into the
scene graph and moves two bones per leg, which is all a renderer should be
doing.

The figure faces +X, which is the way a rider on this track faces before the
node is turned to their heading. Up is +Z, as everywhere else in this world.

Everything a person is made of is round: limbs are tubes, the head is a ball,
the body is a tube flattened into an oval. A cyclist built out of boxes reads
as a stack of boxes, which is what the first one did.
"""

from __future__ import annotations

import math

from panda3d.core import NodePath

from app.core.figure import (
    BOTTOM_BRACKET_M,
    FOOT_SPACING_M,
    HIP_WIDTH_M,
    SHOULDER_WIDTH_M,
    WHEEL_RADIUS_M,
    WHEELBASE_M,
    Joint,
    Rider,
)
from app.render.geometry import geom_node
from app.world.mesh import Mesh
from app.world.solids import annulus, box, sphere, tube

#: The colours the figure is drawn in. A rider has to be picked out at a glance
#: from a hundred metres, so the jersey is the team's orange.
JERSEY = (0.95, 0.42, 0.05, 1.0)
SHORTS = (0.13, 0.14, 0.18, 1.0)
SKIN = (0.85, 0.68, 0.55, 1.0)
BIKE = (0.16, 0.17, 0.20, 1.0)
TYRE = (0.09, 0.09, 0.10, 1.0)
#: A deep carbon rim, pale enough to be seen against the road. The wheels were
#: the part that vanished: a rim four centimetres wide is a hairline at any
#: distance, and a bicycle without visible wheels is a person floating.
RIM = (0.72, 0.74, 0.78, 1.0)

#: How thick each part of a rider is, in metres.
THIGH_M = 0.075
SHIN_M = 0.055
ARM_M = 0.045
HEAD_M = 0.105

#: A deep-section rim: how far in from the tyre the rim reaches, and how wide
#: the tyre itself is.
RIM_DEPTH_M = 0.055
TYRE_WIDTH_M = 0.030


class Cyclist:
    """A person on a bicycle, with legs that go round.

    Held together by the node it hangs from: place that at the rider's position
    and turn it to their heading, and everything below it follows.
    """

    def __init__(self, parent: NodePath, rider: Rider | None = None) -> None:
        self.rider = rider or Rider()
        self.root = parent.attachNewNode("cyclist")
        self._build_bicycle()
        self._build_body()
        self.bones = [
            (self._bone(THIGH_M, side), self._bone(SHIN_M, side))
            for side in (FOOT_SPACING_M / 2, -FOOT_SPACING_M / 2)
        ]
        self.feet = [
            self._part(box(0.24, 0.09, 0.05), SHORTS, "foot") for _ in range(2)
        ]
        self.pedal_at(0.0)

    # Putting it together. Everything is measured from the bottom bracket,
    # which is where the node's origin is.

    def _build_bicycle(self) -> None:
        posture = self.rider.posture
        axle = WHEEL_RADIUS_M - BOTTOM_BRACKET_M
        for along, front in ((-0.42, False), (WHEELBASE_M - 0.42, True)):
            self._wheel(along, axle, disc=posture.aerobars and not front)
        for start, end, thickness in (
            ((-0.42, axle), (0.0, 0.0), 0.035),  # chainstay
            ((-0.42, axle), (-0.06, 0.58), 0.028),  # seat stay
            ((0.0, 0.0), (-0.06, 0.62), 0.045),  # seat tube
            ((0.0, 0.0), (0.50, 0.50), 0.048),  # down tube
            ((-0.06, 0.60), (0.50, 0.50), 0.040),  # top tube
            ((0.50, 0.50), (WHEELBASE_M - 0.42, axle), 0.032),  # fork
            ((0.50, 0.50), (0.50, 0.58), 0.030),  # stem
        ):
            self._strut(Joint(*start), Joint(*end), thickness, BIKE)
        saddle = self._part(box(0.26, 0.07, 0.035), SHORTS, "saddle")
        saddle.setPos(-0.16, 0.0, posture.hip.up_m - 0.05)
        self._across(Joint(0.50, 0.58), 0.42, 0.028, BIKE, "bars")
        if posture.aerobars:
            # Extensions to rest the forearms on: most of what makes a time
            # trial position what it is.
            for side in (0.07, -0.07):
                extension = self._strut(Joint(0.50, 0.58), posture.hands, 0.025, BIKE)
                extension.setY(side)
        ring = self._part(annulus(0.04, 0.105), RIM, "chainring")
        ring.setHpr(90.0, 0.0, 0.0)
        ring.setY(-0.055)

    def _wheel(self, along: float, axle: float, disc: bool) -> None:
        """A wheel: a tyre, and either a deep rim or a solid disc.

        A disc wheel on the back of a time trial bicycle is a real thing and
        the most recognisable shape in cycling, so the bicycle a rider chose is
        visible from across the circuit.
        """
        tyre = self._part(tube(TYRE_WIDTH_M, WHEEL_RADIUS_M, hollow=True), TYRE, "tyre")
        tyre.setHpr(90.0, 0.0, 0.0)
        tyre.setPos(along, -TYRE_WIDTH_M / 2, axle)
        inner = 0.02 if disc else WHEEL_RADIUS_M - RIM_DEPTH_M
        for side in (0.012, -0.012):
            face = self._part(annulus(inner, WHEEL_RADIUS_M - 0.002), RIM, "rim")
            # An annulus is built across +X; a wheel stands across the bike,
            # the same way its tyre does.
            face.setHpr(90.0, 0.0, 0.0)
            face.setPos(along, side, axle)

    def _build_body(self) -> None:
        """A rider seen from behind is shoulders, a back, and two legs."""
        posture = self.rider.posture
        hip, shoulder = posture.hip, posture.shoulder
        # The back, as an oval rather than a slab: wide across, shallow deep.
        back = self._strut(hip, shoulder, 1.0, JERSEY, round_=True)
        back.setScale(back.getSx(), SHOULDER_WIDTH_M * 0.9, 0.22)
        self._across(hip, HIP_WIDTH_M, 0.16, SHORTS, "hips")
        self._across(shoulder, SHOULDER_WIDTH_M, 0.15, JERSEY, "shoulders")
        for side in (1.0, -1.0):
            arm = self._strut(
                Joint(shoulder.along_m, shoulder.up_m),
                posture.hands,
                ARM_M,
                SKIN,
                round_=True,
            )
            arm.setY(side * SHOULDER_WIDTH_M / 2 * 0.8)
        lean = math.atan2(shoulder.up_m - hip.up_m, shoulder.along_m - hip.along_m)
        head = self._part(sphere(HEAD_M), JERSEY, "head")
        head.setPos(
            shoulder.along_m + 0.16 * math.cos(lean),
            0.0,
            shoulder.up_m + 0.16 * math.sin(lean),
        )
        head.setScale(1.25, 0.9, 0.95)

    def _across(
        self,
        at: Joint,
        width: float,
        thickness: float,
        colour: tuple[float, ...],
        name: str,
    ) -> NodePath:
        """A tube lying across the bike: a pair of shoulders, or handlebars."""
        node = self._part(tube(width, thickness / 2.0), colour, name)
        node.setHpr(90.0, 0.0, 0.0)
        node.setPos(at.along_m, -width / 2.0, at.up_m)
        return node

    def _strut(
        self,
        start: Joint,
        end: Joint,
        thickness: float,
        colour: tuple[float, ...],
        round_: bool = False,
    ) -> NodePath:
        """A tube from one point to another in the bicycle's side plane."""
        length = start.distance_to(end)
        shape: Mesh = (
            tube(length, thickness / 2.0)
            if round_ or thickness < 0.06
            else box(length, thickness, thickness)
        )
        node = self._part(shape, colour, "strut")
        node.setPos(start.along_m, 0.0, start.up_m)
        _point_along(node, start, end)
        return node

    def _bone(self, thickness: float, side: float) -> NodePath:
        """One segment of a leg: placed and pointed afresh every frame."""
        node = self._part(tube(1.0, thickness), SKIN, "bone")
        node.setY(side)
        return node

    def _part(self, mesh: Mesh, colour: tuple[float, ...], name: str) -> NodePath:
        node = self.root.attachNewNode(geom_node(mesh, name))
        node.setColor(*colour)
        node.setTwoSided(True)
        return node

    # Moving it.

    def pedal_at(self, angle_rad: float) -> None:
        """Put the legs where this crank angle puts them."""
        legs = self.rider.legs(angle_rad)
        for leg, (thigh, shin) in zip(legs, self.bones, strict=True):
            _lay(thigh, leg.hip, leg.knee)
            _lay(shin, leg.knee, leg.pedal)
        for foot, leg in zip(self.feet, legs, strict=True):
            foot.setPos(leg.pedal.along_m - 0.10, foot.getY(), leg.pedal.up_m)

    def hide(self) -> None:
        self.root.hide()

    def show(self) -> None:
        self.root.show()


def _lay(node: NodePath, start: Joint, end: Joint) -> None:
    """Stretch a unit-length segment from one joint to the next."""
    length = start.distance_to(end)
    node.setPos(start.along_m, node.getY(), start.up_m)
    _point_along(node, start, end)
    node.setScale(max(length, 1e-3), 1.0, 1.0)


def _point_along(node: NodePath, start: Joint, end: Joint) -> None:
    """Aim a shape built along +X at another joint.

    Roll, not pitch. Pitch turns a limb about its own length, and for a round
    cross-section that is no visible change at all - which is exactly what a
    figure made entirely of horizontal slabs looked like.
    """
    angle = math.atan2(end.up_m - start.up_m, end.along_m - start.along_m)
    node.setHpr(0.0, 0.0, -math.degrees(angle))
