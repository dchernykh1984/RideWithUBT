"""Building the rider, and turning their legs.

The shapes and the pedal stroke are worked out elsewhere - `app/world/solids.py`
and `app/core/figure.py` - and neither needs a window. This puts them into the
scene graph and moves two bones per leg, which is all a renderer should be
doing.

The figure faces +X, which is the way a rider on this track faces before the
node is turned to their heading. Up is +Z, as everywhere else in this world.
"""

from __future__ import annotations

import math

from panda3d.core import NodePath

from app.core.figure import (
    BOTTOM_BRACKET_M,
    WHEEL_RADIUS_M,
    WHEELBASE_M,
    Joint,
    Rider,
)
from app.render.geometry import geom_node
from app.world.solids import box, tube

#: The colours the figure is drawn in. A rider has to be picked out at a glance
#: from a hundred metres, so the jersey is the team's orange.
JERSEY = (0.95, 0.42, 0.05, 1.0)
SKIN = (0.85, 0.68, 0.55, 1.0)
BIKE = (0.16, 0.17, 0.20, 1.0)
TYRE = (0.10, 0.10, 0.11, 1.0)

#: How thick a limb is drawn, in metres. Thin enough to be a leg, thick enough
#: to be seen.
LIMB_M = 0.11
#: How far apart the two legs are, so they are not one leg drawn twice.
TRACK_M = 0.09


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
            (self._bone(TRACK_M), self._bone(TRACK_M)),
            (self._bone(-TRACK_M), self._bone(-TRACK_M)),
        ]
        self.pedals = self._pedals()
        self.pedal_at(0.0)

    # Putting it together. Everything is measured from the bottom bracket,
    # which is where the node's origin is, so the figure sits on the road when
    # the node is put at the road's height plus the wheel's radius.

    def _build_bicycle(self) -> None:
        wheelbase = WHEELBASE_M
        radius = WHEEL_RADIUS_M
        # The wheels' centres, measured from the bottom bracket rather than
        # from the road: everything here is.
        axle = radius - BOTTOM_BRACKET_M
        for along in (-0.42, wheelbase - 0.42):
            wheel = self._part(tube(0.045, radius, hollow=True), TYRE, "wheel")
            # A tube is built along +X; a wheel stands across the bike.
            wheel.setHpr(90.0, 0.0, 0.0)
            wheel.setPos(along, -0.022, axle)
        for start, end, thickness in (
            ((-0.42, axle), (0.0, 0.0), 0.045),  # chainstay
            ((-0.42, axle), (-0.06, 0.60), 0.04),  # seat stay
            ((0.0, 0.0), (-0.06, 0.62), 0.05),  # seat tube
            ((0.0, 0.0), (0.50, 0.50), 0.05),  # down tube
            ((-0.06, 0.60), (0.50, 0.50), 0.045),  # top tube
            ((0.50, 0.50), (wheelbase - 0.42, axle), 0.04),  # fork
            ((-0.14, 0.66), (0.06, 0.68), 0.05),  # saddle
            ((0.46, 0.56), (0.62, 0.56), 0.04),  # bars
        ):
            self._strut(Joint(*start), Joint(*end), thickness, BIKE)
        if self.rider.posture.aerobars:
            # Extensions to rest the forearms on, reaching towards the hands:
            # they are most of what makes a time trial position what it is.
            self._strut(Joint(0.50, 0.58), self.rider.posture.hands, 0.035, BIKE)
        # The chainring, so the cranks have something to turn on.
        ring = self._part(tube(0.02, 0.10, hollow=True), BIKE, "chainring")
        ring.setHpr(90.0, 0.0, 0.0)
        ring.setPos(0.0, -0.06, 0.0)

    def _build_body(self) -> None:
        """A rider bent over the bars: a back, arms, and a head."""
        posture = self.rider.posture
        hip, shoulder = posture.hip, posture.shoulder
        self._strut(hip, shoulder, 0.17, JERSEY)
        for side in (TRACK_M, -TRACK_M):
            arm = self._strut(shoulder, posture.hands, 0.07, SKIN)
            arm.setY(side)
        # A helmet, across the bike rather than along it: a disc pointing at
        # the rider behind is not a head. It goes on ahead of the shoulders,
        # along the line the back is already running.
        lean = math.atan2(shoulder.up_m - hip.up_m, shoulder.along_m - hip.along_m)
        head = self._part(tube(0.19, 0.095), JERSEY, "head")
        head.setHpr(90.0, 0.0, 0.0)
        head.setPos(
            shoulder.along_m + 0.14 * math.cos(lean),
            -0.095,
            shoulder.up_m + 0.14 * math.sin(lean),
        )

    def _strut(
        self, start: Joint, end: Joint, thickness: float, colour: tuple[float, ...]
    ) -> NodePath:
        """A tube from one point to another in the bicycle's side plane."""
        node = self._part(
            box(start.distance_to(end), thickness, thickness), colour, "strut"
        )
        node.setPos(start.along_m, 0.0, start.up_m)
        _point_along(node, start, end)
        return node

    def _bone(self, side: float) -> NodePath:
        """One segment of a leg: placed and pointed afresh every frame."""
        node = self._part(box(1.0, LIMB_M, LIMB_M), SKIN, "bone")
        node.setY(side)
        return node

    def _pedals(self) -> list[NodePath]:
        return [self._part(box(0.09, 0.11, 0.02), BIKE, "pedal") for _ in range(2)]

    def _part(self, mesh: object, colour: tuple[float, ...], name: str) -> NodePath:
        node = self.root.attachNewNode(geom_node(mesh, name))  # type: ignore[arg-type]
        node.setColor(*colour)
        return node

    # Moving it.

    def pedal_at(self, angle_rad: float) -> None:
        """Put the legs where this crank angle puts them."""
        for leg, (thigh, shin) in zip(
            self.rider.legs(angle_rad), self.bones, strict=True
        ):
            _lay(thigh, leg.hip, leg.knee)
            _lay(shin, leg.knee, leg.pedal)
        for pedal, leg in zip(self.pedals, self.rider.legs(angle_rad), strict=True):
            pedal.setPos(leg.pedal.along_m - 0.045, pedal.getY(), leg.pedal.up_m)

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

    Roll, not pitch. Pitch turns a limb about its own length, and for a square
    cross-section that is no visible change at all - which is exactly what a
    figure made entirely of horizontal slabs looked like.
    """
    angle = math.atan2(end.up_m - start.up_m, end.along_m - start.along_m)
    node.setHpr(0.0, 0.0, -math.degrees(angle))
