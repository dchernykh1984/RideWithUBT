"""Choosing a bike and a trainer.

The catalogues were there from the beginning and nothing could pick from them:
a rider's wheel lived in the settings file and the only way to put it there was
to edit the file by hand."""

from __future__ import annotations

import pytest

from app import setup_commands as setup
from app.core.control import ControlMode
from app.settings import Settings


def test_a_fresh_install_admits_it_knows_nothing() -> None:
    answer = setup.describe_setup()

    text = "\n".join(answer.lines)
    assert "trainer      not set" in text
    assert "wheel        not set" in text
    assert "none paired" in text


def test_the_wheel_list_shows_the_sizes_and_what_they_take() -> None:
    text = "\n".join(setup.list_wheels().lines)

    assert "700c  ISO 622" in text
    assert "29in" in text, "the names people actually use are listed too"
    assert "2.1in" in text, "mountain bike widths are written in inches"
    assert "25" in text


def test_choosing_a_wheel_says_what_it_rolls() -> None:
    """The rollout is the number the whole power estimate hangs off."""
    answer = setup.choose_wheel("700c", "25")

    assert answer.ok
    assert "700c x 25" in answer.lines[0]
    assert "2111 mm" in answer.lines[0]
    assert Settings.load().wheel_size_id == "700c"


def test_a_size_can_be_chosen_by_the_name_people_use() -> None:
    answer = setup.choose_wheel("29in", "2.1in")

    assert answer.ok
    assert Settings.load().wheel_size_id == "700c", "stored by its real name"


@pytest.mark.parametrize(
    ("size", "width"), [("unicycle", "25"), ("700c", "99"), ("700c", "2.1")]
)
def test_a_wheel_that_does_not_exist_points_at_the_list(size: str, width: str) -> None:
    answer = setup.choose_wheel(size, width)

    assert not answer.ok
    assert "--wheels lists" in answer.lines[-1]
    assert Settings.load().wheel_size_id == ""


def test_a_measured_rollout_beats_the_catalogue() -> None:
    setup.choose_wheel("700c", "25")

    answer = setup.choose_rollout(2088.0)

    assert answer.ok
    wheel = Settings.load().wheel
    assert wheel is not None
    assert wheel.rollout_mm == 2088.0


def test_choosing_from_the_catalogue_again_drops_the_old_measurement() -> None:
    """It was measured for a different wheel; keeping it would be silently wrong."""
    setup.choose_rollout(2088.0)

    setup.choose_wheel("700c", "28")

    wheel = Settings.load().wheel
    assert wheel is not None
    assert wheel.rollout_mm != 2088.0
    assert not wheel.is_measured


def test_a_rollout_in_the_wrong_unit_is_refused() -> None:
    answer = setup.choose_rollout(2.088)

    assert not answer.ok
    assert "unit" in answer.lines[0]


def test_the_trainer_list_says_which_are_measured() -> None:
    text = "\n".join(setup.list_trainers().lines)

    assert "Wahoo" in text
    assert "kinetic-road-machine" in text
    assert "estimated" in text, "nothing ships with a measured curve yet"


def test_choosing_a_classic_trainer_says_what_its_watts_will_be_worth() -> None:
    setup.choose_wheel("700c", "25")

    answer = setup.choose_trainer("kinetic-road-machine")

    text = "\n".join(answer.lines)
    assert answer.ok
    assert "Kinetic Road Machine" in text
    assert "at 30 km/h" in text
    assert "an estimate" in text
    assert "--capture-trainer" in text


def test_a_smart_trainer_is_not_estimated_and_says_so() -> None:
    answer = setup.choose_trainer("generic-smart-ftms")

    assert "measures its own power" in "\n".join(answer.lines)


def test_a_classic_trainer_without_a_wheel_says_what_is_missing() -> None:
    """Its watts cannot be worked out from a wheel nobody has described."""
    answer = setup.choose_trainer("kinetic-road-machine")

    assert "set a wheel with --wheel" in "\n".join(answer.lines)


def test_a_trainer_that_does_not_exist_points_at_the_list() -> None:
    answer = setup.choose_trainer("nonesuch")

    assert not answer.ok
    assert "--trainers lists" in answer.lines[-1]


