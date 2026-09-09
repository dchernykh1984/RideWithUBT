"""Smoothing a sampled ground profile.

The reason this exists is not tidiness. A gradient goes into the power model and
out through a smart trainer into the rider's legs, so an elevation model's
rounding read as a slope is resistance somebody actually pushes against."""

from __future__ import annotations

import pytest

from app.world.elevation import DEFAULT_WINDOW_M, levelled, smooth


def evenly(count: int, spacing: float = 10.0) -> list[float]:
    return [index * spacing for index in range(count)]


def test_a_flat_profile_stays_flat() -> None:
    distances = evenly(20)

    assert smooth(distances, [650.0] * 20) == [650.0] * 20


def test_rounding_noise_is_averaged_away() -> None:
    """A metre up and down between neighbours is the model, not a hill."""
    distances = evenly(41)
    jagged = [650.0 + (1.0 if index % 2 else 0.0) for index in range(41)]

    smoothed = smooth(distances, jagged, window_m=100.0)

    middle = smoothed[10:30]
    assert max(middle) - min(middle) < 0.1
    assert 650.0 < sum(middle) / len(middle) < 651.0


def test_a_real_slope_survives() -> None:
    """Smoothing that flattened a hill would be no better than the noise."""
    distances = evenly(41, spacing=25.0)
    climbing = [600.0 + index * 2.5 for index in range(41)]  # a steady 10%

    smoothed = smooth(distances, climbing, window_m=100.0)

    rise = smoothed[-5] - smoothed[5]
    run = distances[-5] - distances[5]
    assert rise / run == pytest.approx(0.1, abs=0.005)


def test_a_loop_is_smoothed_across_its_start_line() -> None:
    """Otherwise a lap has a step in it at the one point every lap crosses."""
    distances = evenly(41)
    heights = [650.0] * 40 + [660.0]  # the last point is also the first

    open_way = smooth(distances, heights, window_m=100.0, closed=False)
    closed_way = smooth(distances, heights, window_m=100.0, closed=True)

    assert open_way[0] != pytest.approx(open_way[-1], abs=0.01)
    assert closed_way[0] == pytest.approx(closed_way[-1], abs=0.01)


def test_a_window_of_nothing_changes_nothing() -> None:
    heights = [1.0, 5.0, 2.0]

    assert smooth([0.0, 10.0, 20.0], heights, window_m=0.0) == heights


def test_an_empty_profile_is_not_an_error() -> None:
    assert smooth([], []) == []


def test_every_point_needs_a_height() -> None:
    with pytest.raises(ValueError, match="a distance and a height"):
        smooth([0.0, 10.0], [650.0])


def test_the_default_window_is_wide_enough_to_bury_a_metre() -> None:
    """A metre of rounding across the window has to come out under a percent."""
    assert 1.0 / DEFAULT_WINDOW_M < 0.01


# Joining a branch back to the circuit it leaves.


def test_a_branch_is_tilted_to_meet_the_circuit_at_both_ends() -> None:
    joined = levelled([100.0, 101.0, 102.0], start=200.0, end=210.0)

    assert joined[0] == pytest.approx(200.0)
    assert joined[-1] == pytest.approx(210.0)


def test_tilting_keeps_the_branch_shape() -> None:
    """Its own bumps are real; only where its ends sit is being corrected."""
    bumpy = [100.0, 103.0, 101.0, 104.0, 102.0]

    joined = levelled(bumpy, start=100.0, end=102.0)

    assert joined == pytest.approx(bumpy)


def test_a_branch_of_one_point_lands_where_it_is_told() -> None:
    assert levelled([50.0], start=200.0, end=210.0) == [200.0]


def test_a_branch_of_nothing_is_not_an_error() -> None:
    assert levelled([], start=1.0, end=2.0) == []
