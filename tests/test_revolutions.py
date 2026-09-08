from __future__ import annotations

import pytest

from app.sensors.revolutions import (
    MAX_UNAMBIGUOUS_GAP_S,
    TICKS_PER_SECOND,
    Cadence,
    RevolutionCounter,
    WheelSpeed,
)


def ticks(seconds: float) -> int:
    return round(seconds * TICKS_PER_SECOND)


def test_the_first_sample_only_sets_a_baseline() -> None:
    """A rate is a difference, so one sample cannot produce one."""
    counter = RevolutionCounter()

    assert counter.update(revolutions=10, event_time=ticks(1.0), now=1.0) is None
    assert counter.rate is None


def test_two_samples_give_a_rate() -> None:
    counter = RevolutionCounter()
    counter.update(10, ticks(1.0), now=1.0)

    # Five revolutions in half a second is ten a second.
    rate = counter.update(15, ticks(1.5), now=1.5)

    assert rate == pytest.approx(10.0)


def test_the_event_clock_wrapping_does_not_produce_a_spike() -> None:
    """The 16-bit event time wraps every 64 seconds; the difference must survive."""
    counter = RevolutionCounter()
    counter.update(10, 65500, now=1.0)

    # 36 ticks later, having wrapped through zero.
    rate = counter.update(11, 0, now=1.05)

    assert rate == pytest.approx(TICKS_PER_SECOND / 36.0, rel=1e-6)


def test_the_revolution_counter_wrapping_does_not_produce_a_spike() -> None:
    counter = RevolutionCounter(revolution_bits=16)
    counter.update(65530, ticks(1.0), now=1.0)

    rate = counter.update(4, ticks(2.0), now=2.0)

    # Ten revolutions across the wrap, in one second - not sixty thousand.
    assert rate == pytest.approx(10.0)


def test_a_repeated_packet_holds_the_last_rate_briefly() -> None:
    """A sensor resends its last event while the wheel is between magnets."""
    counter = RevolutionCounter(stop_after_s=3.0)
    counter.update(10, ticks(1.0), now=1.0)
    counter.update(15, ticks(1.5), now=1.5)

    held = counter.update(15, ticks(1.5), now=2.0)

    assert held == pytest.approx(10.0)


def test_a_wheel_that_stops_reads_as_stopped() -> None:
    counter = RevolutionCounter(stop_after_s=3.0)
    counter.update(10, ticks(1.0), now=1.0)
    counter.update(15, ticks(1.5), now=1.5)

    assert counter.update(15, ticks(1.5), now=4.4) == pytest.approx(10.0)
    assert counter.update(15, ticks(1.5), now=4.6) == 0.0


def test_a_gap_long_enough_to_be_ambiguous_starts_again() -> None:
    """Past 64 seconds the event clock may have wrapped any number of times."""
    counter = RevolutionCounter()
    counter.update(10, ticks(1.0), now=1.0)
    counter.update(15, ticks(1.5), now=1.5)

    assert counter.update(20, ticks(2.0), now=1.5 + MAX_UNAMBIGUOUS_GAP_S + 1) is None
    assert counter.rate is None


def test_reset_forgets_everything() -> None:
    counter = RevolutionCounter()
    counter.update(10, ticks(1.0), now=1.0)
    counter.update(15, ticks(1.5), now=1.5)

    counter.reset()

    assert counter.rate is None
    assert counter.update(20, ticks(2.0), now=2.0) is None


def test_wheel_speed_is_revolutions_through_the_rollout() -> None:
    wheel = WheelSpeed(rollout_mm=2000.0)
    wheel.update(0, ticks(0.0), now=0.0)

    # Five revolutions in one second, two metres each.
    speed = wheel.update(5, ticks(1.0), now=1.0)

    assert speed == pytest.approx(10.0)


def test_wheel_speed_has_no_answer_before_the_second_sample() -> None:
    wheel = WheelSpeed(rollout_mm=2100.0)

    assert wheel.update(0, ticks(0.0), now=0.0) is None


def test_cadence_is_reported_per_minute() -> None:
    cadence = Cadence()
    cadence.update(0, ticks(0.0), now=0.0)

    # Ninety revolutions a minute is 1.5 a second.
    rpm = cadence.update(3, ticks(2.0), now=2.0)

    assert rpm == pytest.approx(90.0)


def test_cadence_resets() -> None:
    cadence = Cadence()
    cadence.update(0, ticks(0.0), now=0.0)
    cadence.update(3, ticks(2.0), now=2.0)

    cadence.reset()

    assert cadence.update(6, ticks(4.0), now=4.0) is None


def test_wheel_speed_resets() -> None:
    wheel = WheelSpeed(rollout_mm=2000.0)
    wheel.update(0, ticks(0.0), now=0.0)
    wheel.update(5, ticks(1.0), now=1.0)

    wheel.reset()

    assert wheel.update(10, ticks(2.0), now=2.0) is None


def test_a_finer_event_clock_is_honoured() -> None:
    """Cycling Power times wheel events in 1/2048 s; 1/1024 would double the rate."""
    counter = RevolutionCounter(ticks_per_second=2048)
    counter.update(10, 0, now=1.0)

    rate = counter.update(15, 2048, now=2.0)

    assert rate == pytest.approx(5.0)


def test_the_ambiguity_window_shrinks_with_a_finer_clock() -> None:
    """At 1/2048 s the 16-bit event field wraps in 32 seconds, not 64."""
    counter = RevolutionCounter(ticks_per_second=2048)
    counter.update(10, 0, now=1.0)
    counter.update(15, 2048, now=2.0)

    assert counter.update(20, 4096, now=2.0 + 40.0) is None
