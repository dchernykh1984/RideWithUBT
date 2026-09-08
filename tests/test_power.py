from __future__ import annotations

import math

import pytest

from app.trainer.power import (
    GENERIC_CURVES,
    MIN_FIT_SAMPLES,
    NotEnoughDataError,
    PowerCurve,
    fit_power_curve,
    generic_curve,
    usable_samples,
)


def samples_from(curve: PowerCurve, count: int = 40) -> list[tuple[float, float]]:
    """Points straight off a curve, spanning a realistic riding range."""
    return [
        (speed, curve.power_w(speed))
        for speed in (3.0 + 0.25 * step for step in range(count))
    ]


def test_a_stopped_wheel_makes_no_power() -> None:
    curve = PowerCurve(coefficient=0.35, exponent=3.0)

    assert curve.power_w(0.0) == 0.0
    assert curve.power_w(-1.0) == 0.0


def test_power_never_goes_negative_even_with_an_offset() -> None:
    curve = PowerCurve(coefficient=0.35, exponent=3.0, offset_w=-50.0)

    assert curve.power_w(1.0) == 0.0


def test_the_generic_fluid_curve_is_in_the_right_neighbourhood() -> None:
    watts = GENERIC_CURVES["fluid"].power_w(30 / 3.6)

    assert 180 < watts < 220


def test_a_fluid_trainer_bites_harder_than_a_magnetic_one_at_speed() -> None:
    fast = 40 / 3.6

    assert GENERIC_CURVES["fluid"].power_w(fast) > GENERIC_CURVES["magnetic"].power_w(
        fast
    )


@pytest.mark.parametrize("resistance", ["electromagnetic", "motor_brake"])
def test_trainers_that_measure_their_own_power_get_no_generic_curve(
    resistance: str,
) -> None:
    """Estimating one of these would replace a measurement with a guess."""
    assert generic_curve(resistance) is None


def test_coasting_and_zero_power_samples_are_dropped() -> None:
    kept = usable_samples([(0.0, 0.0), (1.0, 30.0), (8.0, 0.0), (8.0, 200.0)])

    assert kept == [(8.0, 200.0)]


def test_a_fit_recovers_the_curve_it_was_generated_from() -> None:
    original = PowerCurve(coefficient=0.346, exponent=3.0)

    fit = fit_power_curve(samples_from(original))

    assert fit.curve.exponent == pytest.approx(3.0, abs=0.01)
    assert fit.curve.coefficient == pytest.approx(0.346, rel=0.01)
    assert fit.rms_error_w == pytest.approx(0.0, abs=0.5)
    assert fit.samples == 40


def test_a_fit_reports_the_range_it_is_valid_over() -> None:
    fit = fit_power_curve(samples_from(PowerCurve(coefficient=2.6, exponent=2.0)))

    low, high = fit.speed_range_kmh
    assert low == pytest.approx(3.0 * 3.6)
    assert high == pytest.approx(12.75 * 3.6)


def test_noise_shows_up_as_error_not_as_a_wrong_curve() -> None:
    original = PowerCurve(coefficient=0.346, exponent=3.0)
    noisy = [
        (speed, power + (10.0 if index % 2 else -10.0))
        for index, (speed, power) in enumerate(samples_from(original))
    ]

    fit = fit_power_curve(noisy)

    assert fit.curve.exponent == pytest.approx(3.0, abs=0.1)
    assert fit.rms_error_w > 5.0


def test_too_few_samples_are_refused() -> None:
    with pytest.raises(NotEnoughDataError, match="usable samples"):
        fit_power_curve(samples_from(PowerCurve(0.35, 3.0), count=MIN_FIT_SAMPLES - 1))


def test_a_narrow_speed_band_is_refused() -> None:
    """Fitting one speed cannot say what happens at another."""
    curve = PowerCurve(coefficient=0.35, exponent=3.0)
    flat = [(8.0 + 0.01 * step, curve.power_w(8.0 + 0.01 * step)) for step in range(40)]

    with pytest.raises(NotEnoughDataError, match="span"):
        fit_power_curve(flat)


def test_the_fit_is_a_straight_line_in_log_space() -> None:
    """The property the maths relies on, checked directly."""
    curve = PowerCurve(coefficient=0.5, exponent=2.4)

    doubled = curve.power_w(2.0) / curve.power_w(1.0)

    assert doubled == pytest.approx(2.0**2.4)
    assert math.log(doubled) == pytest.approx(2.4 * math.log(2.0))
