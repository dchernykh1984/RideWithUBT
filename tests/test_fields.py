"""Fields you click and work, rather than lists you cycle through.

Stepping a weight to 83 kg one arrow press at a time is eighty-three key
presses, and a row that steps through forty trainers is a row nobody reaches
the end of. Clicking a number opens it for typing; clicking a list opens the
list.
"""

from __future__ import annotations

from app.core.preferences import TRAINER, SetupMenu
from app.core.rows import WINDOW, ChoiceRow, NumberRow, Picking, Typing
from app.core.startscreen import SIMULATE, WORLD, StartScreen
from app.settings import Settings


def weight_row() -> NumberRow:
    return NumberRow("Weight", 75.0, 0.5, 30.0, 200.0, " kg")


def bikes() -> ChoiceRow:
    from app.core.rows import Choice

    return ChoiceRow(
        "Riding",
        (Choice("road", "Road"), Choice("tt", "Time trial"), Choice("upright", "Up")),
    )


# Typing a number.


def test_typing_a_weight_is_one_field_not_eighty_three_key_presses() -> None:
    typing = Typing(weight_row())

    for character in "83":
        typing.key(character)
    typing.commit()

    assert typing.row.value == 83.0


def test_a_decimal_point_is_allowed_once() -> None:
    typing = Typing(weight_row())

    for character in "8.5.5":
        typing.key(character)

    assert typing.text == "8.55"


def test_a_comma_is_a_decimal_point_too() -> None:
    """Half the world types one and means the other."""
    typing = Typing(weight_row())

    for character in "8,5":
        typing.key(character)

    assert typing.text == "8.5"


def test_letters_are_not_numbers() -> None:
    typing = Typing(weight_row())

    for character in "8kg3":
        typing.key(character)

    assert typing.text == "83"


def test_backspace_takes_the_last_one_back() -> None:
    typing = Typing(weight_row())
    for character in "839":
        typing.key(character)

    typing.backspace()

    assert typing.text == "83"


def test_a_field_shows_what_is_being_typed_into_it() -> None:
    typing = Typing(weight_row())
    typing.key("8")

    assert "8" in typing.reading


def test_nothing_typed_leaves_the_value_alone() -> None:
    row = weight_row()

    assert not Typing(row).commit()
    assert row.value == 75.0


def test_a_number_nobody_weighs_is_pulled_back_into_range() -> None:
    """Somebody typing 300 meant 300, and the row knows what a weight can be."""
    typing = Typing(weight_row())
    for character in "300":
        typing.key(character)

    typing.commit()

    assert typing.row.value == 200.0


def test_a_field_cannot_be_typed_into_forever() -> None:
    typing = Typing(weight_row())

    for _ in range(50):
        typing.key("9")

    assert len(typing.text) <= 8


# Picking from a list.


def test_a_list_opens_on_what_is_already_chosen() -> None:
    row = bikes()
    row.point_at("tt")

    picking = Picking(row, row.index)

    assert picking.index == 1


def test_choosing_from_the_list_changes_the_row() -> None:
    row = bikes()
    picking = Picking(row, row.index)

    picking.move(1)
    picking.choose()

    assert row.value == "tt"


def test_the_list_says_which_one_is_in_use() -> None:
    row = bikes()
    picking = Picking(row, row.index)
    picking.move(2)

    drawn = picking.lines()

    assert drawn[0][1] == "in use"
    assert drawn[2][0].startswith(">")


def test_a_mouse_can_land_on_a_line_of_the_list() -> None:
    picking = Picking(bikes(), 0)

    assert picking.point_at(2)
    assert not picking.point_at(9)
    assert picking.index == 2


# The panel that holds them.


def test_clicking_a_number_opens_it_for_typing() -> None:
    front = StartScreen()
    front.selected = _at(front, SIMULATE)

    front.activate()

    assert front.typing is not None
    assert front.busy


def test_clicking_a_list_opens_the_list() -> None:
    setup = SetupMenu()
    setup.selected = _at(setup, TRAINER)

    setup.activate()

    assert setup.picking is not None
    assert setup.open_row is setup.row(TRAINER)


def test_the_list_opens_in_a_box_of_its_own() -> None:
    setup = SetupMenu()
    setup.selected = _at(setup, TRAINER)
    setup.activate()

    drawn = setup.popup()

    assert drawn[0][0].startswith(">")
    assert [name.lstrip("> ") for name, _ in drawn] == [
        choice.label for choice in setup.choice(TRAINER).choices[: len(drawn)]
    ]


def test_a_list_taller_than_the_screen_is_shown_a_windowful_at_a_time() -> None:
    """Thirty-nine trainers do not fit, and a box whose last lines are off the
    bottom of the window is a box nobody can finish reading."""
    setup = SetupMenu()
    setup.selected = _at(setup, TRAINER)
    setup.activate()
    assert len(setup.choice(TRAINER).choices) > WINDOW

    assert len(setup.popup()) == WINDOW


def test_the_window_follows_the_marker_down_the_list() -> None:
    setup = SetupMenu()
    setup.selected = _at(setup, TRAINER)
    setup.activate()
    assert setup.picking is not None

    for _ in range(WINDOW + 3):
        setup.move(1)

    shown = [name.lstrip("> ") for name, _ in setup.popup()]
    marked = setup.choice(TRAINER).choices[setup.picking.index].label
    assert marked in shown, "the marker walked off the end of its own box"
    assert setup.picking.place == f"{setup.picking.index + 1} / 39"


