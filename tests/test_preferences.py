"""The settings screen, tested without a screen.

Everything a rider decides before they ride is a list of rows, and none of it
needs a window to be decided - which is why a settings screen has tests at all.

The one thing here that reaches outside is scanning for sensors, and that is
handed in, so these run on machines with no Bluetooth in the room. Which is
every machine they run on.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.core.control import ControlMode
from app.core.preferences import (
    BIKE_KG,
    CAPTURE,
    CONTROL,
    LANGUAGE,
    RIDER_KG,
    SCAN,
    TRAINER,
    TYRE_WIDTH,
    VIRTUAL_BIKE,
    WHEEL_SIZE,
    ChoiceRow,
    Found,
    Heading,
    SetupMenu,
)
from app.settings import Settings


def menu(**kwargs: object) -> SetupMenu:
    return SetupMenu(**kwargs)  # type: ignore[arg-type]


def point_at(setup: SetupMenu, name: str) -> None:
    """Put the marker on a named row, the way arrowing to it would."""
    setup.selected = next(
        index for index, row in enumerate(setup.rows) if row.name == name
    )


def value(setup: SetupMenu, name: str) -> str:
    return setup.choice(name).value


def step_to(setup: SetupMenu, name: str, wanted: str) -> None:
    """Arrow along a row until it reaches a value, giving up rather than looping."""
    point_at(setup, name)
    for _ in range(len(setup.choice(name).choices)):
        if value(setup, name) == wanted:
            return
        setup.change(1)
    raise AssertionError(f"{name} never reached {wanted}")


# What there is to decide.


def test_everything_a_rider_has_to_decide_is_on_the_screen() -> None:
    """The point of the exercise: no terminal needed to set the app up."""
    names = {row.name for row in menu().rows}

    assert {
        RIDER_KG,
        BIKE_KG,
        VIRTUAL_BIKE,
        WHEEL_SIZE,
        TYRE_WIDTH,
        TRAINER,
        CONTROL,
        CAPTURE,
        SCAN,
        LANGUAGE,
    } <= names


def test_it_opens_on_what_the_rider_already_has() -> None:
    Settings(
        wheel_size_id="26in",
        wheel_width_id="2.1in",
        trainer_id="saris-fluid2",
        control_mode="erg",
        virtual_bike_id="tt",
        rider_mass_kg=83.0,
    ).save()

    setup = menu()

    assert value(setup, WHEEL_SIZE) == "26in"
    assert value(setup, TYRE_WIDTH) == "2.1in"
    assert value(setup, TRAINER) == "saris-fluid2"
    assert value(setup, CONTROL) == "erg"
    assert value(setup, VIRTUAL_BIKE) == "tt"
    assert setup.number(RIDER_KG).value == 83.0


def test_a_fresh_install_opens_on_something_sensible() -> None:
    setup = menu()

    assert value(setup, WHEEL_SIZE) == "700c"
    assert value(setup, TYRE_WIDTH) == "25"


# Moving about.


def test_the_marker_steps_over_the_headings() -> None:
    """A heading is a label, not a thing to choose."""
    setup = menu()

    for _ in range(len(setup.rows) * 2):
        setup.move(1)
        assert not isinstance(setup.rows[setup.selected], Heading)


def test_moving_up_and_round() -> None:
    setup = menu()
    first = setup.selected
    choosable = sum(1 for row in setup.rows if row.selectable)

    for _ in range(choosable):
        setup.move(1)

    assert setup.selected == first, "a list is a ring in a menu"


def test_moving_backwards_also_steps_over_headings() -> None:
    setup = menu()

    for _ in range(len(setup.rows) * 2):
        setup.move(-1)
        assert not isinstance(setup.rows[setup.selected], Heading)


# Rows that choose from a list.


def test_changing_a_row_walks_its_options() -> None:
    setup = menu()
    point_at(setup, TRAINER)
    first = value(setup, TRAINER)

    setup.change(1)

    assert value(setup, TRAINER) != first


def test_changing_the_rim_offers_the_tyres_that_fit_it() -> None:
    """2.1in is not a 650c size and 20 mm is not a mountain bike one."""
    setup = menu()
    step_to(setup, WHEEL_SIZE, "26in")

    widths = {choice.value for choice in setup.choice(TYRE_WIDTH).choices}

    assert "2.1in" in widths
    assert "18" not in widths


def test_a_rim_passed_over_does_not_throw_the_tyre_away() -> None:
    """700c to 26in goes past 650b and 650c, neither of which takes 35 mm.
    Arriving at a rim that does take it should offer it back."""
    setup = menu()
    step_to(setup, TYRE_WIDTH, "35")

    step_to(setup, WHEEL_SIZE, "26in")

    assert value(setup, TYRE_WIDTH) == "35"


def test_choosing_a_tyre_on_the_new_rim_is_the_choice_that_sticks() -> None:
    setup = menu()
    step_to(setup, WHEEL_SIZE, "26in")
    step_to(setup, TYRE_WIDTH, "2.1in")

    point_at(setup, WHEEL_SIZE)
    setup.change(-1)
    setup.change(1)

    assert value(setup, TYRE_WIDTH) == "2.1in"


# Rows that count.


def test_a_weight_counts_up_and_down() -> None:
    setup = menu()
    point_at(setup, RIDER_KG)
    start = setup.number(RIDER_KG).value

    setup.change(1)
    setup.change(1)

    assert setup.number(RIDER_KG).value == start + 1.0


def test_a_weight_cannot_be_wound_past_what_a_rider_is() -> None:
    setup = menu()
    point_at(setup, RIDER_KG)

    for _ in range(2000):
        setup.change(-1)

    assert setup.number(RIDER_KG).value == 30.0


def test_the_bicycle_weighs_to_a_tenth() -> None:
    setup = menu()
    point_at(setup, BIKE_KG)
    setup.change(1)

    assert "." in setup.number(BIKE_KG).reading


# Toggles.


def test_recording_the_trainer_is_a_yes_or_no() -> None:
    setup = menu()
    point_at(setup, CAPTURE)

    setup.activate()

    assert setup.save().record_trainer_data is True


# Sensors.


def radios(*devices: Found) -> object:
    def scan(seconds: float) -> Sequence[Found]:
        return devices

    return scan


def test_scanning_offers_whatever_answered() -> None:
    setup = menu(scanner=radios(Found("ble:AA", "Wahoo KICKR"), Found("ant:12", "HR")))

    setup.scan()

    labels = "\n".join(setup.lines())
    assert "Wahoo KICKR" in labels
    assert "found 2" in setup.note


def test_a_scan_that_finds_nothing_says_so() -> None:
    """It happens often enough that silence would have a rider pressing again."""
    setup = menu(scanner=radios())

    setup.scan()

    assert "nothing answered" in setup.note


def test_a_build_with_no_radios_says_that_rather_than_nothing() -> None:
    setup = menu()

    setup.scan()

    assert "no radios" in setup.note


def test_pairing_a_sensor_from_the_menu() -> None:
    setup = menu(scanner=radios(Found("ble:AA", "Wahoo KICKR")))
    setup.scan()
    point_at(setup, "  Wahoo KICKR")

    setup.activate()

    assert setup.save().paired_device_ids == ["ble:AA"]


def test_unpairing_one_again() -> None:
    Settings(paired_device_ids=["ble:AA"]).save()
    setup = menu()
    point_at(setup, "  ble:AA")

    setup.activate()

    assert setup.save().paired_device_ids == []


def test_a_sensor_paired_last_week_is_shown_without_the_radio_being_awake() -> None:
    """Otherwise it could never be dropped except by scanning for it."""
    Settings(paired_device_ids=["ble:AA"]).save()

    shown = "\n".join(menu().lines())

    assert "ble:AA" in shown
    assert "paired" in shown


def test_scanning_leaves_the_marker_where_the_rider_left_it() -> None:
    setup = menu(scanner=radios(Found("ble:AA", "Wahoo KICKR")))
    point_at(setup, SCAN)

    setup.activate()

    assert setup.rows[setup.selected].name == SCAN


# What it says, and what it keeps.


def test_the_menu_says_what_the_choices_are_worth() -> None:
    """A rider cannot read a CdA or a rollout; they can read a speed and a
    number of watts."""
    setup = menu()
    setup.choice(TRAINER).point_at("kinetic-road-machine")

    described = setup.summary

    assert "km/h at 250 W" in described
    assert "kg all in" in described
    assert "rollout" in described
    assert "at 30 km/h" in described


def test_the_summary_says_what_is_still_missing() -> None:
    setup = menu()
    setup.choice(TRAINER).choices = ()

    assert "choose a wheel and a trainer" in setup.summary


def test_a_smart_trainer_says_it_measures_itself() -> None:
    setup = menu()
    setup.choice(TRAINER).point_at("generic-smart-ftms")

    assert "measures its own power" in setup.summary


def test_the_lines_show_where_the_rider_is() -> None:
    setup = menu()

    lines = setup.lines()

    assert sum(1 for line in lines if line.startswith(">")) == 1
    assert any(line.startswith("Rider") for line in lines)


def test_nothing_is_written_until_it_is_saved() -> None:
    """Stepping through the trainer list is looking, not choosing."""
    setup = menu()
    setup.choice(TRAINER).point_at("saris-h3")

    assert Settings.load().trainer_id == ""

    setup.save()

    assert Settings.load().trainer_id == "saris-h3"


def test_saving_writes_every_row() -> None:
    setup = menu()
    setup.choice(WHEEL_SIZE).point_at("650b")
    setup.choice(TRAINER).point_at("tacx-neo-2t")
    setup.choice(CONTROL).point_at(ControlMode.ERG.value)
    setup.choice(VIRTUAL_BIKE).point_at("tt")
    setup.choice(LANGUAGE).point_at("ru")
    setup.number(RIDER_KG).value = 83.0

    saved = setup.save()

    assert saved.wheel_size_id == "650b"
    assert saved.trainer_id == "tacx-neo-2t"
    assert saved.trainer_control is ControlMode.ERG
    assert saved.virtual_bike_id == "tt"
    assert saved.language == "ru"
    assert saved.rider_mass_kg == 83.0
    assert Settings.load() == saved


def test_choosing_from_the_menu_drops_a_measured_rollout() -> None:
    """It was measured for a different wheel; keeping it would be wrong."""
    Settings(measured_rollout_mm=2088.0).save()

    menu().save()

    assert Settings.load().measured_rollout_mm is None


def test_a_row_that_chooses_nothing_still_draws() -> None:
    setup = menu()
    setup.choice(TRAINER).choices = ()

    assert any(line.rstrip().endswith("-") for line in setup.lines())


@pytest.mark.parametrize("locale", ["en", "ru", "kk"])
def test_the_screen_speaks_every_language(locale: str) -> None:
    from app import i18n

    translate = i18n.load(locale)

    assert translate("Press tab to close") != ""
    if locale != "en":
        assert translate("Press tab to close") != "Press tab to close"


def test_a_choice_row_can_be_pointed_at_something_it_does_not_have() -> None:
    """A settings file naming a trainer that has since left the catalogue."""
    row = ChoiceRow("x", ())

    row.point_at("gone")  # must simply not raise

    assert row.reading == "-"


def test_a_heading_reads_as_nothing() -> None:
    """It labels a group; there is no value beside it."""
    heading = next(row for row in menu().rows if isinstance(row, Heading))

    assert heading.reading == ""
    assert not heading.selectable


def test_a_toggle_also_answers_to_the_arrows() -> None:
    """Enter is the obvious key for it, but a rider arrowing along a row
    expects that to do something too."""
    setup = menu()
    point_at(setup, CAPTURE)

    setup.change(1)

    assert setup.save().record_trainer_data is True


def test_a_sensor_also_pairs_with_the_arrows() -> None:
    Settings(paired_device_ids=["ble:AA"]).save()
    setup = menu()
    point_at(setup, "  ble:AA")

    setup.change(1)

    assert setup.save().paired_device_ids == []


def test_a_fresh_install_has_not_chosen_a_trainer() -> None:
    """Otherwise the row points at whatever happens to come first, and closing
    the menu saves a trainer the rider never picked."""
    setup = menu()

    assert value(setup, TRAINER) == ""
    assert "not chosen" in setup.choice(TRAINER).reading
    assert setup.save().trainer_id == ""


def test_the_language_is_filed_under_the_application() -> None:
    """It is about the application, not about this ride."""
    setup = menu()
    language_at = next(
        index for index, row in enumerate(setup.rows) if row.name == LANGUAGE
    )
    last_heading = max(
        index
        for index, row in enumerate(setup.rows)
        if isinstance(row, Heading) and index < language_at
    )

    assert setup.rows[last_heading].name == "Application"


def test_riding_without_sensors_is_not_hidden_in_the_settings() -> None:
    """It is a choice about this ride, and a rider looking for it should not
    have to find it behind Settings - which is where it was, and where it was
    not found."""
    from app.core.startscreen import SIMULATE

    assert SIMULATE not in {row.name for row in menu().rows}


def test_the_menu_is_two_columns_rather_than_one_padded_block() -> None:
    """A window's font is not monospaced: padding with spaces lines nothing up
    and a long label shoves its value into the middle of the screen."""
    setup = menu()

    named = setup.columns()

    assert all(len(pair) == 2 for pair in named)
    weight = next(reading for name, reading in named if RIDER_KG in name)
    assert weight.endswith("kg")


def test_a_heading_has_a_label_and_no_value() -> None:
    """A heading comes without the marker a row has, which is how the two are
    told apart when they are drawn - and it is shouted there, not here, so
    that a renderer can translate it first."""
    setup = menu()

    headings = [pair for pair in setup.columns() if not pair[0].startswith((">", " "))]

    assert headings
    assert all(reading == "" for _, reading in headings)
    assert all(name == name.strip() for name, _ in headings)


def test_the_marker_is_on_the_name_not_the_value() -> None:
    setup = menu()
    point_at(setup, RIDER_KG)

    marked = [name for name, _ in setup.columns() if name.startswith(">")]

    assert len(marked) == 1
    assert RIDER_KG in marked[0]
