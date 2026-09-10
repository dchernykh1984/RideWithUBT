"""What stands beside the track.

A circuit is not a ribbon of asphalt in an empty field. The thing that tells a
rider where they are on a lap is what is beside them - the pit garages, the
grandstand, the tower at the last corner - and without any of it every corner
looks like every other corner.

These are not invented. OpenStreetMap has the footprints of the buildings at
this circuit, surveyed in the same trace as the track itself, so they stand
where they really stand and are the shape they really are. What open data does
not have is how tall they are, so heights come from the world's recipe, by what
kind of building it is: a grandstand is not a garage.

Photographs would give texture and nothing else - not position, not shape, not
scale - and they are somebody's to license. Footprints plus stated heights give
a rider what they actually need from scenery, which is knowing where they are.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.world.network import Point

#: What a building is, when open data does not say more than "a building".
DEFAULT_KIND = "building"

#: How tall each kind stands when the recipe does not say. Storeys of about
#: three metres, which is what these are.
DEFAULT_HEIGHTS: dict[str, float] = {
    "grandstand": 12.0,
    "garage": 7.0,
    "hotel": 15.0,
    "tower": 18.0,
    DEFAULT_KIND: 6.0,
}


@dataclass(frozen=True)
class Building:
    """One structure beside the track: where it stands, and how tall."""

    id: str
    kind: str
    footprint: tuple[Point, ...]
    height_m: float

    def __post_init__(self) -> None:
        if len(self.footprint) < 3:
            raise ValueError(f"building {self.id!r} has no outline")
        if self.height_m <= 0:
            raise ValueError(f"building {self.id!r} has no height")

    @property
    def base_m(self) -> float:
        """The ground it stands on: the lowest corner of its own footprint."""
        return min(point.z for point in self.footprint)

    @property
    def centre(self) -> Point:
        count = len(self.footprint)
        return Point(
            x=sum(point.x for point in self.footprint) / count,
            y=sum(point.y for point in self.footprint) / count,
            z=self.base_m,
        )

    @property
    def span_m(self) -> float:
        """How far across it is, for deciding what is worth drawing."""
        xs = [point.x for point in self.footprint]
        ys = [point.y for point in self.footprint]
        return max(max(xs) - min(xs), max(ys) - min(ys))


def height_for(kind: str, heights: dict[str, float] | None = None) -> float:
    """How tall this kind of building stands in this world."""
    table = {**DEFAULT_HEIGHTS, **(heights or {})}
    return table.get(kind, table[DEFAULT_KIND])


def kind_of(tags: dict[str, str]) -> str:
    """What kind of thing open data says this is.

    `building=yes` means "a building, and nobody said what sort", which is most
    of them, so it is read as exactly that rather than as a kind of its own.
    """
    building = tags.get("building", "")
    if building and building != "yes":
        return building
    if tags.get("man_made") == "tower":
        return "tower"
    return DEFAULT_KIND


def named(tags: dict[str, str]) -> str:
    return tags.get("name", "")


def sorted_by_size(buildings: Sequence[Building]) -> tuple[Building, ...]:
    """Biggest first, which is the order to draw them in if not all of them are."""
    return tuple(sorted(buildings, key=lambda building: -building.span_m))
