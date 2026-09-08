"""Reverse direction: measure a trainer's curve and hand it back to the project.

With a power meter on the bike and a speed sensor on the wheel, every second of
riding is one (speed, power) pair. Enough of them across a wide enough range fit
into the curve the next rider with that trainer gets to use instead of a guess.

This module is the arithmetic and the file format. Collecting the samples from
live sensors, and the screen that drives it, come with the sensor layer; the
recorder is deliberately fed by hand so it can be tested without a device.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.trainer.catalog import Trainer, TrainerProfile
from app.trainer.power import CurveFit, NotEnoughDataError, fit_power_curve
from app.trainer.wheels import Wheel

# A fit worse than this is not describing a trainer, it is describing a rider who
# changed the resistance lever half way through. Refuse to publish it.
MAX_PUBLISHABLE_RMS_W = 25.0


@dataclass
class ProfileRecorder:
    """Accumulates measured pairs for one trainer at one resistance setting.

    The resistance setting matters as much as the trainer model: a magnetic unit
    on level 3 and the same unit on level 7 are two different curves, and mixing
    their samples produces one that describes neither.
    """

    trainer: Trainer
    wheel: Wheel
    resistance_setting: str | None = None
    tyre_pressure_bar: float | None = None
    samples: list[tuple[float, float]] = field(default_factory=list)

    def add(self, speed_ms: float, power_w: float) -> None:
        self.samples.append((speed_ms, power_w))

    def fit(self) -> CurveFit:
        """Fit the samples, raising NotEnoughDataError while they are too thin."""
        return fit_power_curve(self.samples)

    def can_publish(self) -> bool:
        """Would this recording produce a profile worth contributing?"""
        try:
            fit = self.fit()
        except NotEnoughDataError:
            return False
        return fit.rms_error_w <= MAX_PUBLISHABLE_RMS_W

    def build(
        self, contributor: str | None = None, recorded_at: datetime | None = None
    ) -> TrainerProfile:
        fit = self.fit()
        moment = recorded_at or datetime.now(UTC)
        return TrainerProfile(
            curve=fit.curve,
            samples=fit.samples,
            rms_error_w=fit.rms_error_w,
            speed_range_kmh=fit.speed_range_kmh,
            recorded_at=moment.date().isoformat(),
            wheel=describe_wheel(self.wheel),
            tyre_pressure_bar=self.tyre_pressure_bar,
            resistance_setting=self.resistance_setting,
            contributor=contributor,
        )

    def as_catalogue_entry(
        self, contributor: str | None = None, recorded_at: datetime | None = None
    ) -> dict[str, Any]:
        """The trainer's catalogue file, with this profile filled in.

        Writing it over ``app/data/trainers/<id>.json`` and opening a pull request
        is the whole contribution: the file is the format the catalogue reads.
        """
        profile = self.build(contributor=contributor, recorded_at=recorded_at)
        return {
            "id": self.trainer.id,
            "brand": self.trainer.brand,
            "model": self.trainer.model,
            "kind": self.trainer.kind,
            "resistance": self.trainer.resistance,
            "protocols": list(self.trainer.protocols),
            "profile": {
                "coefficient": round(profile.curve.coefficient, 6),
                "exponent": round(profile.curve.exponent, 4),
                "offset_w": round(profile.curve.offset_w, 3),
                "samples": profile.samples,
                "rms_error_w": round(profile.rms_error_w, 2),
                "speed_range_kmh": [
                    round(value, 1) for value in profile.speed_range_kmh
                ],
                "recorded_at": profile.recorded_at,
                "wheel": profile.wheel,
                "tyre_pressure_bar": profile.tyre_pressure_bar,
                "resistance_setting": profile.resistance_setting,
                "contributor": profile.contributor,
            },
            "notes": self.trainer.notes,
        }


def describe_wheel(wheel: Wheel) -> str:
    """A one-line description of the wheel a profile was recorded on."""
    if wheel.is_measured:
        return f"measured rollout {wheel.rollout_mm:.0f} mm"
    return f"{wheel.size_id} x {wheel.width_id} ({wheel.rollout_mm:.0f} mm)"
