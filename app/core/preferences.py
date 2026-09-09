"""The settings screen, with no screen in it.

Choosing a wheel and a trainer from a window is picking from lists and saving the
result - and none of that needs a window to be decided or to be tested. So the
menu lives here as a small state machine over the catalogues, and the renderer
draws its lines and passes it key presses.

It exists because a rider should be able to set their bike up in the application
they actually use, without a terminal. The command line does the same job and
keeps doing it; this is the same choices, in the place where they are made.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.control import ControlMode
from app.settings import Settings
from app.trainer import catalog, wheels

#: What a row is choosing between, and what to call it.
WHEEL_SIZE = "Wheel"
TYRE_WIDTH = "Tyre"
TRAINER = "Trainer"
CONTROL = "Trainer control"


@dataclass(frozen=True)
class Choice:
    """One option in a row: what is stored, and what the rider reads."""

    value: str
    label: str


@dataclass
class Row:
    """One line of the menu, and where it currently points."""

    name: str
    choices: tuple[Choice, ...]
    index: int = 0

    @property
    def chosen(self) -> Choice | None:
        return self.choices[self.index] if self.choices else None

    def move(self, by: int) -> None:
        """Step through the options, wrapping - a list is a ring in a menu."""
        if self.choices:
            self.index = (self.index + by) % len(self.choices)

    def point_at(self, value: str) -> None:
        for index, choice in enumerate(self.choices):
            if choice.value == value:
                self.index = index
                return


@dataclass
class SetupMenu:
    """Choosing a bike, as rows to move through rather than commands to type."""

    settings: Settings = field(default_factory=Settings.load)
    rows: list[Row] = field(default_factory=list)
    selected: int = 0
    #: The width the rider last asked for, which may not be on the current rim.
    #: Scrolling through rims to find one is not a decision about tyres, so a
    #: rim passed over on the way must not quietly throw the tyre choice away.
    wanted_width: str = ""

    def __post_init__(self) -> None:
        if not self.rows:
            self.rows = self._build()
        if not self.wanted_width:
            chosen = self.row(TYRE_WIDTH).chosen
            self.wanted_width = chosen.value if chosen else ""

    def row(self, name: str) -> Row:
        """The row by what it chooses, rather than by where it happens to sit."""
        return next(row for row in self.rows if row.name == name)

    def _build(self) -> list[Row]:
        catalogue = wheels.catalogue()
        sizes = Row(
            WHEEL_SIZE,
            tuple(
                Choice(size.id, f"{size.id} (ISO {size.bead_seat_mm})")
                for size in catalogue.sizes
            ),
        )
        sizes.point_at(self.settings.wheel_size_id or "700c")
        widths = Row(TYRE_WIDTH, self._widths(sizes))
        widths.point_at(self.settings.wheel_width_id or "25")
        trainers = Row(
            TRAINER,
            tuple(Choice(trainer.id, trainer.name) for trainer in catalog.catalogue()),
        )
        trainers.point_at(self.settings.trainer_id)
        control = Row(
            CONTROL,
            tuple(Choice(mode.value, mode.value) for mode in ControlMode),
        )
        control.point_at(self.settings.trainer_control.value)
        return [sizes, widths, trainers, control]

    @staticmethod
    def _widths(size_row: Row) -> tuple[Choice, ...]:
        chosen = size_row.chosen
        if chosen is None:  # pragma: no cover - the catalogue is never empty
            return ()
        size = wheels.catalogue().size(chosen.value)
        return tuple(Choice(width.id, width.id) for width in size.widths)

    # Moving about.

    def move(self, by: int) -> None:
        """Up and down the rows."""
        self.selected = (self.selected + by) % len(self.rows)

    def change(self, by: int) -> None:
        """Left and right through a row's options."""
        row = self.rows[self.selected]
        row.move(by)
        if row.name == TYRE_WIDTH:
            chosen = row.chosen
            self.wanted_width = chosen.value if chosen else self.wanted_width
        if row.name == WHEEL_SIZE:
            # A tyre width belongs to a rim: 2.1in is not a 650c size, and 20 mm
            # is not a mountain bike one. Changing the rim rebuilds the list and
            # offers the width the rider asked for wherever a rim takes it, so
            # that walking from 700c to 26in past two rims that have no 35 mm
            # still arrives on 35 mm.
            widths = self.row(TYRE_WIDTH)
            widths.choices = self._widths(row)
            widths.index = 0
            widths.point_at(self.wanted_width)

    # What it says, and what it does.

    def lines(self) -> list[str]:
        """The menu as a screen draws it, with a marker on the current row."""
        drawn = []
        for index, row in enumerate(self.rows):
            marker = ">" if index == self.selected else " "
            chosen = row.chosen
            drawn.append(f"{marker} {row.name:16} {chosen.label if chosen else '-'}")
        return drawn

    @property
    def summary(self) -> str:
        """One line saying what this bike will mean, the way choosing does."""
        settings = self.as_settings()
        wheel, trainer = settings.wheel, settings.trainer
        if wheel is None or trainer is None:
            return "choose a wheel and a trainer"
        if trainer.reports_own_power:
            return f"{trainer.name} measures its own power"
        from app.trainer.estimate import PowerEstimator

        estimate = PowerEstimator(wheel=wheel, trainer=trainer).from_speed(30 / 3.6)
        if estimate is None:  # pragma: no cover - reports_own_power covers this
            return trainer.name
        measured = "measured" if estimate.calibrated else "estimated"
        return (
            f"{wheel.rollout_mm:.0f} mm rollout; "
            f"about {estimate.watts:.0f} W at 30 km/h ({measured})"
        )

    def as_settings(self) -> Settings:
        """The settings these choices describe, without saving them."""
        chosen = {row.name: row.chosen for row in self.rows}
        settings = Settings.load()
        settings.wheel_size_id = _value(chosen.get(WHEEL_SIZE))
        settings.wheel_width_id = _value(chosen.get(TYRE_WIDTH))
        settings.trainer_id = _value(chosen.get(TRAINER))
        settings.control_mode = _value(chosen.get(CONTROL)) or settings.control_mode
        # Choosing from the catalogue is choosing again: a rollout measured for a
        # different wheel would otherwise be applied to this one.
        settings.measured_rollout_mm = None
        return settings

    def save(self) -> Settings:
        settings = self.as_settings()
        settings.save()
        self.settings = settings
        return settings


def _value(choice: Choice | None) -> str:
    return choice.value if choice else ""
