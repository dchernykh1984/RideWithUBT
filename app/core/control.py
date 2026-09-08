"""Deciding what to ask a smart trainer for.

Two modes, and the rider picks. In **ERG** the trainer holds the workout's target
power whatever the rider spins at, which is what makes an interval an interval.
In **simulation** it makes the pedals as heavy as the slope under the rider,
which is what makes a course a course. There is also off, which leaves the
trainer's own resistance alone.

The other half of this module's job is not sending commands. A trainer takes a
command over a radio that also carries its readings, and asking it something
sixty times a second floods that: the rider sees stuttering data and the trainer
lags behind the course. So a command only goes out when the value actually moved
enough to feel, or when it has been quiet long enough to be worth repeating.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ControlMode(StrEnum):
    OFF = "off"
    ERG = "erg"
    SIMULATION = "simulation"


class CommandKind(StrEnum):
    TARGET_POWER = "target_power"
    SIMULATION = "simulation"


@dataclass(frozen=True)
class Command:
    """What to ask the trainer for. The transport turns this into bytes."""

    kind: CommandKind
    value: float

    @property
    def watts(self) -> float:
        return self.value

    @property
    def grade_percent(self) -> float:
        return self.value


# A rider cannot feel five watts on a trainer, nor a tenth of a percent of slope,
# so anything smaller is not worth a radio message.
POWER_STEP_W = 5.0
GRADE_STEP_PERCENT = 0.1
# How long a value may stand before it is sent again, in case the trainer missed
# it or was reset.
REFRESH_AFTER_S = 10.0
# The floor on how often anything at all is sent.
MIN_INTERVAL_S = 0.5


@dataclass
class TrainerDirector:
    """Turns the ride into a stream of commands, as sparse as it can be."""

    mode: ControlMode = ControlMode.OFF
    power_step_w: float = POWER_STEP_W
    grade_step_percent: float = GRADE_STEP_PERCENT
    refresh_after_s: float = REFRESH_AFTER_S
    min_interval_s: float = MIN_INTERVAL_S
    _last: Command | None = None
    _sent_at: float = 0.0

    @property
    def last_command(self) -> Command | None:
        return self._last

    def reset(self) -> None:
        """Forget what was sent, so the next command goes out whatever it is."""
        self._last = None
        self._sent_at = 0.0

    def update(
        self,
        now: float,
        gradient: float = 0.0,
        target_w: float | None = None,
    ) -> Command | None:
        """The command to send this instant, or None if there is nothing to say.

        ``gradient`` is rise over run, as the track reports it; ``target_w`` is
        the workout's current power target, or None when there is no workout or
        the step does not name one.
        """
        wanted = self._wanted(gradient, target_w)
        if wanted is None:
            return None
        if not self._worth_sending(wanted, now):
            return None
        self._last = wanted
        self._sent_at = now
        return wanted

    def _wanted(self, gradient: float, target_w: float | None) -> Command | None:
        if self.mode is ControlMode.ERG:
            if target_w is None:
                # An ERG workout in a step with no power target - a free warm-up,
                # say - has nothing to hold, so the trainer is left alone.
                return None
            return Command(CommandKind.TARGET_POWER, target_w)
        if self.mode is ControlMode.SIMULATION:
            return Command(CommandKind.SIMULATION, gradient * 100.0)
        return None

    def _worth_sending(self, wanted: Command, now: float) -> bool:
        last = self._last
        if last is None:
            return True
        if now - self._sent_at < self.min_interval_s:
            return False
        if last.kind is not wanted.kind:
            return True
        if now - self._sent_at >= self.refresh_after_s:
            return True
        step = (
            self.power_step_w
            if wanted.kind is CommandKind.TARGET_POWER
            else self.grade_step_percent
        )
        return abs(wanted.value - last.value) >= step
