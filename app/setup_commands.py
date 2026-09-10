"""Choosing the bike, the trainer and how the trainer is driven.

The catalogues have been there since the beginning and nothing could pick from
them: a rider's wheel and trainer lived in the settings file and the only way to
put them there was to edit it by hand. This is that missing half - listing what
there is, and choosing from it - kept apart from the command line's own parsing
so it can be tested as behaviour rather than as output.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core import physics
from app.core.control import ControlMode
from app.settings import Settings
from app.trainer import catalog, wheels
from app.trainer.estimate import PowerEstimator
from app.trainer.wheels import UnknownWheelError, Wheel


@dataclass(frozen=True)
class Answer:
    """What to tell the rider, and whether they got what they asked for."""

    lines: tuple[str, ...]
    ok: bool = True

    @classmethod
    def say(cls, *lines: str) -> Answer:
        return cls(lines=lines)

    @classmethod
    def refuse(cls, *lines: str) -> Answer:
        return cls(lines=lines, ok=False)


def list_wheels() -> Answer:
    """Every rim standard and the tyre widths it takes."""
    lines = []
    for size in wheels.catalogue().sizes:
        also = f"  (also {', '.join(size.aliases)})" if size.aliases else ""
        lines.append(f"{size.id}  ISO {size.bead_seat_mm}{also}")
        lines.append("    " + "  ".join(width.id for width in size.widths))
    return Answer.say(*lines)


def list_trainers() -> Answer:
    """The catalogue, by brand, saying which have a measured curve."""
    lines = []
    for brand, trainers in catalog.catalogue().by_brand().items():
        lines.append(brand)
        for trainer in trainers:
            marks = []
            if trainer.is_smart:
                marks.append("smart")
            marks.append("measured" if trainer.is_calibrated else "estimated")
            lines.append(f"    {trainer.id:38} {trainer.model}  ({', '.join(marks)})")
    return Answer.say(*lines)


def list_bikes() -> Answer:
    """What there is to ride, and what each one is worth on the flat."""
    settings = Settings.load()
    air = physics.Air.at_altitude(600.0)
    lines = ["At 250 W on the flat, for the rider's own weight:"]
    for bike in physics.BIKES:
        ridden = physics.Bike.ridden_by(
            rider_kg=settings.rider_mass_kg,
            bike_kg=settings.bike_mass_kg,
            bike_id=bike.id,
        )
        speed = physics.steady_speed_ms(250.0, 0.0, ridden, air) * 3.6
        here = " <-" if bike.id == settings.virtual_bike_id else ""
        lines.append(
            f"  {bike.id:16} {bike.name:36} CdA {bike.cda_m2:.3f}"
            f"  {speed:5.1f} km/h{here}"
        )
    return Answer.say(*lines)


def choose_bike(bike_id: str) -> Answer:
    """Pick the bicycle to ride in the world."""
    known = [bike.id for bike in physics.BIKES]
    if bike_id not in known:
        return Answer.refuse(
            f"{bike_id!r} is not one of the bicycles here.",
            "--bikes lists them.",
        )
    settings = Settings.load()
    settings.virtual_bike_id = bike_id
    settings.save()
    chosen = physics.virtual_bike(bike_id)
    return Answer.say(f"riding a {chosen.name.lower()} (CdA {chosen.cda_m2:.3f} m2)")


def choose_rider(rider_kg: float, bike_kg: float | None = None) -> Answer:
    """Say what the rider and their bicycle weigh.

    Weight is the one number a power model cannot guess at and cannot do
    without: it decides every climb, every acceleration and part of the
    rolling resistance.
    """
    if not 30.0 <= rider_kg <= 250.0:
        return Answer.refuse(f"{rider_kg:.0f} kg is not a weight a rider is.")
    if bike_kg is not None and not 3.0 <= bike_kg <= 40.0:
        return Answer.refuse(f"{bike_kg:.0f} kg is not a weight a bicycle is.")
    settings = Settings.load()
    settings.rider_mass_kg = rider_kg
    if bike_kg is not None:
        settings.bike_mass_kg = bike_kg
    settings.save()
    return Answer.say(
        f"{settings.rider_mass_kg:.0f} kg rider on a "
        f"{settings.bike_mass_kg:.0f} kg bicycle "
        f"({settings.rider_mass_kg + settings.bike_mass_kg:.0f} kg all in)"
    )


def choose_cda(cda_m2: float | None) -> Answer:
    """Use a drag figure the rider measured, instead of the catalogue's."""
    if cda_m2 is not None and not 0.1 <= cda_m2 <= 0.8:
        return Answer.refuse(f"{cda_m2} m2 is not a frontal area a rider has.")
    settings = Settings.load()
    settings.measured_cda_m2 = cda_m2
    settings.save()
    if cda_m2 is None:
        return Answer.say("using the figure for the bicycle you chose")
    return Answer.say(f"using your measured CdA of {cda_m2:.3f} m2")


