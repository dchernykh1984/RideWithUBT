"""The view, and what dragging a mouse does to it.

A camera is not a picture: where it sits is a point on a sphere around the
rider and where it aims is another point, and both are arithmetic. That is why
this can be tested with no window open, which is the whole of the rule about
what lives in `app/render`.
"""

from __future__ import annotations

import math

import pytest

from app.core.camera import (
    BEHIND_M,
    FAR_M,
    FRAME_TILT_DEG,
    HEIGHT_M,
    LIFT_HIGH_DEG,
    LIFT_LOW_DEG,
    LOOK_AHEAD_M,
    LOOK_HEIGHT_M,
    NEAR_M,
    REST_DISTANCE_M,
    REST_LIFT_DEG,
    Chase,
)

Point = tuple[float, float, float]


def direction(here: Point, there: Point) -> Point:
    return (there[0] - here[0], there[1] - here[1], there[2] - here[2])


def angle_between(one: Point, other: Point) -> float:
    """The angle between two directions, in degrees."""
    dot = sum(a * b for a, b in zip(one, other, strict=True))
    lengths = math.hypot(*one) * math.hypot(*other)
    return math.degrees(math.acos(min(1.0, max(-1.0, dot / lengths))))


#: A rider at the origin heading due north, which makes "behind" and "ahead"
#: something a reader can check in their head.
NORTH = math.pi / 2


def test_a_ride_starts_behind_the_rider_and_above_them() -> None:
    """Untouched, it is exactly the view this had before it could be moved."""
    eye = Chase().eye(0.0, 0.0, 0.0, NORTH)

    assert eye[0] == pytest.approx(0.0, abs=1e-9)
    assert eye[1] == pytest.approx(-BEHIND_M)
    assert eye[2] == pytest.approx(HEIGHT_M)


def test_and_looks_up_the_road_rather_than_at_the_rider() -> None:
    """The same line as before any of this: at a point LOOK_AHEAD_M up the road
    and LOOK_HEIGHT_M above it, seen from BEHIND_M back and HEIGHT_M up."""
    chase = Chase()

    aim = direction(chase.eye(0.0, 0.0, 0.0, NORTH), chase.target(0.0, 0.0, 0.0, NORTH))

    # A thousandth of a degree: acos of a number a hair under one is not a
    # precise way to measure nothing, and nothing is what this is measuring.
    assert angle_between(
        aim, (0.0, BEHIND_M + LOOK_AHEAD_M, LOOK_HEIGHT_M - HEIGHT_M)
    ) == pytest.approx(0.0, abs=1e-3)


@pytest.mark.parametrize("turn", [0.0, 37.0, 90.0, 145.0, 180.0, 250.0, 330.0])
@pytest.mark.parametrize(
    "lift", [LIFT_LOW_DEG, 0.0, REST_LIFT_DEG, 45.0, LIFT_HIGH_DEG]
)
@pytest.mark.parametrize("distance", [NEAR_M, 9.0, REST_DISTANCE_M, FAR_M])
def test_the_rider_stays_where_they_were_in_the_picture(
    turn: float, lift: float, distance: float
) -> None:
    """However the view is swung, lifted or pushed away. A view that can be
    turned until the rider is off the bottom of it is not a view of the rider,
    and aiming at a fixed point up the road did exactly that from above.

    Never further off the middle of the picture than riding puts them, and
    closer to it the nearer the camera comes."""
    chase = Chase(turn, lift, distance)

    eye = chase.eye(0.0, 0.0, 0.0, NORTH)
    aim = direction(eye, chase.target(0.0, 0.0, 0.0, NORTH))
    rider = direction(eye, (0.0, 0.0, LOOK_HEIGHT_M))

    assert angle_between(aim, rider) <= FRAME_TILT_DEG + 1e-3


def test_the_rider_is_where_riding_puts_them_from_the_distance_riding_uses() -> None:
    chase = Chase(turn_deg=64.0)

    eye = chase.eye(0.0, 0.0, 0.0, NORTH)
    aim = direction(eye, chase.target(0.0, 0.0, 0.0, NORTH))
    rider = direction(eye, (0.0, 0.0, LOOK_HEIGHT_M))

    assert angle_between(aim, rider) == pytest.approx(FRAME_TILT_DEG, abs=1e-3)


