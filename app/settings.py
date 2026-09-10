"""User settings, stored as one JSON file inside the static data tree."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from typing import Any

from app import i18n, paths
from app.core import physics
from app.core.control import ControlMode
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
    #: Devices the rider has paired, by id. They are looked for at the start of
    #: a ride and connected if they answer; one that does not is simply absent.
    paired_device_ids: list[str] = field(default_factory=list)
    #: How the trainer is commanded: "off", "erg" or "simulation".
    control_mode: str = ControlMode.SIMULATION.value
    #: The Garmin Connect account to import from. Only the name is kept here;
    #: the password lives in the operating system's credential store.
    garmin_username: str = ""
    #: What the rider last chose to ride, so the application opens on it. Kept
    #: here rather than asked for every time: a rider who rides the same
    #: circuit every week should not have to say so every week.
    world_id: str = "sokol"
    route_id: str = ""
    workout_name: str = ""
    #: Shown to other riders in a room, and only ever sent to a relay the rider
    #: asked to join. Empty until they do.
    rider_name: str = ""
    rider_id: str = ""
    #: What the rider and their bicycle weigh, and how the rider sits. Weight
    #: decides how fast they climb; position decides how fast they go on the
    #: flat, which on a circuit is nearly all of it.
    rider_mass_kg: float = physics.DEFAULT_RIDER_KG
    bike_mass_kg: float = physics.DEFAULT_BIKE_KG
    #: Which virtual bicycle they are riding. A rider on clip-on bars is not a
    #: rider on a time trial bike, and neither is one on the hoods.
    virtual_bike_id: str = physics.DEFAULT_BIKE
    #: A drag figure the rider measured for themselves, which beats the one
    #: their position is listed at - the same way a measured wheel rollout
    #: beats the catalogue's.
    measured_cda_m2: float | None = None

    @property
    def bike(self) -> physics.Bike:
        """The bicycle these settings describe, for the physics to ride."""
        return physics.Bike.ridden_by(
            rider_kg=self.rider_mass_kg,
            bike_kg=self.bike_mass_kg,
            bike_id=self.virtual_bike_id,
            cda_m2=self.measured_cda_m2,
        )

    @property
    def effective_language(self) -> str:
        return i18n.normalise(self.language) if self.language else i18n.system_locale()

    @property
    def trainer_control(self) -> ControlMode:
        """The saved control mode, or leaving the trainer alone if it is unknown."""
        try:
            return ControlMode(self.control_mode)
        except ValueError:
            return ControlMode.OFF

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
