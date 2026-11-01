"""Distances between points.

PHASE 1 (now): straight-line distance only. This is TEMPORARY. The optimization
README says straight-line routes are not valid operational routes, so every plan
made with this provider says so in its `message`.

PHASE 2 (next): add `SeaGridDistance` in this file. It must offer the same
`matrix_km` method and a `description`, so the solver does not change at all.
"""

from math import asin, cos, radians, sin, sqrt
from typing import Protocol, Sequence

from shared.schemas import GeoCoordinate

EARTH_RADIUS_KM = 6371.0088


def haversine_km(a: GeoCoordinate, b: GeoCoordinate) -> float:
    """Great-circle distance in km between two WGS84 points."""
    lat1, lat2 = radians(a.latitude), radians(b.latitude)
    d_lat = lat2 - lat1
    d_lon = radians(b.longitude - a.longitude)
    h = sin(d_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(min(1.0, sqrt(h)))


class DistanceProvider(Protocol):
    """Anything that can fill a distance table in km."""

    description: str

    def matrix_km(self, points: Sequence[GeoCoordinate]) -> list[list[float]]: ...


class StraightLineDistance:
    description = "straight-line distances, NOT validated for navigable water"

    def matrix_km(self, points: Sequence[GeoCoordinate]) -> list[list[float]]:
        return [[haversine_km(a, b) for b in points] for a in points]
