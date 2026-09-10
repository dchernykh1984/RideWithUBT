"""The numbers here are checked against what a rider would actually see.

A power model that is merely self-consistent is useless: if 200 W gives the wrong
speed, every workout ridden in this app is ridden at the wrong effort. So the
tests assert against outdoor figures, not against the model's own arithmetic.
"""

from __future__ import annotations

import pytest

from app.core.physics import (
    MAX_ACCELERATION_MS2,
    MAX_SPEED_MS,
    SEA_LEVEL_DENSITY_KGM3,
    Air,
    Bike,
    power_needed_w,
    resistance_n,
    steady_speed_ms,
    step_speed_ms,
)

# Eighty kilos all in, on the hoods. Stated rather than taken from the default,
# because the figures below are what published calculators say for *this* rider
# and would quietly stop meaning that if the default moved.
RIDER = Bike(total_mass_kg=80.0, cda_m2=0.32)


@pytest.mark.parametrize(
    ("watts", "expected_kmh"),
    [
        (100, 25.5),
        (150, 30.0),
        (200, 33.5),
        (250, 36.5),
        (300, 39.0),
    ],
)
def test_flat_speeds_match_what_a_rider_sees_outdoors(
    watts: int, expected_kmh: float
) -> None:
    """Eighty kilos on the hoods: the figures every power calculator agrees on."""
    speed = steady_speed_ms(watts, 0.0, RIDER) * 3.6

    assert speed == pytest.approx(expected_kmh, abs=0.6)


@pytest.mark.parametrize(
    ("watts", "expected_kmh"),
    [(150, 11.7), (200, 15.1), (300, 21.1)],
)
def test_climbing_speeds_are_dominated_by_weight(
    watts: int, expected_kmh: float
) -> None:
    """On a five percent climb the rider is lifting themselves, not fighting air."""
    speed = steady_speed_ms(watts, 0.05, RIDER) * 3.6

    assert speed == pytest.approx(expected_kmh, abs=0.6)


def test_a_heavier_rider_climbs_slower_at_the_same_power() -> None:
    light = steady_speed_ms(250, 0.06, Bike(total_mass_kg=68.0))
    heavy = steady_speed_ms(250, 0.06, Bike(total_mass_kg=92.0))

    assert light > heavy


def test_a_smaller_frontal_area_pays_off_on_the_flat_not_the_climb() -> None:
    """Aerodynamics scale with the cube of speed, so they barely matter uphill."""
    hoods, drops = Bike(cda_m2=0.32), Bike(cda_m2=0.27)

    flat_gain = steady_speed_ms(250, 0.0, drops) - steady_speed_ms(250, 0.0, hoods)
    climb_gain = steady_speed_ms(250, 0.08, drops) - steady_speed_ms(250, 0.08, hoods)

    assert flat_gain > climb_gain * 5


def test_power_and_speed_are_inverses_of_each_other() -> None:
    speed = steady_speed_ms(240, 0.02, RIDER)

    assert power_needed_w(speed, 0.02, RIDER, Air()) == pytest.approx(240, abs=0.5)


def test_no_power_means_no_speed() -> None:
    assert steady_speed_ms(0.0, 0.0, RIDER) == 0.0
    assert steady_speed_ms(-50.0, 0.0, RIDER) == 0.0


def test_a_descent_needs_less_than_nothing_to_hold_a_speed() -> None:
    """Gravity does the work, so the resistance the rider fights turns negative."""
    assert resistance_n(10.0, -0.08, RIDER, Air()) < 0.0


def test_a_climb_needs_more_power_than_the_flat() -> None:
    assert power_needed_w(8.0, 0.05, RIDER, Air()) > power_needed_w(
        8.0, 0.0, RIDER, Air()
    )


def test_thinner_air_higher_up() -> None:
    """Sokol sits about six hundred metres up, which is a few percent of drag."""
    high = Air.at_altitude(600)

    assert high.density_kgm3 < SEA_LEVEL_DENSITY_KGM3
    assert high.density_kgm3 == pytest.approx(1.156, abs=0.01)
    assert steady_speed_ms(200, 0.0, RIDER, high) > steady_speed_ms(200, 0.0, RIDER)


def test_hot_air_is_thinner_than_cold_air() -> None:
    assert (
        Air.at_altitude(0, temperature_c=35).density_kgm3
        < Air.at_altitude(0, temperature_c=0).density_kgm3
    )


def test_a_rider_and_bicycle_have_to_weigh_something() -> None:
    with pytest.raises(ValueError, match="weigh something"):
        Bike(total_mass_kg=0.0)


def test_a_drivetrain_cannot_give_back_more_than_it_takes() -> None:
    with pytest.raises(ValueError, match="more than it is given"):
        Bike(drivetrain_efficiency=1.4)


# Accelerating, coasting and stopping.


def test_a_standing_start_accelerates_rather_than_dividing_by_zero() -> None:
    speed = step_speed_ms(0.0, 250.0, 0.0, 0.1, RIDER)

    assert 0.0 < speed < 5.0


def test_holding_a_power_settles_at_the_speed_for_it() -> None:
    speed = 0.0
    for _ in range(6000):  # ten minutes at a tenth of a second
        speed = step_speed_ms(speed, 200.0, 0.0, 0.1, RIDER)

    assert speed == pytest.approx(steady_speed_ms(200, 0.0, RIDER), abs=0.05)


def test_stopping_pedalling_coasts_down_rather_than_stopping_dead() -> None:
    rolling = steady_speed_ms(200, 0.0, RIDER)

    after_a_second = step_speed_ms(rolling, 0.0, 0.0, 1.0, RIDER)

    assert after_a_second < rolling
    assert after_a_second > rolling * 0.9


def test_a_rider_who_cannot_hold_a_climb_stops_rather_than_rolling_backwards() -> None:
    speed = 3.0
    for _ in range(200):
        speed = step_speed_ms(speed, 0.0, 0.12, 0.5, RIDER)

    assert speed == 0.0


def test_the_solver_covers_the_speeds_a_bicycle_reaches() -> None:
    """A long descent must not run into the bisection's ceiling."""
    assert steady_speed_ms(400, -0.10, RIDER) < MAX_SPEED_MS


def test_a_standing_start_is_limited_by_traction_not_by_watts() -> None:
    """P/v at walking pace claims an acceleration no bicycle can produce.

    Without a ceiling, a single one-second step at 200 W would take a stationary
    rider to nearly 30 km/h - and a coarse simulation step would be the only
    reason.
    """
    after_a_second = step_speed_ms(0.0, 200.0, 0.0, 1.0, RIDER)

    assert after_a_second <= MAX_ACCELERATION_MS2 + 1e-9
    assert after_a_second > 1.0


def test_the_ceiling_does_not_touch_a_rider_already_moving() -> None:
    rolling = steady_speed_ms(200, 0.0, RIDER) / 2

    gentle = step_speed_ms(rolling, 200.0, 0.0, 0.1, RIDER) - rolling

    assert 0.0 < gentle / 0.1 < MAX_ACCELERATION_MS2
