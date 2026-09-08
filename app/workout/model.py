"""What a workout is.

Deliberately small: a workout is steps, a step has a duration and targets, and a
repeat is a group of steps done a number of times. Everything that reads a
workout - the engine, the screen, a trainer being told what resistance to apply -
works from this, so the two import formats have exactly one thing to produce.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum


class WorkoutError(ValueError):
    """A workout nobody could ride."""


class StepKind(StrEnum):
    WARMUP = "warmup"
    INTERVAL = "interval"
    REST = "rest"
    COOLDOWN = "cooldown"


class TargetKind(StrEnum):
    POWER = "power"
    CADENCE = "cadence"
    HEART_RATE = "heart_rate"


class DurationKind(StrEnum):
    TIME = "time"
    DISTANCE = "distance"
    #: Runs until the rider says they are done - a recovery of whatever length
    #: they need, or a warm-up they end when they feel ready.
    OPEN = "open"


@dataclass(frozen=True)
class Target:
    """A range to hold. ``low`` and ``high`` are in the metric's own units."""

    kind: TargetKind
    low: float
    high: float

    def __post_init__(self) -> None:
        if self.high < self.low:
            raise WorkoutError(
                f"{self.kind} target runs from {self.low} to {self.high}, backwards"
            )

    @property
    def middle(self) -> float:
        """What to aim for, and what to set a trainer to in a power step."""
        return (self.low + self.high) / 2

    def holds(self, value: float) -> bool:
        return self.low <= value <= self.high


@dataclass(frozen=True)
class Step:
    """One block of the workout."""

    kind: StepKind
    name: str = ""
    duration_kind: DurationKind = DurationKind.TIME
    #: Seconds for a timed step, metres for a distance one, None when open.
    duration: float | None = None
    targets: tuple[Target, ...] = ()

    def __post_init__(self) -> None:
        if self.duration_kind is DurationKind.OPEN:
            return
        if self.duration is None or self.duration <= 0:
            raise WorkoutError(
                f"step {self.name or self.kind!s} is {self.duration_kind} "
                "but says nothing about how long"
            )

    def target(self, kind: TargetKind) -> Target | None:
        for item in self.targets:
            if item.kind is kind:
                return item
        return None

    @property
    def power(self) -> Target | None:
        return self.target(TargetKind.POWER)

    @property
    def is_open(self) -> bool:
        return self.duration_kind is DurationKind.OPEN

    @property
    def label(self) -> str:
        return self.name or self.kind.replace("_", " ").title()


@dataclass(frozen=True)
class Repeat:
    """A group of steps, done more than once."""

    count: int
    steps: tuple[Step | Repeat, ...]

    def __post_init__(self) -> None:
        if self.count < 1:
            raise WorkoutError("a repeat has to happen at least once")
        if not self.steps:
            raise WorkoutError("a repeat with no steps in it repeats nothing")


Element = Step | Repeat


def flatten(elements: Sequence[Element]) -> Iterator[Step]:
    """Expand repeats into the plain run of steps the rider actually does."""
    for element in elements:
        if isinstance(element, Repeat):
            for _ in range(element.count):
                yield from flatten(element.steps)
        else:
            yield element


@dataclass(frozen=True)
class Workout:
    """A whole session."""

    name: str
    steps: tuple[Element, ...]
    description: str = ""
    sport: str = "cycling"
    ftp_watts: int | None = None
    source: str = ""

    def __post_init__(self) -> None:
        if not self.steps:
            raise WorkoutError(f"workout {self.name!r} has no steps")

    @property
    def ridden_steps(self) -> tuple[Step, ...]:
        """Every step in the order it happens, repeats expanded."""
        return tuple(flatten(self.steps))

    @property
    def has_open_steps(self) -> bool:
        return any(step.is_open for step in self.ridden_steps)

    @property
    def total_time_s(self) -> float | None:
        """How long it takes, or None when a step runs until the rider stops it."""
        total = 0.0
        for step in self.ridden_steps:
            if step.duration_kind is DurationKind.TIME and step.duration is not None:
                total += step.duration
            else:
                return None
        return total


@dataclass
class WorkoutLibrary:
    """The workouts the rider has to choose from."""

    workouts: tuple[Workout, ...] = field(default_factory=tuple)

    def __len__(self) -> int:
        return len(self.workouts)

    def __iter__(self) -> Iterator[Workout]:
        return iter(self.workouts)

    def named(self, name: str) -> Workout:
        for workout in self.workouts:
            if workout.name == name:
                return workout
        raise WorkoutError(f"no workout named {name!r}")
