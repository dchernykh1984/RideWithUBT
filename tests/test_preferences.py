"""The settings screen, tested without a screen.

Choosing a wheel and a trainer from a window is picking from lists and saving the
result. None of that needs a window to be decided, so none of it is in one."""

from __future__ import annotations

import pytest

from app.core.control import ControlMode
from app.core.preferences import CONTROL, TRAINER, TYRE_WIDTH, WHEEL_SIZE, SetupMenu
from app.settings import Settings


def menu() -> SetupMenu:
    return SetupMenu()


def row(setup: SetupMenu, name: str):  # type: ignore[no-untyped-def]
    return next(item for item in setup.rows if item.name == name)


def chosen(setup: SetupMenu, name: str) -> str:
    picked = row(setup, name).chosen
    assert picked is not None
    return picked.value


def test_the_menu_offers_everything_there_is_to_choose() -> None:
    setup = menu()

    assert [item.name for item in setup.rows] == [
        WHEEL_SIZE,
        TYRE_WIDTH,
        TRAINER,
        CONTROL,
    ]
    assert all(item.choices for item in setup.rows)


def test_it_opens_on_what_the_rider_already_has() -> None:
    Settings(
        wheel_size_id="26in",
        wheel_width_id="2.1in",
        trainer_id="saris-fluid2",
        control_mode="erg",
    ).save()

    setup = menu()

    assert chosen(setup, WHEEL_SIZE) == "26in"
    assert chosen(setup, TYRE_WIDTH) == "2.1in"
    assert chosen(setup, TRAINER) == "saris-fluid2"
    assert chosen(setup, CONTROL) == "erg"


def test_a_fresh_install_opens_on_something_sensible() -> None:
    setup = menu()

    assert chosen(setup, WHEEL_SIZE) == "700c"
    assert chosen(setup, TYRE_WIDTH) == "25"


def test_moving_down_and_round() -> None:
    """A list is a ring in a menu: past the bottom is the top."""
    setup = menu()

    setup.move(1)
    assert setup.selected == 1

    setup.move(len(setup.rows))
    assert setup.selected == 1

    setup.selected = 0
    setup.move(-1)
    assert setup.selected == len(setup.rows) - 1


def test_changing_a_row_walks_its_options() -> None:
    setup = menu()
    setup.selected = 2  # the trainers

    first = chosen(setup, TRAINER)
    setup.change(1)

    assert chosen(setup, TRAINER) != first


def test_changing_the_rim_offers_the_tyres_that_fit_it() -> None:
    """2.1in is not a 650c size and 20 mm is not a mountain bike one."""
    setup = menu()
    setup.selected = 0
    row(setup, WHEEL_SIZE).point_at("700c")

    while chosen(setup, WHEEL_SIZE) != "26in":
        setup.change(1)

    widths = {choice.value for choice in row(setup, TYRE_WIDTH).choices}
    assert "2.1in" in widths
    assert "18" not in widths, "a road tyre width is not offered for a 26in rim"


def test_a_width_that_both_rims_take_survives_the_change() -> None:
    setup = menu()
    setup.selected = 1
    while chosen(setup, TYRE_WIDTH) != "35":
        setup.change(1)

    setup.selected = 0
    setup.change(1)

    assert chosen(setup, WHEEL_SIZE) == "650b"
    assert chosen(setup, TYRE_WIDTH) != "35", "650b has no 35 mm tyre"


def test_a_rim_passed_over_does_not_throw_the_tyre_away() -> None:
    """Scrolling through rims to find one is not a decision about tyres.

    700c to 26in goes past 650b and 650c, neither of which takes a 35 mm tyre.
    Arriving at a rim that does take it should offer it back."""
    setup = menu()
    setup.selected = 1
    while chosen(setup, TYRE_WIDTH) != "35":
        setup.change(1)

    setup.selected = 0
    while chosen(setup, WHEEL_SIZE) != "26in":
        setup.change(1)

    assert chosen(setup, TYRE_WIDTH) == "35", "26in takes 35 mm too"


def test_choosing_a_tyre_on_the_new_rim_is_the_choice_that_sticks() -> None:
    """Having settled on a fat tyre, going back to 700c must not undo it."""
    setup = menu()
    setup.selected = 0
    while chosen(setup, WHEEL_SIZE) != "26in":
        setup.change(1)

    setup.selected = 1
    while chosen(setup, TYRE_WIDTH) != "2.1in":
        setup.change(1)

    setup.selected = 0
    setup.change(-1)  # back off 26in and onto it again
    setup.change(1)

    assert chosen(setup, TYRE_WIDTH) == "2.1in"


def test_the_menu_says_what_the_choices_will_mean() -> None:
    setup = menu()
    row(setup, TRAINER).point_at("kinetic-road-machine")

    assert "at 30 km/h" in setup.summary
    assert "estimated" in setup.summary
    assert "rollout" in setup.summary


def test_a_smart_trainer_says_it_measures_itself() -> None:
    setup = menu()
    row(setup, TRAINER).point_at("generic-smart-ftms")

    assert "measures its own power" in setup.summary


def test_with_no_trainer_chosen_it_says_what_is_missing() -> None:
    setup = menu()
    row(setup, TRAINER).choices = ()

    assert setup.summary == "choose a wheel and a trainer"


def test_nothing_is_written_until_it_is_saved() -> None:
    """Stepping through the trainer list is looking, not choosing."""
    setup = menu()
    row(setup, TRAINER).point_at("saris-h3")

    assert Settings.load().trainer_id == ""

    setup.save()

    assert Settings.load().trainer_id == "saris-h3"


def test_saving_writes_every_row() -> None:
    setup = menu()
    row(setup, WHEEL_SIZE).point_at("650b")
    row(setup, TYRE_WIDTH).choices = row(setup, TYRE_WIDTH).choices  # unchanged
    row(setup, TRAINER).point_at("tacx-neo-2t")
    row(setup, CONTROL).point_at(ControlMode.ERG.value)

    saved = setup.save()

    assert saved.wheel_size_id == "650b"
    assert saved.trainer_id == "tacx-neo-2t"
    assert saved.trainer_control is ControlMode.ERG
    assert Settings.load() == saved


def test_choosing_from_the_menu_drops_a_measured_rollout() -> None:
    """It was measured for a different wheel; keeping it would be silently wrong."""
    Settings(measured_rollout_mm=2088.0).save()

    menu().save()

    assert Settings.load().measured_rollout_mm is None


def test_the_lines_show_where_the_rider_is() -> None:
    setup = menu()
    setup.move(2)

    lines = setup.lines()

    assert len(lines) == len(setup.rows)
    assert lines[2].startswith(">")
    assert sum(line.startswith(">") for line in lines) == 1


def test_an_empty_row_shows_a_dash_rather_than_breaking() -> None:
    setup = menu()
    row(setup, TRAINER).choices = ()

    assert any(line.rstrip().endswith("-") for line in setup.lines())


@pytest.mark.parametrize("locale", ["en", "ru", "kk"])
def test_the_screen_speaks_every_language(locale: str) -> None:
    from app import i18n

    translate = i18n.load(locale)

    assert translate("Press tab to close") != ""
    if locale != "en":
        assert translate("Press tab to close") != "Press tab to close"
