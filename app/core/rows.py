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

    @property
    def range_says(self) -> str:
        """What a field will take, for a box that is asking for a number."""
        return f"{self.low:.{self.decimals}f} - {self.high:.{self.decimals}f}"

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


@dataclass
class Typing:
    """A number being typed into a row.

    Stepping a weight to 83 kg with an arrow key is eighty-three key presses.
    A field you click and type into is one - which is what a number field is
    for, and what this is.
    """

    row: NumberRow
    text: str = ""

    def key(self, character: str) -> None:
        """Take one keystroke. Digits and a single decimal point, nothing else."""
        if character.isdigit():
            self.text += character
        elif character in ".," and "." not in self.text:
            self.text += "."
        if len(self.text) > MAX_TYPED:
            self.text = self.text[:MAX_TYPED]

    def backspace(self) -> None:
        self.text = self.text[:-1]

    @property
    def reading(self) -> str:
        """What the field shows while it is being typed into."""
        return f"{self.text}_"

    def commit(self) -> bool:
        """Put what was typed into the row. False if it was not a number.

        Out of range is not refused, it is pulled back into range: somebody
        typing 300 for their weight meant 300, and the row knows what a weight
        can be.
        """
        try:
            wanted = float(self.text)
        except ValueError:
            return False
        self.row.value = min(max(wanted, self.row.low), self.row.high)
        return True


#: How many options a box shows at once. Twelve fits on the shortest window
#: anybody rides on; the list of trainers is three times that.
WINDOW = 12