def test_a_click_lands_on_the_line_of_the_box_not_the_list_behind_it() -> None:
    """The box shows part of the list; its third line is not the third option
    once the window has moved."""
    setup = SetupMenu()
    setup.selected = _at(setup, TRAINER)
    setup.activate()
    assert setup.picking is not None
    for _ in range(WINDOW + 3):
        setup.move(1)
    first = setup.picking.first

    setup.point_at(2)

    assert setup.picking.index == first + 2


def test_the_panel_stays_behind_the_open_list() -> None:
    """A box over the panel, not a screen instead of it: a rider picking a
    trainer can still see what the rest of it is set to."""
    setup = SetupMenu()
    setup.selected = _at(setup, TRAINER)
    plain = setup.columns()
    setup.activate()

    drawn = setup.columns()

    assert [name for name, _ in drawn] == [name for name, _ in plain]


def test_the_box_shows_what_is_being_typed_and_what_it_will_take() -> None:
    front = StartScreen()
    front.selected = _at(front, SIMULATE)
    front.activate()
    front.key("2")

    (typed, range_says) = front.popup()[0]

    assert typed.startswith("2")
    assert "W" in typed, "a number without its unit is a number about nothing"
    assert range_says == front.number(SIMULATE).range_says


def test_a_row_with_nothing_open_has_no_box() -> None:
    assert SetupMenu().popup() == []
    assert SetupMenu().open_row is None


def test_enter_takes_what_the_list_is_on() -> None:
    setup = SetupMenu()
    setup.selected = _at(setup, TRAINER)
    setup.activate()
    setup.move(1)

    setup.activate()

    assert setup.picking is None
    assert setup.choice(TRAINER).index == 1


def test_typing_a_number_and_keeping_it() -> None:
    front = StartScreen()
    front.selected = _at(front, SIMULATE)
    front.activate()

    for character in "240":
        front.key(character)
    front.activate()

    assert front.typing is None
    assert front.simulated_watts == 240.0


def test_escape_leaves_a_field_as_it_was() -> None:
    front = StartScreen()
    front.selected = _at(front, SIMULATE)
    front.activate()
    front.key("9")

    front.cancel()

    assert front.typing is None
    assert front.simulated_watts is None


def test_the_arrows_still_step_a_row_without_opening_it() -> None:
    """A rider who knows the list does not want a dialogue about it."""
    setup = SetupMenu()
    setup.selected = _at(setup, TRAINER)

    setup.change(1)

    assert setup.picking is None
    assert setup.choice(TRAINER).index == 1


def test_the_arrows_move_the_open_list_rather_than_the_rows() -> None:
    setup = SetupMenu()
    setup.selected = _at(setup, TRAINER)
    was = setup.selected
    setup.activate()

    setup.move(1)

    assert setup.selected == was
    assert setup.picking is not None
    assert setup.picking.index == 1


def test_typing_swallows_the_arrows_rather_than_moving_about() -> None:
    front = StartScreen()
    front.selected = _at(front, SIMULATE)
    front.activate()

    front.change(1)

    assert front.number(SIMULATE).value == 0.0


def test_a_row_with_one_option_is_not_worth_a_list() -> None:
    from app.core.rows import Choice

    setup = SetupMenu()
    only = setup.choice(TRAINER)
    only.choices = (Choice("one", "The only one"),)
    setup.selected = _at(setup, TRAINER)

    setup.activate()

    assert setup.picking is None


def test_an_action_row_still_just_does_the_thing() -> None:
    done: list[str] = []
    front = StartScreen(on_quit=lambda: done.append("quit"))
    front.selected = _at(front, "Quit")

    front.activate()

    assert done == ["quit"]


def test_a_number_typed_on_the_front_screen_is_kept_for_next_time() -> None:
    front = StartScreen()
    front.selected = _at(front, WORLD)

    front.activate()
    front.activate()

    assert Settings.load().world_id != ""


def _at(panel: StartScreen | SetupMenu, name: str) -> int:
    wanted = panel.row(name)
    return next(index for index, row in enumerate(panel.rows) if row is wanted)


def test_a_mouse_over_the_open_list_moves_the_list() -> None:
    setup = SetupMenu()
    setup.selected = _at(setup, TRAINER)
    was = setup.selected
    setup.activate()

    assert setup.point_at(3)
    assert setup.selected == was, "the rows behind do not move"
    assert setup.picking is not None
    assert setup.picking.index == 3


def test_the_arrows_move_an_open_list_sideways_too() -> None:
    """Left and right are the same gesture as up and down in a list."""
    setup = SetupMenu()
    setup.selected = _at(setup, TRAINER)
    setup.activate()

    setup.change(1)

    assert setup.picking is not None
    assert setup.picking.index == 1


def test_backspace_with_no_field_open_does_nothing() -> None:
    front = StartScreen()

    front.backspace()
    front.key("9")

    assert front.simulated_watts is None


def test_backspace_reaches_the_open_field() -> None:
    front = StartScreen()
    front.selected = _at(front, SIMULATE)
    front.activate()
    for character in "245":
        front.key(character)

    front.backspace()
    front.activate()

    assert front.simulated_watts == 24.0
