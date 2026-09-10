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
    colour,
    described,
    frame_tubes,
)
from app.render.geometry import geom_node
from app.world.mesh import EMPTY, Mesh
from app.world.solids import annulus, box, sphere, tube

# Everything the figure is made of is described in `app/data/figure.json`;
# these only give those numbers names to read the code by.
JERSEY = colour("jersey")
SHORTS = colour("shorts")
SKIN = colour("skin")
BIKE = colour("frame")
TYRE = colour("tyre")
RIM = colour("rim")


def _rider_says(key: str) -> float:
    return float(described()["rider"][key])


def _bicycle_says(key: str) -> float:
    return float(described()["bicycle"][key])


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
        thigh = _rider_says("thigh_thickness_m")
        shin = _rider_says("shin_thickness_m")
        self.bones = [
            (self._bone(thigh, side), self._bone(shin, side))
            for side in (FOOT_SPACING_M / 2, -FOOT_SPACING_M / 2)
        ]
        foot = _rider_says("foot_m")
        self.feet = [
            self._part(box(foot, 0.09, 0.045), SHORTS, "foot") for _ in range(2)
        ]
        for side, node in zip(
            (FOOT_SPACING_M / 2, -FOOT_SPACING_M / 2), self.feet, strict=True
        ):
            node.setY(side)
        self.pedal_at(0.0)

    # Putting it together. Everything is measured from the bottom bracket,
    # which is where the node's origin is.

    def _build_bicycle(self) -> None:
        posture = self.rider.posture
        axle = WHEEL_RADIUS_M - BOTTOM_BRACKET_M
        for along, front in ((-0.42, False), (WHEELBASE_M - 0.42, True)):
            self._wheel(along, axle, disc=posture.aerobars and not front)
        for tube_ in frame_tubes():
            self._strut(tube_.start, tube_.end, tube_.thickness_m, BIKE)
        saddle = self._part(
            box(_bicycle_says("saddle_length_m"), 0.07, 0.035), SHORTS, "saddle"
        )
        saddle.setPos(-0.16, 0.0, posture.hip.up_m - 0.05)
        bar_at = Joint(*described()["bicycle"]["bar_at"])
        self._across(bar_at, _bicycle_says("bar_width_m"), 0.028, BIKE, "bars")
        if posture.aerobars:
            # Extensions to rest the forearms on: most of what makes a time
            # trial position what it is.
            for side in (posture.hand_spacing_m, -posture.hand_spacing_m):
                extension = self._strut(bar_at, posture.hands, 0.025, BIKE)
                extension.setY(side)
        ring = self._part(annulus(0.04, _bicycle_says("chainring_m")), RIM, "chainring")
        ring.setHpr(90.0, 0.0, 0.0)
        ring.setY(-0.055)

    def _wheel(self, along: float, axle: float, disc: bool) -> None:
        """A wheel: a tyre, a rim, and either spokes or a solid disc.

        A disc wheel on the back of a time trial bicycle is a real thing and
        the most recognisable shape in cycling, so the bicycle a rider chose is
        visible from across the circuit.
        """
        tyre_width = _bicycle_says("tyre_width_m")
        tyre = self._part(tube(tyre_width, WHEEL_RADIUS_M, hollow=True), TYRE, "tyre")
        tyre.setHpr(90.0, 0.0, 0.0)
        tyre.setPos(along, -tyre_width / 2, axle)
        rim_inner = 0.02 if disc else WHEEL_RADIUS_M - _bicycle_says("rim_depth_m")
        for side in (0.012, -0.012):
            face = self._part(annulus(rim_inner, WHEEL_RADIUS_M - 0.002), RIM, "rim")
            # An annulus is built across +X; a wheel stands across the bike,
            # the same way its tyre does.
            face.setHpr(90.0, 0.0, 0.0)
            face.setPos(along, side, axle)
        if not disc:
            spokes = self._part(
                _spokes(
                    rim_inner,
                    int(_bicycle_says("spokes")),
                    _bicycle_says("spoke_thickness_m"),
                ),
                RIM,
                "spokes",
            )
            # Built across +X like the rim, so it takes the same quarter turn
            # to stand up in the wheel's own plane.
            spokes.setHpr(90.0, 0.0, 0.0)
            spokes.setPos(along, 0.0, axle)

    def _build_body(self) -> None:
        """A rider seen from behind is shoulders, a back and two legs."""
        posture = self.rider.posture
        hip, shoulder = posture.hip, posture.shoulder
        # The back, as an oval rather than a slab: wide across, shallow deep.
        back = self._strut(hip, shoulder, 1.0, JERSEY, round_=True)
        back.setScale(back.getSx(), SHOULDER_WIDTH_M * 0.9, 0.22)
        self._across(hip, HIP_WIDTH_M, 0.16, SHORTS, "hips")
        self._across(shoulder, SHOULDER_WIDTH_M, 0.15, JERSEY, "shoulders")
        self._build_arms()
        lean = math.atan2(shoulder.up_m - hip.up_m, shoulder.along_m - hip.along_m)
        # On a neck, ahead of the shoulders and a little above them - a head
        # level with the shoulders reads as a lump on the front of the chest.
        neck = Joint(
            shoulder.along_m + 0.07 * math.cos(lean) + 0.04,
            shoulder.up_m + 0.07 * math.sin(lean) + 0.05,
        )
        self._strut(shoulder, neck, 0.08, SKIN, round_=True)
        head = self._part(sphere(_rider_says("head_m")), JERSEY, "head")
        # On the neck, not ahead of it: a gap between the two is a head
        # floating in front of a rider.
        head.setPos(neck.along_m + 0.02, 0.0, neck.up_m + 0.02)
        head.setScale(1.3, 0.85, 0.95)

    def _build_arms(self) -> None:
        """Two bones and an elbow, and a hand on the bar.

        An arm is nearly sixty centimetres from shoulder to wrist and a rider's
        hands are forty from their shoulders, so the elbow is bent hard. Drawn
        as one straight piece it is not an arm, it is a stick - which is what
        it was.
        """
        posture = self.rider.posture
        shoulder, elbow_at, hand = self.rider.arm()
        thickness = _rider_says("arm_thickness_m")
        reach = SHOULDER_WIDTH_M / 2 * 0.8
        grip = posture.hand_spacing_m
        for side in (1.0, -1.0):
            upper = self._strut(shoulder, elbow_at, thickness, SKIN, round_=True)
            upper.setY(side * reach)
            fore = self._strut(elbow_at, hand, thickness * 0.9, SKIN, round_=True)
            fore.setY(side * (reach + grip) / 2)
            glove = self._part(sphere(_rider_says("hand_m") / 2), SHORTS, "hand")
            glove.setPos(hand.along_m, side * grip, hand.up_m)

    def _across(
        self,
        at: Joint,
        width: float,
        thickness: float,
        colour_: tuple[float, ...],
        name: str,
    ) -> NodePath:
        """A tube lying across the bike: a pair of shoulders, or handlebars."""
        node = self._part(tube(width, thickness / 2.0), colour_, name)
        node.setHpr(90.0, 0.0, 0.0)
        node.setPos(at.along_m, -width / 2.0, at.up_m)
        return node

    def _strut(
        self,
        start: Joint,
        end: Joint,
        thickness: float,
        colour_: tuple[float, ...],
        round_: bool = False,
    ) -> NodePath:
        """A tube from one point to another in the bicycle's side plane."""
        length = start.distance_to(end)
        shape: Mesh = (
            tube(length, thickness / 2.0)
            if round_ or thickness < 0.06
            else box(length, thickness, thickness)
        )
        node = self._part(shape, colour_, "strut")
        node.setPos(start.along_m, 0.0, start.up_m)
        _point_along(node, start, end)
        return node

    def _bone(self, thickness: float, side: float) -> NodePath:
        """One segment of a leg: placed and pointed afresh every frame."""
        node = self._part(tube(1.0, thickness), SKIN, "bone")
        node.setY(side)
        return node

    def _part(self, mesh: Mesh, colour_: tuple[float, ...], name: str) -> NodePath:
        node = self.root.attachNewNode(geom_node(mesh, name))
        node.setColor(*colour_)
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
            # The ball of the foot is on the pedal and the rest of it hangs
            # back from there, turning as the ankle turns.
            foot.setPos(leg.pedal.along_m, foot.getY(), leg.pedal.up_m)
            foot.setHpr(0.0, 0.0, -math.degrees(leg.foot_rad))
            foot.setPos(
                foot,
                -_rider_says("foot_m") * 0.65,
                0.0,
                0.0,
            )

    def hide(self) -> None:
        self.root.hide()

    def show(self) -> None:
        self.root.show()


def _spokes(inner: float, count: int, thickness: float) -> Mesh:
    """Every spoke of a wheel in one mesh, from the hub out to the rim."""
    wheel = EMPTY
    for number in range(count):
        angle = math.tau * number / count
        spoke = box(inner - 0.02, thickness, thickness)
        wheel = wheel.merged_with(_turned(spoke, angle, 0.02))
    return wheel


def _turned(mesh: Mesh, angle: float, from_hub: float) -> Mesh:
    """A spoke laid out from the hub at this angle, in the wheel's own plane.

    Across +X, the plane a wheel is built in here - the same one the rim is.
    Laid out in the ground plane instead, twenty spokes are a starburst lying
    flat on the road, which is what they were.
    """
    cosine, sine = math.cos(angle), math.sin(angle)
    return Mesh(
        vertices=tuple(
            (
                z,
                (from_hub + x) * cosine - y * sine,
                (from_hub + x) * sine + y * cosine,
            )
            for x, y, z in mesh.vertices
        ),
        tex_coords=mesh.tex_coords,
        triangles=mesh.triangles,
        normals=None,
    )


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
