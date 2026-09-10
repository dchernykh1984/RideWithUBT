"""The rider you can see, and their legs going round.

A red triangle told you where you were and nothing else. A cyclist tells you
something no number does: whether the pedals are turning, and how fast. The
stroke is geometry, so it is checked as geometry - without a window.
"""

from __future__ import annotations

import math

import pytest

from app.core.figure import (
    BOTTOM_BRACKET_M,
    DEFAULT_CADENCE_RPM,
    STOPPED_RPM,
    Cranks,
    Joint,
    Rider,
    knee,
)


def rider() -> Rider:
    return Rider()


# Where the pedals are.


def test_the_pedals_go_round_a_circle_the_size_of_the_cranks() -> None:
    on = rider()

    for degrees in range(0, 360, 15):
        pedal = on.pedal_at(math.radians(degrees))
        assert math.hypot(pedal.along_m, pedal.up_m) == pytest.approx(on.crank_m)


def test_the_two_pedals_are_always_opposite() -> None:
    """Which is the only reason pedalling works at all."""
    on = rider()

    for degrees in range(0, 360, 30):
        right, left = on.legs(math.radians(degrees))
        assert right.pedal.along_m == pytest.approx(-left.pedal.along_m, abs=1e-9)
        assert right.pedal.up_m == pytest.approx(-left.pedal.up_m, abs=1e-9)


# Where the knee is.


def test_the_leg_reaches_from_the_hip_to_the_pedal() -> None:
    """Two bones of fixed length: they have to actually meet at both ends."""
    on = rider()

    for degrees in range(0, 360, 10):
        leg = on.leg_at(math.radians(degrees))
        assert leg.hip.distance_to(leg.knee) == pytest.approx(on.thigh_m, abs=1e-6)
        assert leg.knee.distance_to(leg.pedal) == pytest.approx(on.shin_m, abs=1e-6)


def test_the_knee_bends_forwards() -> None:
    """The other solution is a leg bending the wrong way."""
    on = rider()

    for degrees in range(0, 360, 10):
        leg = on.leg_at(math.radians(degrees))
        assert leg.knee.along_m > leg.hip.along_m, f"at {degrees} degrees"


def test_the_knee_is_never_locked_straight() -> None:
    """A rider's leg keeps a bend in it all the way round, and a leg that
    straightens completely at the bottom looks like a mannequin."""
    on = rider()

    for degrees in range(0, 360, 10):
        leg = on.leg_at(math.radians(degrees))
        assert leg.hip.distance_to(leg.pedal) < on.thigh_m + on.shin_m - 0.01


def test_the_leg_is_most_bent_at_the_top_of_the_stroke() -> None:
    on = rider()

    top = on.leg_at(math.pi / 2)
    bottom = on.leg_at(-math.pi / 2)

    assert top.hip.distance_to(top.pedal) < bottom.hip.distance_to(bottom.pedal)


def test_a_rider_whose_legs_cannot_reach_the_pedals_is_refused() -> None:
    """Rather than drawn with a leg that snaps straight at the bottom."""
    with pytest.raises(ValueError, match="cannot reach"):
        Rider(thigh_m=0.20, shin_m=0.20)


def test_a_leg_stretched_to_its_limit_points_at_the_pedal() -> None:
    hip = Joint(0.0, 1.0)
    pedal = Joint(0.0, 0.0)

    where = knee(hip, pedal, 0.4, 0.4)

    assert where.along_m == pytest.approx(0.0, abs=1e-9)
    assert where.up_m == pytest.approx(0.6, abs=1e-9)


# The pedals turning.


def test_the_cranks_turn_at_the_cadence_they_are_given() -> None:
    cranks = Cranks()

    cranks.advance(seconds=60.0 / 90.0, cadence_rpm=90.0)

    assert cranks.angle_rad == pytest.approx(math.tau, abs=1e-6) or (
        cranks.angle_rad == pytest.approx(0.0, abs=1e-6)
    )


def test_a_minute_at_ninety_is_ninety_turns() -> None:
    cranks = Cranks()
    turns = 0.0
    before = cranks.angle_rad

    for _ in range(600):
        after = cranks.advance(seconds=0.1, cadence_rpm=90.0)
        if after < before:
            turns += 1
        before = after

    assert turns == pytest.approx(90, abs=1)


def test_with_no_sensor_the_rider_still_pedals() -> None:
    """A figure sitting frozen on a moving bicycle looks broken, and that is
    what most riders will see first."""
    cranks = Cranks()

    cranks.advance(seconds=0.5, cadence_rpm=None)

    assert cranks.angle_rad > 0.0
    assert 60 <= DEFAULT_CADENCE_RPM <= 100


def test_a_sensor_reading_beats_the_default() -> None:
    fast, slow = Cranks(), Cranks()

    fast.advance(seconds=1.0, cadence_rpm=110.0)
    slow.advance(seconds=1.0, cadence_rpm=50.0)

    assert fast.angle_rad > slow.angle_rad


def test_a_stopped_rider_stops_pedalling() -> None:
    """A cadence sensor reports small numbers as a wheel coasts to a halt, and
    legs still going round on a bicycle nobody is pedalling is worse."""
    cranks = Cranks(angle_rad=1.0)

    cranks.advance(seconds=1.0, cadence_rpm=0.0)
    cranks.advance(seconds=1.0, cadence_rpm=STOPPED_RPM - 1)

    assert cranks.angle_rad == 1.0


def test_the_angle_stays_within_one_turn() -> None:
    """It only ever grows, so without this it grows for as long as the ride."""
    cranks = Cranks()

    for _ in range(2000):
        cranks.advance(seconds=0.1, cadence_rpm=100.0)

    assert 0.0 <= cranks.angle_rad < math.tau


def test_the_bicycle_stands_on_the_road_rather_than_through_it() -> None:
    """Everything is measured from the bottom bracket, so this is what puts the
    figure on the tarmac: without it the pedals swing below the road."""
    assert BOTTOM_BRACKET_M > Rider().crank_m


def test_the_knee_goes_forwards_whichever_way_the_pedal_is() -> None:
    """The forward normal has to be picked whichever side the maths lands on,
    or the leg folds the wrong way through half the stroke."""
    hip = Joint(0.0, 1.0)

    forward = knee(hip, Joint(0.3, 0.2), 0.6, 0.6)
    backward = knee(hip, Joint(-0.3, 0.2), 0.6, 0.6)

    assert forward.along_m > hip.along_m
    assert backward.along_m > hip.along_m


def test_a_rider_with_the_pedals_above_their_hips_still_bends_forwards() -> None:
    """Which is a recumbent, and the only shape that takes the other branch:
    on an upright bicycle the pedals are always below the saddle."""
    hip = Joint(0.0, 0.0)
    pedal = Joint(0.1, 0.6)

    where = knee(hip, pedal, 0.45, 0.45)

    assert where.along_m > hip.along_m, "the knee still leads the way"
