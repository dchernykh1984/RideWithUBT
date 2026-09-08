"""Forward direction: a speed sensor and a wheel size, turned into watts."""

from __future__ import annotations

from dataclasses import dataclass

from app.trainer.catalog import Trainer
from app.trainer.wheels import Wheel


@dataclass(frozen=True)
class PowerEstimate:
    """Watts, and how much they should be trusted.

    ``calibrated`` is false when the number came from a generic curve rather than
    a profile recorded from this model. It travels with the value on purpose:
    every screen that shows estimated power has to be able to say so, and a
    workout that targets watts has to know it is steering by an estimate.
    """

    watts: float
    calibrated: bool


@dataclass(frozen=True)
class PowerEstimator:
    """Combines the rider's wheel with their trainer's curve."""

    wheel: Wheel
    trainer: Trainer

    @property
    def available(self) -> bool:
        """False when this trainer measures its own power and should be read instead."""
        return self.trainer.power_curve() is not None

    @property
    def calibrated(self) -> bool:
        return self.trainer.is_calibrated

    def from_speed(self, speed_ms: float) -> PowerEstimate | None:
        curve = self.trainer.power_curve()
        if curve is None:
            return None
        return PowerEstimate(watts=curve.power_w(speed_ms), calibrated=self.calibrated)

    def from_wheel_revolutions(
        self, revolutions_per_second: float
    ) -> PowerEstimate | None:
        """The path a real speed sensor takes: revolutions, then rollout, then watts."""
        return self.from_speed(self.wheel.speed_ms(revolutions_per_second))
