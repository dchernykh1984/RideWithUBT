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
