"""The trainer catalogue.

One JSON file per trainer under ``app/data/trainers``, so adding a trainer is a
one-file pull request that cannot conflict with anyone else's. Ids are stable and
are what settings store.

**The catalogue is a hint, not an authority.** What a connected device actually
supports is discovered when it connects; the entries here exist so a rider can
pick their trainer before anything is plugged in, and so an uncalibrated
estimate knows which family of resistance it is estimating. Where the two
disagree, the device wins.

Most entries carry no profile yet: ``profile`` is null until someone records one
against a real power meter and contributes it back.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.trainer.power import PowerCurve, generic_curve

DATA_DIR = Path(__file__).parent.parent / "data" / "trainers"

KINDS = frozenset({"direct_drive", "wheel_on", "roller"})
RESISTANCES = frozenset({"fluid", "air", "magnetic", "electromagnetic", "motor_brake"})
PROTOCOLS = frozenset({"ftms", "fec"})


class UnknownTrainerError(LookupError):
    """No trainer with that id."""


class TrainerDataError(ValueError):
    """A catalogue file is malformed."""


@dataclass(frozen=True)
class TrainerProfile:
    """A curve measured from a real trainer, with the context that makes it reusable.

    A curve on its own is not: the same trainer on a different tyre, a different
    pressure or a different resistance lever is a different curve, so a profile
    that does not say which is not worth reusing.
    """

    curve: PowerCurve
    samples: int
    rms_error_w: float
    speed_range_kmh: tuple[float, float]
    recorded_at: str
    wheel: str
    tyre_pressure_bar: float | None = None
    resistance_setting: str | None = None
    contributor: str | None = None


@dataclass(frozen=True)
class Trainer:
    id: str
    brand: str
    model: str
    kind: str
    resistance: str
    protocols: tuple[str, ...]
    profile: TrainerProfile | None = None
    notes: str = ""

    @property
    def name(self) -> str:
        return f"{self.brand} {self.model}"

    @property
    def is_smart(self) -> bool:
        """Does it speak a protocol we can read power from and write resistance to?"""
        return bool(self.protocols)

    @property
    def reports_own_power(self) -> bool:
        """Smart trainers measure power; for the rest the app has to estimate it."""
        return self.is_smart

    @property
    def is_calibrated(self) -> bool:
        return self.profile is not None

    def power_curve(self) -> PowerCurve | None:
        """The best curve available, or None when estimating would be wrong.

        A recorded profile first, then the generic curve for this resistance type.
        None means the trainer measures its own power and should be believed
        instead of estimated.
        """
        if self.profile is not None:
            return self.profile.curve
        return generic_curve(self.resistance)


def _require(raw: dict[str, Any], key: str, path: Path) -> Any:
    if key not in raw:
        raise TrainerDataError(f"{path.name}: missing {key!r}")
    return raw[key]


def _parse_profile(raw: dict[str, Any] | None) -> TrainerProfile | None:
    if raw is None:
        return None
    low, high = raw["speed_range_kmh"]
    return TrainerProfile(
        curve=PowerCurve(
            coefficient=float(raw["coefficient"]),
            exponent=float(raw["exponent"]),
            offset_w=float(raw.get("offset_w", 0.0)),
        ),
        samples=int(raw["samples"]),
        rms_error_w=float(raw["rms_error_w"]),
        speed_range_kmh=(float(low), float(high)),
        recorded_at=str(raw["recorded_at"]),
        wheel=str(raw["wheel"]),
        tyre_pressure_bar=raw.get("tyre_pressure_bar"),
        resistance_setting=raw.get("resistance_setting"),
        contributor=raw.get("contributor"),
    )


def parse_trainer(raw: dict[str, Any], path: Path) -> Trainer:
    kind = _require(raw, "kind", path)
    resistance = _require(raw, "resistance", path)
    protocols = tuple(_require(raw, "protocols", path))
    if kind not in KINDS:
        raise TrainerDataError(f"{path.name}: unknown kind {kind!r}")
    if resistance not in RESISTANCES:
        raise TrainerDataError(f"{path.name}: unknown resistance {resistance!r}")
    unknown = set(protocols) - PROTOCOLS
    if unknown:
        raise TrainerDataError(f"{path.name}: unknown protocols {sorted(unknown)}")
    trainer_id = str(_require(raw, "id", path))
    if trainer_id != path.stem:
        raise TrainerDataError(
            f"{path.name}: id {trainer_id!r} does not match the file name"
        )
    return Trainer(
        id=trainer_id,
        brand=str(_require(raw, "brand", path)),
        model=str(_require(raw, "model", path)),
        kind=kind,
        resistance=resistance,
        protocols=protocols,
        profile=_parse_profile(raw.get("profile")),
        notes=str(raw.get("notes", "")),
    )


@dataclass(frozen=True)
class TrainerCatalogue:
    trainers: tuple[Trainer, ...]

    def __iter__(self) -> Iterator[Trainer]:
        return iter(self.trainers)

    def __len__(self) -> int:
        return len(self.trainers)

    def get(self, trainer_id: str) -> Trainer:
        for trainer in self.trainers:
            if trainer.id == trainer_id:
                return trainer
        raise UnknownTrainerError(f"unknown trainer {trainer_id!r}")

    def by_brand(self) -> dict[str, tuple[Trainer, ...]]:
        """Grouped for a picker, brands in alphabetical order."""
        grouped: dict[str, list[Trainer]] = {}
        for trainer in self.trainers:
            grouped.setdefault(trainer.brand, []).append(trainer)
        return {brand: tuple(grouped[brand]) for brand in sorted(grouped)}


def load_catalogue(directory: Path = DATA_DIR) -> TrainerCatalogue:
    """Read every trainer file in a directory. File name and id must agree."""
    trainers = []
    for path in sorted(directory.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        trainers.append(parse_trainer(raw, path))
    return TrainerCatalogue(tuple(trainers))


@lru_cache(maxsize=1)
def catalogue() -> TrainerCatalogue:
    """The shipped catalogue, read once."""
    return load_catalogue()
