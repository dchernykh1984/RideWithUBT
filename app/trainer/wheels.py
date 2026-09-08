"""Wheel sizes, tyre widths and rollout.

Rollout - the distance covered by one wheel revolution - is what turns a speed
sensor's revolutions into speed, and speed is what a trainer's resistance curve
turns into watts. Every error here is multiplied through both steps, which is
why a measured value always beats a computed one.

The catalogue itself is data (``app/data/wheels.json``): adding a size or a width
is a data change, not a code change.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_FILE = Path(__file__).parent.parent / "data" / "wheels.json"

# Below this a "rollout" is a typo, above it a unit mix-up: a 700c wheel is about
# 2100 mm and the smallest wheel in the catalogue is about 1400 mm.
MIN_ROLLOUT_MM = 900.0
MAX_ROLLOUT_MM = 2600.0


class UnknownWheelError(LookupError):
    """A size or width that is not in the catalogue."""


@dataclass(frozen=True)
class TyreWidth:
    """One tyre width offered for a size, in millimetres.

    ``id`` is what the setting stores and what the user sees: millimetres for
    road tyres ("25"), inches for mountain bike tyres ("2.1in"), because that is
    how each is written on the sidewall.
    """

    id: str
    mm: float


@dataclass(frozen=True)
class WheelSize:
    """A rim standard, identified by its ISO bead seat diameter."""

    id: str
    bead_seat_mm: int
    aliases: tuple[str, ...]
    widths: tuple[TyreWidth, ...]

    def width(self, width_id: str) -> TyreWidth:
        for width in self.widths:
            if width.id == width_id:
                return width
        raise UnknownWheelError(f"{self.id} has no tyre width {width_id!r}")

    def rollout_mm(self, width_id: str) -> float:
        return nominal_rollout_mm(self.bead_seat_mm, self.width(width_id).mm)


def nominal_rollout_mm(bead_seat_mm: float, tyre_width_mm: float) -> float:
    """Rollout from geometry: the tyre adds its own width above and below the rim.

    A loaded tyre rolls slightly shorter than this - the contact patch flattens -
    so treat the result as a starting point, not a measurement. Riders who care
    about the last percent should measure their own rollout and enter it.
    """
    return math.pi * (bead_seat_mm + 2.0 * tyre_width_mm)


@dataclass(frozen=True)
class WheelCatalogue:
    sizes: tuple[WheelSize, ...]

    def size(self, size_id: str) -> WheelSize:
        """Look a size up by its id or by any of its aliases ("29in" is "700c")."""
        for size in self.sizes:
            if size_id == size.id or size_id in size.aliases:
                return size
        raise UnknownWheelError(f"unknown wheel size {size_id!r}")

    @property
    def size_ids(self) -> tuple[str, ...]:
        return tuple(size.id for size in self.sizes)


def parse_size(raw: dict[str, Any]) -> WheelSize:
    """Build one size from its catalogue entry, refusing an unusable one."""
    widths = raw["widths"]
    if not widths:
        raise ValueError(f"wheel size {raw.get('id')!r} lists no tyre widths")
    return WheelSize(
        id=str(raw["id"]),
        bead_seat_mm=int(raw["bead_seat_mm"]),
        aliases=tuple(str(alias) for alias in raw.get("aliases", ())),
        widths=tuple(
            TyreWidth(id=str(width["id"]), mm=float(width["mm"])) for width in widths
        ),
    )


@lru_cache(maxsize=1)
def catalogue() -> WheelCatalogue:
    """The shipped wheel catalogue, read once."""
    document = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return WheelCatalogue(tuple(parse_size(raw) for raw in document["sizes"]))


@dataclass(frozen=True)
class Wheel:
    """The wheel the rider actually has.

    Either a catalogue pick (size plus width) or a rollout measured by hand. The
    measured value wins when both are present, because someone who went to the
    trouble of measuring meant it.
    """

    size_id: str | None = None
    width_id: str | None = None
    measured_rollout_mm: float | None = None

    def __post_init__(self) -> None:
        if self.measured_rollout_mm is not None:
            if not MIN_ROLLOUT_MM <= self.measured_rollout_mm <= MAX_ROLLOUT_MM:
                raise ValueError(
                    f"measured rollout {self.measured_rollout_mm} mm is outside "
                    f"{MIN_ROLLOUT_MM:.0f}-{MAX_ROLLOUT_MM:.0f} mm; "
                    "it is probably in the wrong unit"
                )
            return
        if self.size_id is None or self.width_id is None:
            raise ValueError(
                "a wheel needs either a measured rollout or both a size and a width"
            )

    @property
    def is_measured(self) -> bool:
        return self.measured_rollout_mm is not None

    @property
    def rollout_mm(self) -> float:
        if self.measured_rollout_mm is not None:
            return self.measured_rollout_mm
        size_id, width_id = self.size_id, self.width_id
        if size_id is None or width_id is None:  # pragma: no cover - __post_init__
            raise ValueError("wheel has neither a rollout nor a size and width")
        return catalogue().size(size_id).rollout_mm(width_id)

    def speed_ms(self, revolutions_per_second: float) -> float:
        """Wheel speed from a speed sensor's revolution rate."""
        return revolutions_per_second * self.rollout_mm / 1000.0
