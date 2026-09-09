"""Cumulative revolution counters, turned into speed and cadence.

Speed and cadence sensors do not send a rate. They send how many revolutions
they have counted since they were switched on, and the time of the most recent
one - and both fields wrap around, because they are 16 or 32 bits wide. The rate
is the difference between two of those samples.

Getting this wrong is quiet rather than loud: a mishandled wrap shows up as one
absurd spike in a ride file, and a repeated packet mistaken for a new event shows
up as a rider who never slows down. Both are handled here, once, for Bluetooth
and ANT+ alike, because both protocols report the same way.
"""

from __future__ import annotations

from dataclasses import dataclass

# Event times live in a 16-bit field. Most sensors count it in 1/1024 of a second,
# so it wraps every 64 seconds - but the Cycling Power characteristic times its
# wheel events in 1/2048, which wraps twice as fast. The rate is the tick count
# divided by the resolution, so a wrong resolution silently halves or doubles it.
TICKS_PER_SECOND = 1024
TIME_MODULUS = 1 << 16
MAX_UNAMBIGUOUS_GAP_S = TIME_MODULUS / TICKS_PER_SECOND

SECONDS_PER_MINUTE = 60.0
MM_PER_M = 1000.0


@dataclass(frozen=True)
class Sample:
    revolutions: int
    event_time: int
    at: float


class RevolutionCounter:
    """Rate in revolutions per second, from cumulative samples.

    ``revolution_bits`` is the width of the counter the device sends: 32 for a
    Bluetooth speed sensor, 16 for cadence and for ANT+. ``ticks_per_second`` is
    the resolution of its event clock, which is not the same for every
    characteristic.
    """

    def __init__(
        self,
        revolution_bits: int = 16,
        stop_after_s: float = 3.0,
        ticks_per_second: int = TICKS_PER_SECOND,
    ) -> None:
        self._modulus = 1 << revolution_bits
        self._stop_after_s = stop_after_s
        self._ticks_per_second = ticks_per_second
        self._max_gap_s = TIME_MODULUS / ticks_per_second
        self._last: Sample | None = None
        self._rate: float | None = None

    @property
    def rate(self) -> float | None:
        """The latest rate, or None before two events have been seen."""
        return self._rate

    def reset(self) -> None:
        self._last = None
        self._rate = None

    def update(self, revolutions: int, event_time: int, now: float) -> float | None:
        """Feed one sample. Returns revolutions per second, or None while unknown.

        ``now`` is a monotonic clock reading, used only to tell a stopped wheel
        from a slow one: a stationary sensor keeps sending its last event
        unchanged, so silence in the event field is the only signal there is.
        """
        last = self._last
        if last is None:
            self._last = Sample(revolutions, event_time, now)
            return None

        elapsed_ticks = (event_time - last.event_time) % TIME_MODULUS
        if elapsed_ticks == 0:
            # The same event, sent again: the wheel has not turned since. There
            # is nothing ambiguous about that however long it goes on, so a
            # standing wheel keeps reading zero instead of blinking out once a
            # minute when the ambiguity window below would otherwise expire.
            if now - last.at >= self._stop_after_s:
                self._rate = 0.0
            return self._rate

        if now - last.at > self._max_gap_s:
            # The event clock has had time to wrap all the way round, so the
            # difference no longer means anything. Start again from here.
            self._last = Sample(revolutions, event_time, now)
            self._rate = None
            return None

        turned = (revolutions - last.revolutions) % self._modulus
        self._last = Sample(revolutions, event_time, now)
        self._rate = turned * self._ticks_per_second / elapsed_ticks
        return self._rate


class WheelSpeed:
    """A wheel speed sensor, read as metres per second."""

    def __init__(
        self,
        rollout_mm: float,
        revolution_bits: int = 32,
        ticks_per_second: int = TICKS_PER_SECOND,
    ) -> None:
        self.rollout_mm = rollout_mm
        self._counter = RevolutionCounter(
            revolution_bits=revolution_bits, ticks_per_second=ticks_per_second
        )

    def update(self, revolutions: int, event_time: int, now: float) -> float | None:
        rate = self._counter.update(revolutions, event_time, now)
        if rate is None:
            return None
        return rate * self.rollout_mm / MM_PER_M

    def reset(self) -> None:
        self._counter.reset()


class Cadence:
    """A crank sensor, read as revolutions per minute."""

    def __init__(
        self,
        revolution_bits: int = 16,
        ticks_per_second: int = TICKS_PER_SECOND,
    ) -> None:
        self._counter = RevolutionCounter(
            revolution_bits=revolution_bits, ticks_per_second=ticks_per_second
        )

    def update(self, revolutions: int, event_time: int, now: float) -> float | None:
        rate = self._counter.update(revolutions, event_time, now)
        if rate is None:
            return None
        return rate * SECONDS_PER_MINUTE

    def reset(self) -> None:
        self._counter.reset()
