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
from typing import Callable, Protocol, Sequence

from optimization.config import RoutingConfig
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

    def distances_from(self, origin: GeoCoordinate) -> Callable[[GeoCoordinate], float]:
        return lambda point: haversine_km(origin, point)


def distances_from(provider: DistanceProvider, origin: GeoCoordinate) -> Callable[[GeoCoordinate], float]:
    """km from `origin` to any point. Used when targets move, so the points are not known up front.

    Uses the provider's fast version when it has one, otherwise one matrix_km call per point.
    """
    if hasattr(provider, "distances_from"):
        return provider.distances_from(origin)
    return lambda point: provider.matrix_km([origin, point])[0][1]


def default_provider(config: RoutingConfig) -> DistanceProvider:
    """Sea-grid distances if the land file is available. Otherwise straight lines, clearly flagged.

    The plan and the baseline both use this, so they always measure distance the same way.
    """
    try:
        from optimization.sea_grid import default_sea_provider

        return default_sea_provider(config)
    except (ImportError, FileNotFoundError) as exc:
        return StraightLineDistance(
            warnings=[f"sea distances unavailable ({exc}); used straight lines instead"]
        )
