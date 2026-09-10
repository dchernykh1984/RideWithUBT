"""The rows a menu is made of, and where a mouse lands on them.

Shared by the front screen and the settings, because they are the same thing
seen twice: a list of lines, one of them marked, changed with the arrows or
with a mouse. What each list is *about* differs; how it behaves does not.

Nothing here draws. Working out which row a click landed on is arithmetic - a
top, a line height, a count - and arithmetic that decides what a click does is
exactly the sort of thing that should not live in the one module without tests.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Choice:
    """One option in a row: what is stored, and what the rider reads."""

    value: str
    label: str


@dataclass(frozen=True)
class Found:
    """A sensor a radio answered with. Only what the menu needs to show it."""

    id: str
    label: str


class Row:
    """One line of the menu."""

    name: str

    @property
    def reading(self) -> str:  # pragma: no cover - every row overrides this
        raise NotImplementedError

    def change(self, by: int) -> None:
        """Left and right. A row that does not adjust ignores it."""

    def activate(self) -> None:
        """Enter. A row that does nothing on Enter ignores it."""

    @property
    def selectable(self) -> bool:
        return True


@dataclass
class Heading(Row):
    """A label between groups of rows. Not somewhere the marker can rest."""

    name: str

    @property
    def reading(self) -> str:
        return ""

    @property
    def selectable(self) -> bool:
        return False


@dataclass
class ChoiceRow(Row):
    """A row that steps through a list."""

    name: str
    choices: tuple[Choice, ...]
    index: int = 0

    @property
    def chosen(self) -> Choice | None:
        return self.choices[self.index] if self.choices else None

    @property
    def value(self) -> str:
        chosen = self.chosen
        return chosen.value if chosen else ""

    @property
    def reading(self) -> str:
        chosen = self.chosen
        return chosen.label if chosen else "-"

    def change(self, by: int) -> None:
        """Step through the options, wrapping - a list is a ring in a menu."""
        if self.choices:
            self.index = (self.index + by) % len(self.choices)

    def point_at(self, value: str) -> None:
        for index, choice in enumerate(self.choices):
            if choice.value == value:
                self.index = index
                return


@dataclass
class NumberRow(Row):
    """A row that counts up and down: a weight, a power, a drag figure."""

    name: str
    value: float
    step: float
    low: float
    high: float
    unit: str = ""
    decimals: int = 0
    #: What to show instead of a number at the bottom of the range. A weight has
    #: no such thing; a stand-in rider at zero watts is "off", which is the
    #: whole point of the row.
    off_label: str = ""

    @property
    def is_off(self) -> bool:
        return bool(self.off_label) and self.value <= self.low

    @property
    def reading(self) -> str:
        if self.is_off:
            return self.off_label
        return f"{self.value:.{self.decimals}f}{self.unit}"

    def change(self, by: int) -> None:
        stepped = self.value + by * self.step
        self.value = min(max(stepped, self.low), self.high)


@dataclass
class ToggleRow(Row):
    """A row that is either on or off."""

    name: str
    on: bool = False
    on_label: str = "yes"
    off_label: str = "no"

    @property
    def reading(self) -> str:
        return self.on_label if self.on else self.off_label

    def change(self, by: int) -> None:
        self.on = not self.on

    def activate(self) -> None:
        self.on = not self.on


@dataclass
class ActionRow(Row):
    """A row that does something when the rider presses Enter."""

    name: str
    do: Callable[[], None]
    reading_of: Callable[[], str] = lambda: ""

    @property
    def reading(self) -> str:
        return self.reading_of()

    def activate(self) -> None:
        self.do()


@dataclass
class DeviceRow(Row):
    """One sensor, and whether the rider is listening to it."""

    name: str
    device_id: str
    paired: set[str]

    @property
    def reading(self) -> str:
        return "paired" if self.device_id in self.paired else "not paired"

    def change(self, by: int) -> None:
        self.activate()

    def activate(self) -> None:
        if self.device_id in self.paired:
            self.paired.discard(self.device_id)
        else:
            self.paired.add(self.device_id)


@dataclass(frozen=True)
class Layout:
    """Where the lines of a menu are drawn, so a click can be placed on one.

    In the renderer's own coordinates: `top` is where the first line sits and
    `line_height` is how far apart they are, both measured downwards.
    """

    top: float
    line_height: float
    #: Lines drawn above the rows - a title and a blank, usually - which a
    #: click can land on and which are not rows.
    header: int = 0

    def row_at(self, y: float, count: int) -> int | None:
        """Which row is at this height, or None if the pointer is off the list."""
        if self.line_height <= 0.0:  # pragma: no cover - a drawn line has height
            return None
        index = int((self.top - y) / self.line_height) - self.header
        return index if 0 <= index < count else None
