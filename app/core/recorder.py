"""Keeping a ride.

The session produces a `RideState` every frame, which is far more often than a
ride needs recording: FIT files are read a second at a time, and so is every
service they are uploaded to. So the recorder samples rather than stores
everything, and it samples on ride time rather than wall time, which keeps a
recording honest across a slow frame.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.session import RideState
from app.storage import activities
from app.storage.activity import RideSample, encode_activity

DEFAULT_INTERVAL_S = 1.0


class RideRecorder:
    """Collects a ride, a sample at a time, and writes it out at the end."""

    def __init__(
        self,
        started_at: datetime | None = None,
        interval_s: float = DEFAULT_INTERVAL_S,
    ) -> None:
        self.started_at = started_at or datetime.now(UTC)
        self.interval_s = interval_s
        self.samples: list[RideSample] = []
        self._next_at_s = 0.0

    @property
    def is_empty(self) -> bool:
        return not self.samples

    def observe(self, state: RideState) -> None:
        """Take a sample if enough ride time has passed since the last one."""
        if state.elapsed_s < self._next_at_s:
            return
        self._next_at_s = state.elapsed_s + self.interval_s
        self.samples.append(
            RideSample(
                at=self.started_at + timedelta(seconds=state.elapsed_s),
                distance_m=state.distance_m,
                speed_ms=state.speed_ms,
                altitude_m=state.point.z,
                power_w=state.power_w,
                cadence_rpm=state.cadence_rpm,
                heart_rate_bpm=state.heart_rate_bpm,
            )
        )

    def to_fit(self) -> bytes:
        return encode_activity(self.samples)

    def save(self, directory: Path | None = None) -> Path:
        """Write the ride into the activity store."""
        return activities.save(self.to_fit(), self.started_at, directory)
