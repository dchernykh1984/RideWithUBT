from __future__ import annotations

import math

import pytest

from app.trainer import wheels
from app.trainer.wheels import UnknownWheelError, Wheel, nominal_rollout_mm


def test_nominal_rollout_is_the_circumference_over_the_tyre() -> None:
    # A 700c rim is 622 mm across the bead seats; a 25 mm tyre adds itself twice.
    assert nominal_rollout_mm(622, 25) == pytest.approx(math.pi * 672)


def test_a_700c_wheel_lands_where_a_road_wheel_should() -> None:
    rollout = Wheel(size_id="700c", width_id="25").rollout_mm

    # Published rollout tables put a 700x25c at roughly 2100 mm; the geometric
    # figure is a few millimetres longer because a loaded tyre flattens.
    assert 2090 < rollout < 2125


@pytest.mark.parametrize(
    ("size_id", "width_id"),
    [("700c", "23"), ("650b", "2.1in"), ("26in", "2.1in"), ("20in", "1.75in")],
)
def test_every_catalogue_pick_gives_a_plausible_rollout(
    size_id: str, width_id: str
) -> None:
    rollout = Wheel(size_id=size_id, width_id=width_id).rollout_mm

    assert wheels.MIN_ROLLOUT_MM < rollout < wheels.MAX_ROLLOUT_MM


def test_a_wider_tyre_rolls_further() -> None:
    narrow = Wheel(size_id="700c", width_id="23").rollout_mm
    wide = Wheel(size_id="700c", width_id="32").rollout_mm

    assert wide > narrow


def test_aliases_resolve_to_the_same_size() -> None:
    catalogue = wheels.catalogue()

    assert catalogue.size("29in") is catalogue.size("700c")
    assert catalogue.size("27.5in") is catalogue.size("650b")


def test_unknown_size_and_width_are_reported_separately() -> None:
    with pytest.raises(UnknownWheelError, match="wheel size"):
        wheels.catalogue().size("nonesuch")
    with pytest.raises(UnknownWheelError, match="tyre width"):
        wheels.catalogue().size("700c").width("99")


def test_a_measured_rollout_beats_the_catalogue() -> None:
    wheel = Wheel(size_id="700c", width_id="25", measured_rollout_mm=2088.0)

    assert wheel.is_measured
    assert wheel.rollout_mm == 2088.0


def test_a_wheel_needs_either_a_measurement_or_a_full_pick() -> None:
    with pytest.raises(ValueError, match="size and a width"):
        Wheel(size_id="700c")
    with pytest.raises(ValueError, match="size and a width"):
        Wheel()


@pytest.mark.parametrize("rollout", [2.096, 209600.0])
def test_a_rollout_in_the_wrong_unit_is_refused(rollout: float) -> None:
    with pytest.raises(ValueError, match="wrong unit"):
        Wheel(measured_rollout_mm=rollout)


def test_speed_comes_from_revolutions_and_rollout() -> None:
    wheel = Wheel(measured_rollout_mm=2000.0)

    # Two metres per revolution, five revolutions a second: ten metres a second.
    assert wheel.speed_ms(5.0) == pytest.approx(10.0)


def test_the_shipped_catalogue_is_usable() -> None:
    catalogue = wheels.catalogue()

    assert "700c" in catalogue.size_ids
    assert len(catalogue.sizes) >= 5
    for size in catalogue.sizes:
        assert size.widths, f"{size.id} offers no tyre widths"
        assert 300 < size.bead_seat_mm < 700
        assert len({width.id for width in size.widths}) == len(size.widths)


def test_a_size_with_no_widths_is_rejected() -> None:
    """A size nobody can pick a tyre for would be an empty dropdown at runtime."""
    with pytest.raises(ValueError, match="no tyre widths"):
        wheels.parse_size({"id": "700c", "bead_seat_mm": 622, "widths": []})
