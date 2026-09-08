"""Running a workout alongside a ride.

The engine watches; it never drives. It is told how much time and distance have
passed and how hard the rider is pushing, and it answers which step they are in,
how much of it is left and whether they are holding the target. What the screen
does with that, and whether a smart trainer is told to hold the target power, are
decisions made elsewhere.

Two things it gets right that are easy to get wrong:

* **Time that overruns a step carries into the next one.** A step that ends half
  way through an update must not throw the other half away, or a workout of
  thirty-second intervals drifts by a frame every interval.
* **An open step never ends on its own.** It runs until the rider says so, which
  is the whole point of one.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.workout.model import DurationKind, Step, TargetKind, Workout


@dataclass(frozen=True)
class StepProgress:
    """Where the rider is inside the current step."""

    index: int
    step: Step
    elapsed_s: float
    covered_m: float
    #: Seconds or metres left, whichever the step measures; None when open.
    remaining: float | None
    #: Zero to one through the step; None when open, because there is no end yet.
    fraction: float | None
    next_step: Step | None
    #: Whether the rider is inside the power target, or None when there is no
    #: power target or no power to compare it with.
    on_target: bool | None


@dataclass(frozen=True)
class WorkoutProgress:
    """The whole workout's state, for a screen or a recorder."""

    step: StepProgress | None
    total_elapsed_s: float
    steps_done: int
    steps_total: int
    finished: bool

    @property
    def steps_left(self) -> int:
        return self.steps_total - self.steps_done


class WorkoutEngine:
    """Tracks a workout as a ride goes on."""

    def __init__(self, workout: Workout) -> None:
        self.workout = workout
        self.steps = workout.ridden_steps
        self.index = 0
        self.total_elapsed_s = 0.0
        self.step_elapsed_s = 0.0
        self.step_covered_m = 0.0
        self._power_w: float | None = None

    @property
    def finished(self) -> bool:
        return self.index >= len(self.steps)

    @property
    def current(self) -> Step | None:
        return None if self.finished else self.steps[self.index]

    @property
    def upcoming(self) -> Step | None:
        following = self.index + 1
        return self.steps[following] if following < len(self.steps) else None

    def update(
        self, seconds: float, metres: float = 0.0, power_w: float | None = None
    ) -> WorkoutProgress:
        """Advance the workout by one step of the ride."""
        self._power_w = power_w
        self.total_elapsed_s += seconds
        self._consume(seconds, metres)
        return self.progress()

    def _consume(self, seconds: float, metres: float) -> None:
        """Spend time and distance, moving on as steps are completed."""
        while not self.finished and (seconds > 0.0 or metres > 0.0):
            step = self.steps[self.index]
            left = self._left_in(step)
            if left is None:
                # Open: it takes everything and still is not finished.
                self.step_elapsed_s += seconds
                self.step_covered_m += metres
                return
            spent = seconds if step.duration_kind is DurationKind.TIME else metres
            if spent < left:
                self.step_elapsed_s += seconds
                self.step_covered_m += metres
                return
            # The step ends part way through: finish it and carry the rest over.
            share = left / spent if spent > 0 else 0.0
            self.advance()
            seconds -= seconds * share
            metres -= metres * share

    def _left_in(self, step: Step) -> float | None:
        if step.duration_kind is DurationKind.OPEN or step.duration is None:
            return None
        if step.duration_kind is DurationKind.TIME:
            return max(step.duration - self.step_elapsed_s, 0.0)
        return max(step.duration - self.step_covered_m, 0.0)

    def advance(self) -> None:
        """Move to the next step. This is what a rider ending an open step does."""
        if self.finished:
            return
        self.index += 1
        self.step_elapsed_s = 0.0
        self.step_covered_m = 0.0

    def progress(self) -> WorkoutProgress:
        return WorkoutProgress(
            step=self._step_progress(),
            total_elapsed_s=self.total_elapsed_s,
            steps_done=min(self.index, len(self.steps)),
            steps_total=len(self.steps),
            finished=self.finished,
        )

    def _step_progress(self) -> StepProgress | None:
        step = self.current
        if step is None:
            return None
        left = self._left_in(step)
        fraction = None
        if left is not None and step.duration:
            fraction = min(max(1.0 - left / step.duration, 0.0), 1.0)
        return StepProgress(
            index=self.index,
            step=step,
            elapsed_s=self.step_elapsed_s,
            covered_m=self.step_covered_m,
            remaining=left,
            fraction=fraction,
            next_step=self.upcoming,
            on_target=self._on_target(step),
        )

    def _on_target(self, step: Step) -> bool | None:
        target = step.target(TargetKind.POWER)
        if target is None or self._power_w is None:
            return None
        return target.holds(self._power_w)
