"""What the application opens on.

It used to drop the rider straight onto the track with a stand-in pedalling.
The choices made every session - which circuit, which way round, which workout
- belong on the front screen; the ones made once - the trainer, the sensors,
the wheel - belong behind Settings.
"""

from __future__ import annotations

import pytest

from app.core.rows import ActionRow, Heading, Layout
from app.core.startscreen import (
    NO_WORKOUT,
    QUIT,
    RIDE,
    ROUTE,
    SETTINGS,
    WORKOUT,
    WORLD,
    StartScreen,
)
from app.settings import Settings
from app.workout.model import Step, StepKind, Target, TargetKind, Workout


def workout(name: str) -> Workout:
    return Workout(
        name=name,
        steps=(
            Step(
                kind=StepKind.INTERVAL,
                name="Effort",
                duration=60.0,
                targets=(Target(TargetKind.POWER, 200.0, 200.0),),
            ),
        ),
    )


def screen(**kwargs: object) -> StartScreen:
    return StartScreen(**kwargs)  # type: ignore[arg-type]


def point_at(front: StartScreen, name: str) -> None:
    front.selected = next(
        index for index, row in enumerate(front.rows) if row.name == name
    )


# What is on it.


def test_the_choices_made_every_session_are_on_the_front_screen() -> None:
    names = {row.name for row in screen().rows}

    assert {RIDE, WORLD, ROUTE, WORKOUT, SETTINGS, QUIT} <= names


def test_the_choices_made_once_are_not() -> None:
    """A trainer is chosen once and a circuit every time; they do not belong
    on the same screen."""
    names = {row.name for row in screen().rows}

    assert "Trainer" not in names
    assert "Wheel" not in names
    assert "Your weight" not in names


def test_the_track_is_named_rather_than_slugged() -> None:
    """`sokol` is how a world is filed, not what it is called."""
    front = screen()

    assert front.choice(WORLD).reading == "Sokol International Racetrack"


def test_the_ways_round_are_the_ones_that_circuit_offers() -> None:
    front = screen()

    routes = {choice.value for choice in front.choice(ROUTE).choices}

    assert "big-ring" in routes
    assert "small-ring" in routes


def test_a_rider_with_no_workouts_can_still_just_ride() -> None:
    front = screen()

    assert front.choice(WORKOUT).value == NO_WORKOUT
    assert front.chosen_workout is None
    assert "just ride" in front.choice(WORKOUT).reading


def test_a_workout_can_be_picked_for_this_ride() -> None:
    front = screen(workouts=[workout("3x8 Intervals")])
    front.choice(WORKOUT).point_at("3x8 Intervals")

    chosen = front.chosen_workout

    assert chosen is not None
    assert chosen.name == "3x8 Intervals"


# What it remembers.


def test_it_opens_on_what_was_ridden_last_time() -> None:
    """A rider who rides the same circuit every week should not have to say so
    every week."""
    Settings(world_id="sokol", route_id="small-ring").save()

    front = screen()

    assert front.choice(ROUTE).value == "small-ring"


def test_a_choice_is_kept_as_it_is_made() -> None:
    """Unlike the settings, where stepping through a list of trainers is
    looking rather than choosing, every row here is a decision about the ride
    about to start."""
    front = screen()
    point_at(front, ROUTE)

    front.change(1)

    assert Settings.load().route_id == front.choice(ROUTE).value


def test_changing_the_circuit_offers_its_own_ways_round() -> None:
    front = screen(worlds=["sokol"])
    point_at(front, WORLD)

    front.change(1)

    assert front.choice(ROUTE).choices, "a circuit always has a way round it"


# Working it.


def test_the_marker_steps_over_the_headings() -> None:
    front = screen()

    for _ in range(len(front.rows) * 2):
        front.move(1)
        assert not isinstance(front.rows[front.selected], Heading)


def test_riding_is_a_row_you_press() -> None:
    pressed = []
    front = screen(on_ride=lambda: pressed.append("go"))
    point_at(front, RIDE)

    front.activate()

    assert pressed == ["go"]


def test_settings_and_quit_are_rows_you_press() -> None:
    pressed: list[str] = []
    front = screen(
        on_settings=lambda: pressed.append("settings"),
        on_quit=lambda: pressed.append("quit"),
    )

    for name in (SETTINGS, QUIT):
        point_at(front, name)
        front.activate()

    assert pressed == ["settings", "quit"]


def test_a_mouse_can_land_on_a_row() -> None:
    front = screen()
    row = next(index for index, item in enumerate(front.rows) if item.name == ROUTE)

    assert front.point_at(row)
    assert front.rows[front.selected].name == ROUTE


def test_a_mouse_on_a_heading_lands_nowhere() -> None:
    front = screen()
    heading = next(
        index for index, row in enumerate(front.rows) if isinstance(row, Heading)
    )
    before = front.selected

    assert not front.point_at(heading)
    assert front.selected == before


def test_a_mouse_off_the_list_lands_nowhere() -> None:
    front = screen()

    assert not front.point_at(-1)
    assert not front.point_at(len(front.rows))


# Where the mouse is.


def test_a_click_is_placed_on_the_row_it_landed_on() -> None:
    layout = Layout(top=0.8, line_height=0.1, header=2)

    assert layout.row_at(0.8 - 0.25, count=5) == 0
    assert layout.row_at(0.8 - 0.35, count=5) == 1


def test_a_click_above_or_below_the_list_is_on_no_row() -> None:
    layout = Layout(top=0.8, line_height=0.1, header=2)

    assert layout.row_at(0.9, count=5) is None
    assert layout.row_at(-0.9, count=5) is None


def test_the_header_is_not_a_row() -> None:
    """The title and the blank line under it can be clicked and are not rows."""
    layout = Layout(top=0.8, line_height=0.1, header=2)

    assert layout.row_at(0.75, count=5) is None
    assert layout.row_at(0.65, count=5) is None


@pytest.mark.parametrize("height", [0.0, -0.1])
def test_a_layout_with_no_height_places_nothing(height: float) -> None:
    assert Layout(top=0.8, line_height=height).row_at(0.5, count=5) is None


# What it draws.


def test_it_says_what_is_currently_chosen() -> None:
    """The point of naming the track on the front screen."""
    drawn = dict(screen().columns())

    assert drawn["  Track"] == "Sokol International Racetrack"


def test_the_marker_is_on_one_row_only() -> None:
    front = screen()

    marked = [name for name, _ in front.columns() if name.startswith(">")]

    assert len(marked) == 1


def test_pressing_ride_is_the_first_thing_the_marker_is_on() -> None:
    """The commonest thing anybody does here."""
    assert screen().rows[screen().selected].name == RIDE


def test_the_row_that_starts_a_ride_says_so() -> None:
    front = screen()
    row = front.row(RIDE)

    assert isinstance(row, ActionRow)
    assert row.reading == "start"


def test_the_labels_are_in_the_rider_s_language() -> None:
    """A screen that says it speaks three languages and labels every row in
    English speaks one."""
    from app import i18n

    russian = i18n.load("ru")

    for name, _ in screen().columns():
        plain = name.lstrip("> ")
        assert russian(plain) != plain, f"{plain} is still English in Russian"


def test_the_names_of_real_things_are_left_alone() -> None:
    """A circuit and a route are called what they are called; translating them
    would invent a place that does not exist."""
    front = screen()

    assert front.choice(WORLD).reading == "Sokol International Racetrack"