def choose_wheel(size_id: str, width_id: str) -> Answer:
    """Set the wheel from the catalogue, and say what it rolls."""
    try:
        rollout = wheels.catalogue().size(size_id).rollout_mm(width_id)
    except UnknownWheelError as error:
        return Answer.refuse(str(error), "--wheels lists the sizes and widths")
    settings = Settings.load()
    settings.wheel_size_id = wheels.catalogue().size(size_id).id
    settings.wheel_width_id = width_id
    # A measured value was chosen deliberately once; choosing from the catalogue
    # now is choosing again, and the old measurement is not about this wheel.
    settings.measured_rollout_mm = None
    settings.save()
    return Answer.say(
        f"{settings.wheel_size_id} x {width_id}, rolling {rollout:.0f} mm",
        "measure your own rollout with --rollout MM if you want the last percent",
    )


def choose_rollout(millimetres: float) -> Answer:
    """Set a measured rollout, which beats anything the catalogue says."""
    try:
        Wheel(measured_rollout_mm=millimetres)
    except ValueError as error:
        return Answer.refuse(str(error))
    settings = Settings.load()
    settings.measured_rollout_mm = millimetres
    settings.save()
    return Answer.say(f"measured rollout {millimetres:.0f} mm")


def choose_trainer(trainer_id: str) -> Answer:
    """Set the trainer, and say what it will mean for the rider's watts."""
    try:
        trainer = catalog.catalogue().get(trainer_id)
    except catalog.UnknownTrainerError as error:
        return Answer.refuse(str(error), "--trainers lists what there is")
    settings = Settings.load()
    settings.trainer_id = trainer.id
    settings.save()
    return Answer.say(trainer.name, *_what_it_means(trainer, settings))


def _what_it_means(trainer: catalog.Trainer, settings: Settings) -> list[str]:
    if trainer.reports_own_power:
        return ["it measures its own power, so nothing here is estimated"]
    wheel = settings.wheel
    if wheel is None:
        return ["set a wheel with --wheel, or its watts cannot be worked out"]
    estimator = PowerEstimator(wheel=wheel, trainer=trainer)
    estimate = estimator.from_speed(30 / 3.6)
    if estimate is None:  # pragma: no cover - reports_own_power covers this
        return []
    quality = "measured for this model" if estimate.calibrated else "an estimate"
    return [
        f"at 30 km/h it will read about {estimate.watts:.0f} W ({quality})",
        ""
        if estimate.calibrated
        else "ride with --capture-trainer to measure yours properly",
    ]


def choose_control(mode: str) -> Answer:
    """Set how a smart trainer is driven."""
    try:
        chosen = ControlMode(mode)
    except ValueError:
        allowed = ", ".join(item.value for item in ControlMode)
        return Answer.refuse(f"{mode!r} is not a control mode; try {allowed}")
    settings = Settings.load()
    settings.control_mode = chosen.value
    settings.save()
    explanations = {
        ControlMode.OFF: "the trainer keeps whatever resistance it has",
        ControlMode.ERG: "the trainer holds the workout's target power",
        ControlMode.SIMULATION: "the trainer follows the slope of the course",
    }
    return Answer.say(f"{chosen.value}: {explanations[chosen]}")


def describe_setup() -> Answer:
    """What the rider has told the app about their bike."""
    settings = Settings.load()
    wheel, trainer = settings.wheel, settings.trainer
    ridden = settings.bike
    lines = [
        f"language     {settings.effective_language}",
        f"rider        {settings.rider_mass_kg:.0f} kg on a "
        f"{settings.bike_mass_kg:.0f} kg bicycle",
        f"bike         {physics.virtual_bike(settings.virtual_bike_id).name}"
        f", CdA {ridden.cda_m2:.3f} m2"
        f"{' (measured)' if settings.measured_cda_m2 is not None else ''}",
        f"trainer      {trainer.name if trainer else 'not set'}",
        f"wheel        {_describe_wheel(wheel)}",
        f"control      {settings.trainer_control.value}",
        f"devices      {', '.join(settings.paired_device_ids) or 'none paired'}",
    ]
    return Answer.say(*lines)


def _describe_wheel(wheel: Wheel | None) -> str:
    if wheel is None:
        return "not set"
    if wheel.is_measured:
        return f"measured, rolling {wheel.rollout_mm:.0f} mm"
    return f"{wheel.size_id} x {wheel.width_id}, rolling {wheel.rollout_mm:.0f} mm"
