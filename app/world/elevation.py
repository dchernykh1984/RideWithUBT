"""Turning sampled ground heights into a rideable profile.

An open elevation model is the only free source of what a circuit's ground does,
and it is far too coarse to use as it comes. SRTM samples every 30 m and rounds
to the metre; a circuit's points are about 10 m apart. So the difference between
two neighbouring points is mostly rounding, and reading it as a slope invents
gradients that are not there - the raw data for Sokol, a circuit that rises and
falls six metres in four and a half kilometres, contains a 22% wall.

That matters more here than it would in a map. The gradient goes straight into
the power model and out to the rider's legs through a smart trainer, so a fake
slope is not a cosmetic wobble - it is resistance the rider actually feels.

So the profile is smoothed along the track, over a window wide enough that the
model's own vertical rounding cannot masquerade as a hill. A metre of rounding
across two hundred metres is half a percent, which is below what anyone notices;
across ten metres it is ten percent, which is a climb.
"""

from __future__ import annotations

from collections.abc import Sequence

# Wide enough to bury a metre of vertical rounding, narrow enough to keep a real
# rise of a few metres over a few hundred.
DEFAULT_WINDOW_M = 200.0


def smooth(
    distances: Sequence[float],
    heights: Sequence[float],
    window_m: float = DEFAULT_WINDOW_M,
    closed: bool = False,
) -> list[float]:
    """Average each height over the track within half a window either side.

    ``distances`` is how far along the track each point is, and must not
    decrease. A closed way wraps: the points before the start line are the ones
    at the end, which is what keeps a lap continuous across it.
    """
    if len(distances) != len(heights):
        raise ValueError("every point needs a distance and a height")
    if not heights:
        return []
    if window_m <= 0:
        return list(heights)
    total = distances[-1]
    half = window_m / 2
    smoothed = []
    for index, here in enumerate(distances):
        gathered = [
            height
            for other, height in zip(distances, heights, strict=True)
            if _within(here, other, half, total, closed)
        ]
        smoothed.append(sum(gathered) / len(gathered) if gathered else heights[index])
    return smoothed


def _within(here: float, other: float, half: float, total: float, closed: bool) -> bool:
    gap = abs(other - here)
    if closed and total > 0:
        # On a loop the far side of the start line is close, not a lap away.
        gap = min(gap, total - gap)
    return gap <= half


def levelled(heights: Sequence[float], start: float, end: float) -> list[float]:
    """Tilt a profile so its ends sit at given heights.

    A branch smoothed on its own drifts away from the circuit it leaves and
    rejoins, which would put a step at the junction. Correcting it linearly
    keeps the branch's own shape and lands both ends where they have to be.
    """
    if not heights:
        return []
    if len(heights) == 1:
        return [start]
    first, last = heights[0], heights[-1]
    count = len(heights) - 1
    return [
        height + (start - first) + ((end - last) - (start - first)) * index / count
        for index, height in enumerate(heights)
    ]
