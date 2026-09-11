"""Where the camera sits, and what a rider dragging the mouse does to it.

The chase camera sits behind and above the rider and looks well ahead, which is
the view somebody rides in. It is not the view somebody wants when they want to
*look* at something - the rider, a building, the line they took through a
corner - so holding a mouse button and moving swings the whole view around.

None of that needs a window: it is a point on a sphere around the rider and a
point to aim at, both arithmetic, and arithmetic that decides what a drag does
belongs where it can be tested.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: Where the camera rests: behind the rider, above them, looking well ahead so
#: the road fills the picture rather than the rider's back.
BEHIND_M = 16.0
HEIGHT_M = 5.0
LOOK_AHEAD_M = 50.0
LOOK_HEIGHT_M = 1.0

#: The same place said as a distance and an angle, which is what an orbit turns.
REST_DISTANCE_M = math.hypot(BEHIND_M, HEIGHT_M)
REST_LIFT_DEG = math.degrees(math.atan2(HEIGHT_M, BEHIND_M))

#: How far below the middle of the picture the rider sits. Not chosen: it is
#: where riding put them, worked out from the resting camera and the point up
#: the road it used to aim at, so the view nobody has touched is unchanged.
FRAME_TILT_DEG = math.degrees(
    # Both angles are measured from the camera, so both distances are measured
    # from the camera: the point up the road is BEHIND_M further off than it is
    # from the rider.
    math.atan2(LOOK_HEIGHT_M - HEIGHT_M, BEHIND_M + LOOK_AHEAD_M)
    - math.atan2(LOOK_HEIGHT_M - HEIGHT_M, BEHIND_M)
)

#: How far a drag across the whole window turns the view. A full window is two
#: units wide in the renderer's coordinates, so this is half a turn across the
#: screen: enough to get round the rider in one gesture without the view
#: running away from a small movement.
TURN_PER_UNIT_DEG = 90.0
LIFT_PER_UNIT_DEG = 60.0

#: How far up and down the view may go. Underneath the road is nothing to look
#: at, and straight down is a view of the rider's helmet.
LIFT_LOW_DEG = -20.0
LIFT_HIGH_DEG = 80.0

#: How close and how far the wheel may take it.
NEAR_M = 3.0
FAR_M = 80.0
ZOOM_STEP = 1.15


@dataclass
class Chase:
    """The camera's place around the rider, and what a mouse does to it.

    `turn_deg` is measured from straight behind the rider and goes round with
    them: a view swung to the left stays on the rider's left through a corner,
    which is what somebody who dragged it there meant.
    """

    turn_deg: float = 0.0
    lift_deg: float = REST_LIFT_DEG
    distance_m: float = REST_DISTANCE_M

    @property
    def turned(self) -> bool:
        """Whether the rider has moved the view off where it rests."""
        return not (
            math.isclose(self.turn_deg, 0.0, abs_tol=1e-6)
            and math.isclose(self.lift_deg, REST_LIFT_DEG, abs_tol=1e-6)
            and math.isclose(self.distance_m, REST_DISTANCE_M, abs_tol=1e-6)
        )

    def drag(self, across: float, up: float) -> None:
        """A mouse moved this far with a button held, in window units."""
        self.turn_deg = (self.turn_deg + across * TURN_PER_UNIT_DEG) % 360.0
        self.lift_deg = min(
            max(self.lift_deg + up * LIFT_PER_UNIT_DEG, LIFT_LOW_DEG), LIFT_HIGH_DEG
        )

    def zoom(self, by: int) -> None:
        """The wheel, a notch at a time: towards the rider, or away."""
        scaled = self.distance_m * (ZOOM_STEP**-by)
        self.distance_m = min(max(scaled, NEAR_M), FAR_M)

    def reset(self) -> None:
        """Back to riding: behind the rider, looking up the road."""
        self.turn_deg = 0.0
        self.lift_deg = REST_LIFT_DEG
        self.distance_m = REST_DISTANCE_M

    def eye(
        self, x: float, y: float, z: float, heading_rad: float
    ) -> tuple[float, float, float]:
        """Where the camera goes: a point on a sphere around the rider."""
        angle = heading_rad + math.radians(self.turn_deg)
        lift = math.radians(self.lift_deg)
        flat = self.distance_m * math.cos(lift)
        return (
            x - flat * math.cos(angle),
            y - flat * math.sin(angle),
            z + self.distance_m * math.sin(lift),
        )

    def target(
        self, x: float, y: float, z: float, heading_rad: float
    ) -> tuple[float, float, float]:
        """What it aims at: the rider, with the picture tipped up off them.

        Aiming at a fixed point up the road only works from behind. Swung round
        or lifted, the road far ahead is somewhere else entirely and the rider
        drops off the bottom of the picture - which is what a first attempt at
        this did, from above.

        So the line is taken to the rider and then tipped up by the angle the
        rider sits below the middle of the picture when riding. From behind
        that is exactly the old view, up the road; from anywhere else the rider
        stays where they were in the frame, which is the whole point of being
        able to swing it round them.
        """
        eye = self.eye(x, y, z, heading_rad)
        across = math.hypot(x - eye[0], y - eye[1])
        along = math.atan2(y - eye[1], x - eye[0])
        down = math.atan2(z + LOOK_HEIGHT_M - eye[2], across)
        # The tip falls away as the camera comes in close. A rider who has
        # pulled it in to look at the bicycle is looking at the bicycle, and at
        # three metres the same angle puts the wheels off the bottom edge.
        tipped = down + math.radians(FRAME_TILT_DEG) * min(
            1.0, self.distance_m / REST_DISTANCE_M
        )
        reach = math.hypot(across, z + LOOK_HEIGHT_M - eye[2])
        flat = reach * math.cos(tipped)
        return (
            eye[0] + flat * math.cos(along),
            eye[1] + flat * math.sin(along),
            eye[2] + reach * math.sin(tipped),
        )