@pytest.mark.parametrize("mode", [mode.value for mode in ControlMode])
def test_every_control_mode_can_be_chosen_and_is_explained(mode: str) -> None:
    answer = setup.choose_control(mode)

    assert answer.ok
    assert answer.lines[0].startswith(f"{mode}: ")
    assert Settings.load().control_mode == mode


def test_a_control_mode_that_is_not_one_lists_the_ones_that_are() -> None:
    answer = setup.choose_control("teleport")

    assert not answer.ok
    assert "erg" in answer.lines[0] and "simulation" in answer.lines[0]


def test_the_setup_reads_back_what_was_chosen() -> None:
    setup.choose_wheel("700c", "28")
    setup.choose_trainer("saris-fluid2")
    setup.choose_control("erg")

    text = "\n".join(setup.describe_setup().lines)

    assert "Saris Fluid2" in text
    assert "700c x 28" in text
    assert "control      erg" in text


# The rider, and what they are riding.


def test_the_bicycles_say_what_each_is_worth() -> None:
    """A CdA means nothing to a rider; a speed at a known effort does."""
    answer = setup.list_bikes()

    assert answer.ok
    text = "\n".join(answer.lines)
    assert "road-aerobars" in text
    assert "tt" in text
    assert "km/h" in text


def test_the_bicycle_list_marks_the_one_being_ridden() -> None:
    setup.choose_bike("tt")

    marked = [line for line in setup.list_bikes().lines if "<-" in line]

    assert len(marked) == 1
    assert "tt" in marked[0]


def test_choosing_a_bicycle_keeps_it() -> None:
    answer = setup.choose_bike("road-aerobars")

    assert answer.ok
    assert Settings.load().virtual_bike_id == "road-aerobars"


def test_a_bicycle_nobody_stocks_is_refused_with_a_way_forward() -> None:
    answer = setup.choose_bike("penny-farthing")

    assert not answer.ok
    assert "--bikes" in "\n".join(answer.lines)


def test_saying_what_you_weigh() -> None:
    answer = setup.choose_rider(83.0, 9.0)

    assert answer.ok
    settings = Settings.load()
    assert settings.rider_mass_kg == 83.0
    assert settings.bike_mass_kg == 9.0
    assert settings.bike.total_mass_kg == 92.0


def test_the_bicycle_keeps_its_weight_when_only_the_rider_is_given() -> None:
    setup.choose_rider(83.0, 7.5)

    setup.choose_rider(80.0)

    assert Settings.load().bike_mass_kg == 7.5


@pytest.mark.parametrize("kilograms", [10.0, 400.0])
def test_a_weight_nobody_is_gets_refused(kilograms: float) -> None:
    answer = setup.choose_rider(kilograms)

    assert not answer.ok
    assert Settings.load().rider_mass_kg != kilograms


def test_a_bicycle_weight_nobody_rides_gets_refused() -> None:
    answer = setup.choose_rider(80.0, 100.0)

    assert not answer.ok


def test_a_measured_drag_figure_is_kept_and_used() -> None:
    setup.choose_bike("road")

    answer = setup.choose_cda(0.24)

    assert answer.ok
    assert Settings.load().bike.cda_m2 == 0.24


def test_clearing_a_measured_drag_figure_goes_back_to_the_catalogue() -> None:
    setup.choose_bike("road")
    setup.choose_cda(0.24)

    setup.choose_cda(None)

    assert Settings.load().bike.cda_m2 == 0.32


@pytest.mark.parametrize("cda", [0.01, 2.0])
def test_a_frontal_area_nobody_has_gets_refused(cda: float) -> None:
    answer = setup.choose_cda(cda)

    assert not answer.ok
    assert Settings.load().measured_cda_m2 is None


def test_the_setup_summary_says_who_is_riding_what() -> None:
    setup.choose_rider(83.0, 9.0)
    setup.choose_bike("road-aerobars")

    described = "\n".join(setup.describe_setup().lines)

    assert "83 kg" in described
    assert "time trial bars" in described
    assert "0.267" in described


def test_the_summary_says_when_a_drag_figure_was_measured() -> None:
    setup.choose_cda(0.24)

    assert "(measured)" in "\n".join(setup.describe_setup().lines)
