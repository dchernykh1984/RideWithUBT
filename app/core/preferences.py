"""The settings screen, with no screen in it.

Everything a rider has to decide before they ride - what they weigh, what
they are riding, which wheel is on the trainer, which sensors to listen to,
whether anybody is pedalling at all - lives here as a list of rows. The
renderer draws the rows and passes key presses back; it decides nothing.

That split is the project's one structural rule applied to a menu, and it is
why a settings screen has tests. It is also why the same choices work from the
command line: both are views onto the same catalogues and the same file.

The rows are deliberately dumb. A row knows its own name, what it is choosing
between, and how to step through that. Anything that needs to reach the world -
scanning a radio for sensors - is handed in as something to call, so this module
never opens anything.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from app import i18n
from app.core import physics
from app.core.control import ControlMode
from app.core.rows import (
    ActionRow,
    Choice,
    ChoiceRow,
    DeviceRow,
    Found,
    Heading,
    NumberRow,
    Panel,
    Row,
    ToggleRow,
)
from app.settings import Settings
from app.trainer import catalog, wheels

#: What each row is deciding. Named rather than numbered, because rows move
#: about as the menu grows and code that says `rows[1]` stops being true.
RIDER_KG = "Your weight"
BIKE_KG = "Bike weight"
VIRTUAL_BIKE = "Riding"
WHEEL_SIZE = "Wheel"
TYRE_WIDTH = "Tyre"
TRAINER = "Trainer"
CONTROL = "Trainer control"
CAPTURE = "Record trainer data"
SIMULATE = "Stand-in rider"
LANGUAGE = "Language"
SCAN = "Scan for sensors"

#: How long a scan listens for. Long enough for a sleepy sensor to wake up and
#: answer, short enough that a rider does not think it has hung.
SCAN_SECONDS = 6.0


@dataclass
class SetupMenu(Panel):
    """Everything a rider decides before riding, as rows to move through.

    `scanner` is how the menu reaches a radio. Handed in rather than reached
    for, so the menu can be tested with no Bluetooth in the room - which is
    every machine the tests run on.
    """

    settings: Settings = field(default_factory=Settings.load)
    scanner: Callable[[float], Sequence[Found]] | None = None
    rows: list[Row] = field(default_factory=list)
    selected: int = 0
    found: list[Found] = field(default_factory=list)
    paired: set[str] = field(default_factory=set)
    #: What the last action had to say for itself. Scanning takes seconds and
    #: finds nothing surprisingly often, and a screen that says neither is a
    #: screen a rider presses again.
    note: str = ""
    #: The width the rider last asked for, which may not be on the current rim.
    #: Scrolling through rims to find one is not a decision about tyres, so a
    #: rim passed over on the way must not quietly throw the tyre choice away.
    wanted_width: str = ""

    def __post_init__(self) -> None:
        self.paired = set(self.settings.paired_device_ids)
        if not self.rows:
            self.rows = self._build()
        if not self.wanted_width:
            self.wanted_width = self.choice(TYRE_WIDTH).value
        if not self.rows[self.selected].selectable:
            self.move(1)

    # Building it.

    def _build(self) -> list[Row]:
        catalogue = wheels.catalogue()
        sizes = ChoiceRow(
            WHEEL_SIZE,
            tuple(
                Choice(size.id, f"{size.id} (ISO {size.bead_seat_mm})")
                for size in catalogue.sizes
            ),
        )
        sizes.point_at(self.settings.wheel_size_id or "700c")
        widths = ChoiceRow(TYRE_WIDTH, self._widths(sizes))
        widths.point_at(self.settings.wheel_width_id or "25")
        # "Not chosen" is first and is where a fresh install sits. Without it
        # the row would point at whatever happens to come first in the
        # catalogue, and closing the menu would save a trainer the rider never
        # picked.
        trainers = ChoiceRow(
            TRAINER,
            (
                Choice("", "not chosen"),
                *(Choice(trainer.id, trainer.name) for trainer in catalog.catalogue()),
            ),
        )
        trainers.point_at(self.settings.trainer_id)
        control = ChoiceRow(
            CONTROL, tuple(Choice(mode.value, mode.value) for mode in ControlMode)
        )
        control.point_at(self.settings.trainer_control.value)
        bikes = ChoiceRow(
            VIRTUAL_BIKE,
            tuple(Choice(bike.id, bike.name) for bike in physics.BIKES),
        )
        bikes.point_at(self.settings.virtual_bike_id)
        languages = ChoiceRow(
            LANGUAGE,
            tuple(Choice(tag, i18n.locale_name(tag)) for tag in i18n.LOCALES),
        )
        languages.point_at(self.settings.effective_language)
        return [
            Heading("Rider"),
            NumberRow(RIDER_KG, self.settings.rider_mass_kg, 0.5, 30.0, 200.0, " kg"),
            NumberRow(BIKE_KG, self.settings.bike_mass_kg, 0.1, 3.0, 30.0, " kg", 1),
            bikes,
            Heading("Trainer and wheel"),
            sizes,
            widths,
            trainers,
            control,
            ToggleRow(CAPTURE, self.settings.record_trainer_data),
            Heading("Sensors"),
            *self._device_rows(),
            ActionRow(SCAN, self.scan, lambda: self.note),
            Heading("Application"),
            languages,
        ]

    def _device_rows(self) -> list[Row]:
        """One row per sensor: the ones already paired, then anything found.

        A rider who paired a sensor last week must be able to see and drop it
        without the radio being awake, so the saved list is shown whether or not
        anything answered this time.
        """
        seen = {device.id: device for device in self.found}
        for device_id in sorted(self.paired):
            seen.setdefault(device_id, Found(device_id, device_id))
        return [
            DeviceRow(f"  {device.label}"[:40], device.id, self.paired)
            for device in sorted(seen.values(), key=lambda device: device.id)
        ]

    @staticmethod
    def _widths(size_row: ChoiceRow) -> tuple[Choice, ...]:
        chosen = size_row.chosen
        if chosen is None:  # pragma: no cover - the catalogue is never empty
            return ()
        size = wheels.catalogue().size(chosen.value)
        return tuple(Choice(width.id, width.id) for width in size.widths)

    def changed(self, row: Row) -> None:
        """A tyre width belongs to a rim: 2.1in is not a 650c size, and 20 mm
        is not a mountain bike one. Changing the rim rebuilds the width list
        and offers the width the rider asked for wherever a rim takes it, so
        that walking from 700c to 26in past two rims with no 35 mm still
        arrives on 35 mm."""
        if isinstance(row, ChoiceRow) and row.name == TYRE_WIDTH:
            self.wanted_width = row.value
        if isinstance(row, ChoiceRow) and row.name == WHEEL_SIZE:
            widths = self.choice(TYRE_WIDTH)
            widths.choices = self._widths(row)
            widths.index = 0
            widths.point_at(self.wanted_width)

    # Doing things that reach outside.

    def scan(self, seconds: float = SCAN_SECONDS) -> None:
        """Ask the radios who is there, and offer whatever answers."""
        if self.scanner is None:
            self.note = "no radios in this build"
            return
        self.found = list(self.scanner(seconds))
        self.note = (
            f"found {len(self.found)}"
            if self.found
            else "nothing answered - are they awake?"
        )
        self._rebuild_devices()

    def _rebuild_devices(self) -> None:
        """Put the device rows back, keeping the rider where they were."""
        here = self.rows[self.selected]
        first = next(
            index
            for index, row in enumerate(self.rows)
            if isinstance(row, Heading) and row.name == "Sensors"
        )
        last = next(index for index, row in enumerate(self.rows) if row.name == SCAN)
        self.rows[first + 1 : last] = self._device_rows()
        try:
            self.selected = self.rows.index(here)
        except ValueError:  # pragma: no cover - the scan row is always there
            self.selected = first + 1

    # What it says, and what it keeps.

    def lines(self) -> list[str]:
        """The panel as one padded string a row, for anything without columns."""
        return [f"{name:26}{reading}" for name, reading in self.columns()]

    @property
    def summary(self) -> str:
        """One line saying what these choices are worth, as choosing does."""
        settings = self.as_settings()
        bike = settings.bike
        speed = physics.steady_speed_ms(250.0, 0.0, bike) * 3.6
        line = f"{bike.total_mass_kg:.0f} kg all in; {speed:.1f} km/h at 250 W"
        wheel, trainer = settings.wheel, settings.trainer
        if wheel is None or trainer is None:
            return f"{line}; choose a wheel and a trainer for virtual power"
        if trainer.reports_own_power:
            return f"{line}; {trainer.name} measures its own power"
        from app.trainer.estimate import PowerEstimator

        estimate = PowerEstimator(wheel=wheel, trainer=trainer).from_speed(30 / 3.6)
        if estimate is None:  # pragma: no cover - reports_own_power covers this
            return line
        measured = "measured" if estimate.calibrated else "estimated"
        return (
            f"{line}; {wheel.rollout_mm:.0f} mm rollout, "
            f"about {estimate.watts:.0f} W at 30 km/h ({measured})"
        )

    def as_settings(self) -> Settings:
        """The settings these choices describe, without saving them."""
        settings = Settings.load()
        settings.wheel_size_id = self.choice(WHEEL_SIZE).value
        settings.wheel_width_id = self.choice(TYRE_WIDTH).value
        settings.trainer_id = self.choice(TRAINER).value
        settings.control_mode = self.choice(CONTROL).value or settings.control_mode
        settings.virtual_bike_id = self.choice(VIRTUAL_BIKE).value
        settings.language = self.choice(LANGUAGE).value
        settings.rider_mass_kg = self.number(RIDER_KG).value
        settings.bike_mass_kg = self.number(BIKE_KG).value
        capture = self.row(CAPTURE)
        settings.record_trainer_data = isinstance(capture, ToggleRow) and capture.on
        settings.paired_device_ids = sorted(self.paired)
        # Choosing from the catalogue is choosing again: a rollout measured for a
        # different wheel would otherwise be applied to this one.
        settings.measured_rollout_mm = None
        return settings

    def save(self) -> Settings:
        settings = self.as_settings()
        settings.save()
        self.settings = settings
        return settings
