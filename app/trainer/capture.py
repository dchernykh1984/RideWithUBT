"""Measuring a trainer while riding it.

The reverse direction, driven by live sensors. With a power meter on the bike and
a speed sensor on the wheel, every second of riding is one (wheel speed, power)
pair, and enough of them across a wide enough range fit into the curve the next
rider with that trainer gets to use instead of a guess.

**The speed this uses is the wheel's, not the ride's.** The speed on screen is
what the course and the physics say the rider is doing; the trainer only knows
how fast its own roller is turning. Fitting the ride's speed would produce a
curve describing the virtual world rather than the trainer, and it would look
entirely plausible.

For the same reason both readings have to be *measured*. An estimated power comes
from a trainer curve, so fitting it would rediscover the curve it came from.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.sensors.types import RideSnapshot
from app.trainer.catalog import Trainer
from app.trainer.power import MIN_FIT_SAMPLES, NotEnoughDataError
from app.trainer.recording import MAX_PUBLISHABLE_RMS_W, ProfileRecorder
from app.trainer.wheels import Wheel

# Samples closer together than this add nothing but weight: a trainer's curve
# does not move in a tenth of a second, and a thousand near-identical points
# make a fit that looks better than it is.
MIN_SAMPLE_GAP_S = 0.5


@dataclass(frozen=True)
class CaptureReport:
    """What has been measured so far, and whether it is worth contributing."""

    samples: int
    publishable: bool
    rms_error_w: float | None = None
    speed_range_kmh: tuple[float, float] | None = None
    reason: str = ""

    @property
    def progress(self) -> float:
        """How far along the minimum sample count this recording is, zero to one."""
        return min(self.samples / MIN_FIT_SAMPLES, 1.0)


@dataclass
class TrainerCapture:
    """Collects a trainer's curve from live readings."""

    trainer: Trainer
    wheel: Wheel
    resistance_setting: str | None = None
    tyre_pressure_bar: float | None = None
    _recorder: ProfileRecorder | None = None
    _last_at: float | None = None

    def __post_init__(self) -> None:
        self._recorder = ProfileRecorder(
            trainer=self.trainer,
            wheel=self.wheel,
            resistance_setting=self.resistance_setting,
            tyre_pressure_bar=self.tyre_pressure_bar,
        )

    @property
    def recorder(self) -> ProfileRecorder:
        assert self._recorder is not None  # noqa: S101 - built in __post_init__
        return self._recorder

    @property
    def samples(self) -> int:
        return len(self.recorder.samples)

    def observe(self, snapshot: RideSnapshot) -> bool:
        """Take a sample if this reading can honestly contribute one."""
        speed, power = snapshot.speed, snapshot.power
        if speed is None or power is None:
            return False
        if speed.estimated or power.estimated:
            # An estimate came from a trainer curve; fitting it would rediscover
            # the curve it came from.
            return False
        if self._last_at is not None and snapshot.at - self._last_at < MIN_SAMPLE_GAP_S:
            return False
        self._last_at = snapshot.at
        self.recorder.add(speed.value, power.value)
        return True

    def report(self) -> CaptureReport:
        try:
            fit = self.recorder.fit()
        except NotEnoughDataError as error:
            return CaptureReport(
                samples=self.samples, publishable=False, reason=str(error)
            )
        publishable = fit.rms_error_w <= MAX_PUBLISHABLE_RMS_W
        return CaptureReport(
            samples=fit.samples,
            publishable=publishable,
            rms_error_w=fit.rms_error_w,
            speed_range_kmh=fit.speed_range_kmh,
            reason=""
            if publishable
            else (
                f"the fit is out by {fit.rms_error_w:.0f} W, more than the "
                f"{MAX_PUBLISHABLE_RMS_W:.0f} W a reusable profile may be - "
                "ride it again at one fixed resistance setting"
            ),
        )

    def write_contribution(
        self, directory: Path, contributor: str | None = None
    ) -> Path:
        """Write the trainer's catalogue file, with this profile filled in.

        The file is exactly what `app/data/trainers` holds, so contributing it is
        copying one file into the repository and opening a pull request.
        """
        entry = self.recorder.as_catalogue_entry(contributor=contributor)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.trainer.id}.json"
        path.write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
        return path
