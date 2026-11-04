"""Geometry helpers that work on plain GeoJSON dicts (no shapely/geopandas needed)."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from services.files import iter_positions

EARTH_RADIUS_KM = 6371.0


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in km. Not a navigable-water distance."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = phi2 - phi1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def path_length_km(coords: list[list[float]]) -> float:
    """Sum of great-circle segment lengths along [[lon, lat], ...]."""
    return sum(haversine_km(*a[:2], *b[:2]) for a, b in zip(coords, coords[1:]))


def bounds(features: Iterable[dict]) -> list[list[float]] | None:
    """Return Folium-style bounds [[south, west], [north, east]] for GeoJSON features."""
    lons, lats = [], []
    for feature in features:
        for pos in iter_positions(feature.get("geometry", {}).get("coordinates")):
            lons.append(pos[0])
            lats.append(pos[1])
    if not lons:
        return None
    return [[min(lats), min(lons)], [max(lats), max(lons)]]


def centroid(feature: dict) -> tuple[float, float] | None:
    """Mean position (lat, lon) of a feature's vertices; good enough for labels."""
    positions = list(iter_positions(feature.get("geometry", {}).get("coordinates")))
    if not positions:
        return None
    return (
        sum(p[1] for p in positions) / len(positions),
        sum(p[0] for p in positions) / len(positions),
    )


def features_center(features: Iterable[dict]) -> tuple[float, float] | None:
    """Mean of the features' centroids (lat, lon)."""
    points = [c for f in features if (c := centroid(f))]
    if not points:
        return None
    return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)


def offset_deg(origin: tuple[float, float], target: tuple[float, float]) -> tuple[float, float]:
    """(dlat, dlon) that moves ``origin`` (lat, lon) onto ``target`` (lat, lon)."""
    return target[0] - origin[0], target[1] - origin[1]


def translate_coords(coords: Any, dlat: float, dlon: float) -> Any:
    """Shift nested GeoJSON [lon, lat, ...] positions; returns new lists, extra dimensions kept.

    A plain degree shift: shapes keep their size to within about 1 % over the Gulf's few
    degrees of latitude, which is fine for repositioning a simulated scenario.
    """
    if isinstance(coords, (list, tuple)) and coords and isinstance(coords[0], (int, float)):
        return [round(coords[0] + dlon, 6), round(coords[1] + dlat, 6), *coords[2:]]
    return [translate_coords(c, dlat, dlon) for c in coords]


def translate_features(features: Iterable[dict], dlat: float, dlon: float) -> list[dict]:
    """Copies of GeoJSON features with their geometry shifted by (dlat, dlon)."""
    return [{**f, "properties": dict(f.get("properties") or {}),
             "geometry": {**f["geometry"], "coordinates": translate_coords(f["geometry"]["coordinates"], dlat, dlon)}}
            for f in features]


def _ring_area_km2(ring: list[list[float]]) -> float:
    """Approximate area of a [lon, lat] ring (equirectangular projection; fine for slicks)."""
    if len(ring) < 3:
        return 0.0
    lat0 = math.radians(sum(p[1] for p in ring) / len(ring))
    xs = [math.radians(p[0]) * math.cos(lat0) * EARTH_RADIUS_KM for p in ring]
    ys = [math.radians(p[1]) * EARTH_RADIUS_KM for p in ring]
    twice = sum(xs[i] * ys[i + 1] - xs[i + 1] * ys[i] for i in range(len(ring) - 1))
    twice += xs[-1] * ys[0] - xs[0] * ys[-1]
    return abs(twice) / 2


def polygon_area_km2(features: Iterable[dict]) -> float:
    """Total area of Polygon/MultiPolygon features (outer rings minus holes), in km²."""
    total = 0.0
    for feature in features:
        geometry = feature.get("geometry") or {}
        polygons = {"Polygon": [geometry.get("coordinates")], "MultiPolygon": geometry.get("coordinates")}.get(
            geometry.get("type"), []
        )
        for rings in polygons or []:
            if rings:
                total += _ring_area_km2(rings[0]) - sum(_ring_area_km2(hole) for hole in rings[1:])
    return total