def test_and_nearer_the_middle_of_it_when_the_camera_is_pulled_in() -> None:
    """Close up the same angle put the wheels off the bottom edge."""
    close = Chase(distance_m=NEAR_M)

    eye = close.eye(0.0, 0.0, 0.0, NORTH)
    aim = direction(eye, close.target(0.0, 0.0, 0.0, NORTH))
    rider = direction(eye, (0.0, 0.0, LOOK_HEIGHT_M))

    assert angle_between(aim, rider) < FRAME_TILT_DEG / 2.0


def test_dragging_across_swings_the_view_round_the_rider() -> None:
    chase = Chase()

    chase.drag(0.5, 0.0)

    assert chase.turn_deg == pytest.approx(45.0)


def test_a_quarter_turn_puts_the_camera_beside_the_rider() -> None:
    chase = Chase()
    chase.lift_deg = 0.0

    chase.drag(1.0, 0.0)

    eye = chase.eye(0.0, 0.0, 0.0, NORTH)
    assert eye[0] == pytest.approx(chase.distance_m)
    assert eye[1] == pytest.approx(0.0, abs=1e-9)


def test_a_view_swung_aside_looks_at_the_rider_rather_than_past_them() -> None:
    chase = Chase()
    chase.drag(1.0, 0.0)

    target = chase.target(0.0, 0.0, 0.0, NORTH)

    assert target[0] == pytest.approx(0.0, abs=0.9), "it is not looking at them"


def test_the_view_stays_where_the_rider_put_it_through_a_corner() -> None:
    """Turned to the rider's left, it is still on their left afterwards: the
    angle is measured from the rider, not from the compass."""
    chase = Chase()
    chase.lift_deg = 0.0
    chase.drag(1.0, 0.0)

    turned = chase.eye(0.0, 0.0, 0.0, NORTH + math.pi / 2)

    assert turned[1] == pytest.approx(chase.distance_m)
    assert turned[0] == pytest.approx(0.0, abs=1e-9)


def test_dragging_up_lifts_the_camera() -> None:
    chase = Chase()
    was = chase.eye(0.0, 0.0, 0.0, NORTH)[2]

    chase.drag(0.0, 0.5)

    assert chase.eye(0.0, 0.0, 0.0, NORTH)[2] > was


def test_the_view_cannot_be_dragged_under_the_road_or_onto_the_helmet() -> None:
    chase = Chase()

    for _ in range(20):
        chase.drag(0.0, -1.0)
    assert chase.lift_deg == pytest.approx(LIFT_LOW_DEG)

    for _ in range(20):
        chase.drag(0.0, 1.0)
    assert chase.lift_deg == pytest.approx(LIFT_HIGH_DEG)


def test_turning_all_the_way_round_comes_back_to_the_beginning() -> None:
    chase = Chase()

    for _ in range(4):
        chase.drag(1.0, 0.0)

    assert chase.turn_deg == pytest.approx(0.0)


def test_the_wheel_moves_the_camera_in_and_out() -> None:
    chase = Chase()
    was = chase.distance_m

    chase.zoom(1)
    assert chase.distance_m < was

    chase.zoom(-1)
    assert chase.distance_m == pytest.approx(was)


def test_the_wheel_cannot_push_the_camera_through_the_rider() -> None:
    chase = Chase()

    for _ in range(60):
        chase.zoom(1)
    assert chase.distance_m == pytest.approx(NEAR_M)

    for _ in range(120):
        chase.zoom(-1)
    assert chase.distance_m == pytest.approx(FAR_M)


def test_putting_it_back_is_one_thing_to_do() -> None:
    chase = Chase()
    chase.drag(0.7, 0.3)
    chase.zoom(3)
    assert chase.turned

    chase.reset()

    assert not chase.turned
    assert chase.eye(0.0, 0.0, 0.0, NORTH) == pytest.approx(
        Chase().eye(0.0, 0.0, 0.0, NORTH)
    )


def test_a_view_nobody_has_touched_says_so() -> None:
    assert not Chase().turned
