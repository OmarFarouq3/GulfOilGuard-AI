"""Distances between points: the shared pieces and the straight-line fallback.

Straight-line distance is only a FALLBACK. The optimization README says
straight-line routes are not valid operational routes, so every plan made with
this provider says so in its `message`.

The navigable-water version (SeaGridDistance) lives in optimization/sea_grid.py.
It is a separate file so that code that only needs straight lines does not need
numpy and scipy installed. Both offer the same `matrix_km` method, `description`
and `warnings`, so the solver does not care which one it gets.
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
    warnings: list[str]

    def matrix_km(
        self, points: Sequence[GeoCoordinate], labels: Sequence[str] | None = None
    ) -> list[list[float]]: ...


class StraightLineDistance:
    description = "straight-line distances, NOT validated for navigable water"

    def __init__(self, warnings: Sequence[str] = ()) -> None:
        self.warnings: list[str] = list(warnings)

    def matrix_km(
        self, points: Sequence[GeoCoordinate], labels: Sequence[str] | None = None
    ) -> list[list[float]]:
        return [[haversine_km(a, b) for b in points] for a in points]
