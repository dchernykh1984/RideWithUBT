"""What the application opens on.

It used to drop the rider straight onto the track with a stand-in pedalling.
That is the wrong first thing to see: before riding, somebody picks a circuit,
maybe a workout, and presses go. Those are the choices made every session, so
they are the ones on the front screen - and the ones made once, the trainer and
the sensors and the wheel, are behind Settings where they belong.

Like the settings, this is a list of rows and no window. What a menu *is* about
differs between the two; how it behaves does not, so both are built from
`app/core/rows.py`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from app.core.rows import ActionRow, Choice, ChoiceRow, Heading, Row
from app.settings import Settings
from app.workout.model import Workout
from app.world.description import available_worlds
from app.world.description import load as load_world

#: What each row decides.
WORLD = "Track"
ROUTE = "Route"
WORKOUT = "Workout"
RIDE = "Ride"
SETTINGS = "Settings"
QUIT = "Quit"

#: The workout row when there is none: a free ride, which is most rides.
NO_WORKOUT = ""


@dataclass
class StartScreen:
    """The front screen: what to ride, and go.

    `workouts` is handed in rather than read here, because a rider's workout
    library is a directory on their machine and this has to be testable without
    one.
    """

    settings: Settings = field(default_factory=Settings.load)
    workouts: Sequence[Workout] = ()
    worlds: Sequence[str] = ()
    on_ride: Callable[[], None] = lambda: None
    on_settings: Callable[[], None] = lambda: None
    on_quit: Callable[[], None] = lambda: None
    rows: list[Row] = field(default_factory=list)
    selected: int = 0

    def __post_init__(self) -> None:
        if not self.worlds:
            self.worlds = available_worlds()
        if not self.rows:
            self.rows = self._build()
        if not self.rows[self.selected].selectable:
            self.move(1)

    def _build(self) -> list[Row]:
        worlds = ChoiceRow(
            WORLD, tuple(Choice(world, _titled(world)) for world in self.worlds)
        )
        worlds.point_at(self.settings.world_id or "")
        routes = ChoiceRow(ROUTE, self._routes(worlds.value))
        routes.point_at(self.settings.route_id)
        workouts = ChoiceRow(
            WORKOUT,
            (
                Choice(NO_WORKOUT, "none - just ride"),
                *(Choice(workout.name, workout.name) for workout in self.workouts),
            ),
        )
        workouts.point_at(self.settings.workout_name)
        return [
            # Not "Ride": the row below it is called that, and a heading that
            # shares a name with a row is a row you cannot look up by name.
            Heading("This ride"),
            ActionRow(RIDE, self.on_ride, lambda: "start"),
            worlds,
            routes,
            workouts,
            Heading("Application"),
            ActionRow(SETTINGS, self.on_settings, lambda: "trainer, sensors, bike"),
            ActionRow(QUIT, self.on_quit),
        ]

    @staticmethod
    def _routes(world_id: str) -> tuple[Choice, ...]:
        """The ways round a circuit, as that circuit names them."""
        if not world_id:  # pragma: no cover - a build always ships a world
            return ()
        network = load_world(world_id)
        return tuple(Choice(route.id, route.name) for route in network.routes)

    # Reaching for it.

    def row(self, name: str) -> Row:
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

    # Moving about.

    def move(self, by: int) -> None:
        step = 1 if by >= 0 else -1
        for _ in range(len(self.rows)):
            self.selected = (self.selected + step) % len(self.rows)
            if self.rows[self.selected].selectable:
                return

    def point_at(self, index: int) -> bool:
        """Put the marker on a row, for a mouse moving over it."""
        if 0 <= index < len(self.rows) and self.rows[index].selectable:
            self.selected = index
            return True
        return False

    def change(self, by: int) -> None:
        row = self.rows[self.selected]
        row.change(by)
        if isinstance(row, ChoiceRow) and row.name == WORLD:
            # Another circuit has its own ways round it; the names from the last
            # one mean nothing here.
            routes = self.choice(ROUTE)
            routes.choices = self._routes(row.value)
            routes.index = 0
        self.save()

    def activate(self) -> None:
        self.rows[self.selected].activate()

    # What it says, and what it keeps.

    def columns(self) -> list[tuple[str, str]]:
        drawn = []
        for index, row in enumerate(self.rows):
            if isinstance(row, Heading):
                drawn.append((row.name.upper(), ""))
                continue
            marker = "> " if index == self.selected else "  "
            drawn.append((f"{marker}{row.name}", row.reading))
        return drawn

    @property
    def chosen_workout(self) -> Workout | None:
        name = self.choice(WORKOUT).value
        return next(
            (workout for workout in self.workouts if workout.name == name), None
        )

    def save(self) -> Settings:
        """Keep what was picked, so the next session opens on it.

        Saved as it is changed rather than on the way out: unlike the settings,
        where stepping through a list of trainers is looking rather than
        choosing, every row here is a decision about the ride about to start.
        """
        settings = Settings.load()
        settings.world_id = self.choice(WORLD).value
        settings.route_id = self.choice(ROUTE).value
        settings.workout_name = self.choice(WORKOUT).value
        settings.save()
        self.settings = settings
        return settings


def _titled(world_id: str) -> str:
    """A world's id as a name, for a screen: `sokol` reads as Sokol."""
    try:
        return load_world(world_id).name
    except Exception:  # pragma: no cover - a shipped world always loads
        return world_id
