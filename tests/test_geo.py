from __future__ import annotations

import math

import pytest

from app.world.geo import Origin, haversine_m

# The origin used by the Sokol world, so the numbers below are the ones that
# actually matter to a built track.
SOKOL = Origin(lat=43.581443, lon=76.565126)


def test_the_origin_is_the_zero_point() -> None:
    assert SOKOL.to_local(SOKOL.lat, SOKOL.lon) == (0.0, 0.0)


def test_north_and_east_are_positive() -> None:
    east, north = SOKOL.to_local(SOKOL.lat + 0.01, SOKOL.lon + 0.01)

    assert east > 0
    assert north > 0


def test_a_degree_of_latitude_is_about_111_kilometres() -> None:
    assert 110_900 < SOKOL.metres_per_degree_lat < 111_400


def test_a_degree_of_longitude_shrinks_with_the_latitude() -> None:
    """At Almaty's latitude a degree of longitude is about four fifths as long."""
    ratio = SOKOL.metres_per_degree_lon / SOKOL.metres_per_degree_lat

    assert ratio == pytest.approx(0.725, abs=0.01)


def test_the_equator_has_the_longer_degree_of_longitude() -> None:
    assert Origin(0.0, 0.0).metres_per_degree_lon > SOKOL.metres_per_degree_lon


@pytest.mark.parametrize(
    ("d_lat", "d_lon"),
    [(0.0, 0.02), (0.02, 0.0), (0.01, 0.01), (-0.015, 0.008)],
)
def test_the_flat_projection_agrees_with_the_globe(d_lat: float, d_lon: float) -> None:
    """Over the couple of kilometres a circuit spans, the plane and the globe must
    give the same answer to within a few metres in a couple of kilometres.

    They do not agree exactly, and the difference is not the plane's fault: the
    haversine here rides on a sphere of mean radius, which at this latitude is
    itself a couple of tenths of a percent out. The projection uses the local
    ellipsoid radii and is the more accurate of the two - so this checks they are
    in the same place, and `test_the_ellipsoid_radii_are_wgs84` pins the accuracy.
    """
    lat, lon = SOKOL.lat + d_lat, SOKOL.lon + d_lon
    x, y = SOKOL.to_local(lat, lon)

    flat = (x**2 + y**2) ** 0.5
    curved = haversine_m(SOKOL.lat, SOKOL.lon, lat, lon)

    assert flat == pytest.approx(curved, rel=3e-3)


@pytest.mark.parametrize(
    ("lat", "expected_km"),
    [
        # Standard WGS84 figures: the meridian radius of curvature is smallest at
        # the equator and largest at the pole.
        (0.0, 6335.439),
        (45.0, 6367.382),
        (90.0, 6399.594),
    ],
)
def test_the_ellipsoid_radii_are_wgs84(lat: float, expected_km: float) -> None:
    metres_per_degree = Origin(lat, 0.0).metres_per_degree_lat
    radius_km = metres_per_degree * 180.0 / math.pi / 1000.0

    assert radius_km == pytest.approx(expected_km, abs=0.01)


def test_converting_back_returns_the_coordinate() -> None:
    lat, lon = SOKOL.to_global(*SOKOL.to_local(43.59, 76.58))

    assert lat == pytest.approx(43.59)
    assert lon == pytest.approx(76.58)
