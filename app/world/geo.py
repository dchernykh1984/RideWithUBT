"""Turning latitude and longitude into metres on a flat local plane.

A circuit is a few kilometres across, so a tangent plane pinned at the world's
origin is exact enough - the curvature it ignores is under a centimetre - and it
gives the renderer and the physics plain metres to work in.

The conversion uses the WGS84 ellipsoid's local radii rather than one average
figure for the earth. That matters more than it sounds: a naive spherical radius
is out by roughly a tenth of a percent, which is four metres over a lap, and lap
distance is a number riders compare against reality.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# WGS84, which is what OpenStreetMap coordinates are in.
SEMI_MAJOR_AXIS_M = 6378137.0
FLATTENING = 1 / 298.257223563
ECCENTRICITY_SQUARED = FLATTENING * (2 - FLATTENING)


@dataclass(frozen=True)
class Origin:
    """Where the world's (0, 0) sits on the globe."""

    lat: float
    lon: float

    @property
    def metres_per_degree_lat(self) -> float:
        """The meridian radius here: how far north a degree of latitude is."""
        radius = _meridian_radius(self.lat)
        return radius * math.pi / 180.0

    @property
    def metres_per_degree_lon(self) -> float:
        """Shrinks towards the poles, which is why it is computed per origin."""
        radius = _prime_vertical_radius(self.lat)
        return radius * math.cos(math.radians(self.lat)) * math.pi / 180.0

    def to_local(self, lat: float, lon: float) -> tuple[float, float]:
        """Metres east and north of the origin."""
        return (
            (lon - self.lon) * self.metres_per_degree_lon,
            (lat - self.lat) * self.metres_per_degree_lat,
        )

    def to_global(self, x: float, y: float) -> tuple[float, float]:
        """The inverse, for writing a position back out as a coordinate."""
        return (
            self.lat + y / self.metres_per_degree_lat,
            self.lon + x / self.metres_per_degree_lon,
        )


def _w(lat: float) -> float:
    return math.sqrt(1 - ECCENTRICITY_SQUARED * math.sin(math.radians(lat)) ** 2)


def _meridian_radius(lat: float) -> float:
    return SEMI_MAJOR_AXIS_M * (1 - ECCENTRICITY_SQUARED) / _w(lat) ** 3


def _prime_vertical_radius(lat: float) -> float:
    return SEMI_MAJOR_AXIS_M / _w(lat)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance, used to check the local projection against."""
    radius = 6371008.8  # mean earth radius
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_lat = p2 - p1
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(d_lon / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))
