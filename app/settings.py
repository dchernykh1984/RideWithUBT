"""User settings, stored as one JSON file inside the static data tree."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from typing import Any

from app import i18n, paths
from app.trainer.catalog import Trainer, UnknownTrainerError
from app.trainer.catalog import catalogue as trainer_catalogue
from app.trainer.wheels import UnknownWheelError, Wheel


@dataclass
class Settings:
    """Everything the app remembers between runs.

    ``language`` is empty when the user has not chosen one; the app then follows
    the system language, so a fresh install is localised without being asked.
    """

    language: str = ""
    trainer_id: str = ""
    wheel_size_id: str = ""
    wheel_width_id: str = ""
    measured_rollout_mm: float | None = None
    # Recording a trainer's power curve is a deliberate mode, not a background
    # habit: it is only useful with a power meter fitted, and the rider has to
    # know it is happening before they are asked to contribute the result.
    record_trainer_data: bool = False

    @property
    def effective_language(self) -> str:
        return i18n.normalise(self.language) if self.language else i18n.system_locale()

    @property
    def wheel(self) -> Wheel | None:
        """The configured wheel, or None while it is still unset or unusable.

        Unusable rather than fatal: a catalogue entry can disappear between
        versions, and a rider whose saved size no longer exists should be asked
        again, not stopped at startup.
        """
        if self.measured_rollout_mm is not None:
            return Wheel(measured_rollout_mm=self.measured_rollout_mm)
        if not (self.wheel_size_id and self.wheel_width_id):
            return None
        wheel = Wheel(size_id=self.wheel_size_id, width_id=self.wheel_width_id)
        try:
            # Resolving the rollout is what proves the saved size and width are
            # still in the catalogue; the value itself is not needed here.
            _ = wheel.rollout_mm
        except UnknownWheelError:
            return None
        return wheel

    @property
    def trainer(self) -> Trainer | None:
        """The configured trainer, or None while it is unset or no longer shipped."""
        if not self.trainer_id:
            return None
        try:
            return trainer_catalogue().get(self.trainer_id)
        except UnknownTrainerError:
            return None

    @classmethod
    def load(cls) -> Settings:
        """Read the settings file, falling back to defaults if it is unusable."""
        path = paths.settings_file()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return cls()
        if not isinstance(raw, dict):
            return cls()
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Settings:
        """Build settings from raw JSON, ignoring keys this version does not know.

        Unknown keys are dropped rather than rejected so that opening an older
        build after a newer one does not wipe the file.
        """
        known = {field.name for field in fields(cls)}
        return cls(**{key: value for key, value in raw.items() if key in known})

    def save(self) -> None:
        paths.ensure_data_tree()
        paths.settings_file().write_text(
            json.dumps(asdict(self), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