@dataclass
class Picking:
    """A list opened on a row, to choose from rather than to cycle through.

    A row that steps through forty trainers one arrow press at a time is a row
    nobody reaches the end of. Opening the list shows them all and puts the
    marker on the one already chosen.
    """

    row: ChoiceRow
    index: int = 0

    def move(self, by: int) -> None:
        if self.row.choices:
            self.index = (self.index + by) % len(self.row.choices)

    def point_at(self, index: int) -> bool:
        if 0 <= index < len(self.row.choices):
            self.index = index
            return True
        return False

    def choose(self) -> None:
        self.row.index = self.index

    @property
    def first(self) -> int:
        """Which option the box shows at the top.

        The window follows the marker instead of paging, so arrowing down a
        list of thirty-nine trainers scrolls it rather than jumping it.
        """
        count = len(self.row.choices)
        if count <= WINDOW:
            return 0
        return min(max(self.index - WINDOW // 2, 0), count - WINDOW)

    def lines(self) -> list[tuple[str, str]]:
        """The list as a panel draws it, with a marker on where it is now.

        Only as much of it as fits: thirty-nine trainers are taller than the
        screen, and a box whose last lines are off the bottom of it is a box
        a rider cannot finish reading.
        """
        first = self.first
        shown = list(enumerate(self.row.choices))[first : first + WINDOW]
        return [
            (
                f"{'> ' if index == self.index else '  '}{choice.label}",
                "in use" if index == self.row.index else "",
            )
            for index, choice in shown
        ]

    @property
    def place(self) -> str:
        """Where in the list the marker is, for a box that shows part of one."""
        return f"{self.index + 1} / {len(self.row.choices)}"


#: Nobody types a weight longer than this, and a field that accepts a hundred
#: digits is a field that has stopped being a number.
MAX_TYPED = 7


class Panel:
    """A list of rows a person works with: the front screen, or the settings.

    Both are the same thing with different rows in them, and both are worked
    the same way - arrows or a mouse to move, a click or Enter to open a field,
    and either a list to pick from or a number to type.
    """

    rows: list[Row]
    selected: int
    typing: Typing | None = None
    picking: Picking | None = None
    #: How to say a thing in the rider's language. A panel builds sentences out
    #: of numbers it works out itself - "found 3", "about 130 W at 30 km/h" -
    #: and those cannot be translated by whoever draws them, because by then
    #: they are one string with a number baked into it. Identity by default, so
    #: nothing that does not care has to know about it.
    speaks: Callable[[str], str] = str

    # Reaching for a row.

    def row(self, name: str) -> Row:
        """The row by what it decides, rather than by where it happens to sit.

        Headings are skipped: a section and a row inside it can be about the
        same thing and share a word, and asking for "Trainer" means the row.
        """
        return next(
            row
            for row in self.rows
            if row.name == name and not isinstance(row, Heading)
        )

    def choice(self, name: str) -> ChoiceRow:
        row = self.row(name)
        if not isinstance(row, ChoiceRow):  # pragma: no cover - names are fixed
            raise TypeError(f"{name} is not a row that chooses from a list")
        return row

    def number(self, name: str) -> NumberRow:
        row = self.row(name)
        if not isinstance(row, NumberRow):  # pragma: no cover - names are fixed
            raise TypeError(f"{name} is not a row that counts")
        return row

    @property
    def busy(self) -> bool:
        """Whether a field is open, and the keys belong to it rather than the list."""
        return self.typing is not None or self.picking is not None

    # Moving about.

    def move(self, by: int) -> None:
        """Up and down: the open list if there is one, the rows if not."""
        if self.picking is not None:
            self.picking.move(by)
            return
        step = 1 if by >= 0 else -1
        for _ in range(len(self.rows)):
            self.selected = (self.selected + step) % len(self.rows)
            if self.rows[self.selected].selectable:
                return

    def point_at(self, index: int) -> bool:
        """Put the marker on a row, for a mouse moving over it.

        While a list is open the lines are the list's, and only the ones the
        box is showing: what comes in is a line of the box rather than a place
        in a list of thirty-nine trainers.
        """
        if self.picking is not None:
            return self.picking.point_at(self.picking.first + index)
        if 0 <= index < len(self.rows) and self.rows[index].selectable:
            self.selected = index
            return True
        return False

    def change(self, by: int) -> None:
        """Left and right, which still step a row without opening it."""
        if self.picking is not None:
            self.picking.move(by)
            return
        if self.typing is not None:
            return
        self.rows[self.selected].change(by)
        self.changed(self.rows[self.selected])

    def changed(self, row: Row) -> None:
        """What to do after a row changes. Panels that care override this."""

    # Opening and closing a field.

    def activate(self) -> None:
        """Enter, or a click: open the field, or take what is in the open one."""
        if self.picking is not None:
            self.picking.choose()
            chosen = self.picking.row
            self.picking = None
            self.changed(chosen)
            return
        if self.typing is not None:
            self.commit()
            return
        here = self.rows[self.selected]
        if isinstance(here, ChoiceRow) and len(here.choices) > 1:
            self.picking = Picking(here, here.index)
            return
        if isinstance(here, NumberRow):
            self.typing = Typing(here)
            return
        here.activate()
        self.changed(here)

    def key(self, character: str) -> None:
        if self.typing is not None:
            self.typing.key(character)

    def backspace(self) -> None:
        if self.typing is not None:
            self.typing.backspace()

    def commit(self) -> None:
        """Take what was typed, if it was a number, and close the field."""
        if self.typing is None:  # pragma: no cover - callers check first
            return
        row = self.typing.row
        self.typing.commit()
        self.typing = None
        self.changed(row)

    def cancel(self) -> None:
        """Escape: close the field and keep what was there before."""
        self.typing = None
        self.picking = None

    # What it says.

    def columns(self) -> list[tuple[str, str]]:
        """The panel as two columns. Always the rows: an open field is a box
        over the top of them, not a screen that replaces them."""
        drawn = []
        for index, row in enumerate(self.rows):
            if isinstance(row, Heading):
                # Left as it is written, not shouted here: a renderer that
                # translates a label first cannot uppercase it beforehand.
                drawn.append((row.name, ""))
                continue
            marker = "> " if index == self.selected else "  "
            drawn.append((f"{marker}{row.name}", row.reading))
        return drawn

    @property
    def open_row(self) -> Row | None:
        """The row whose field is open, if one is."""
        if self.picking is not None:
            return self.picking.row
        return self.typing.row if self.typing is not None else None

    def popup(self) -> list[tuple[str, str]]:
        """What is in the box over the panel: a list, or a number being typed.

        A box rather than a screen of its own, so a rider can still see what
        they are changing and what the rest of it is set to.
        """
        if self.picking is not None:
            return self.picking.lines()
        if self.typing is not None:
            row = self.typing.row
            # The range beside what is being typed, because a field that
            # silently pulls 300 back to 200 looks broken from the outside.
            return [(f"{self.typing.reading}{row.unit}", row.range_says)]
        return []


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
