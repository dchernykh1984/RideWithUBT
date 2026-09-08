"""User settings, stored as one JSON file inside the static data tree."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from typing import Any

from app import i18n, paths


@dataclass
class Settings:
    """Everything the app remembers between runs.

    ``language`` is empty when the user has not chosen one; the app then follows
    the system language, so a fresh install is localised without being asked.
    """

    language: str = ""

    @property
    def effective_language(self) -> str:
        return i18n.normalise(self.language) if self.language else i18n.system_locale()

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
