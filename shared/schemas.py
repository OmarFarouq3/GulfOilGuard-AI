"""Shared interfaces. Coordinates are WGS84 degrees, never image pixels.

Dataclasses describe contracts; callers must validate provider data at boundaries.
Use timezone-aware UTC timestamps, kilometres, hours, and metres per second.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class GeoCoordinate:
    """Georeferenced WGS84 position; latitude first, longitude second."""

    latitude: float
    longitude: float


@dataclass(frozen=True)
class DetectionOutput:
    image_id: str
    mask_path: Path
    oil_coordinates: tuple[GeoCoordinate, ...] | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class TimedPosition:
    timestamp: datetime
    coordinate: GeoCoordinate


@dataclass(frozen=True)
class DriftOutput:
    simulation_id: str
    initial_location: GeoCoordinate
    positions: tuple[TimedPosition, ...]
    duration_hours: float


@dataclass(frozen=True)
class EnvironmentalData:
    """Local provider files covering the requested region and simulation window."""

    wind_path: Path
    current_path: Path
    start_time: datetime
    end_time: datetime


@dataclass(frozen=True)
class Vessel:
    vessel_id: str
    location: GeoCoordinate
    speed_m_per_s: float
    capacity_m3: float
    available_hours: float


@dataclass(frozen=True)
class ResponseTarget:
    target_id: str
    location: GeoCoordinate
    oil_volume_m3: float


@dataclass(frozen=True)
class VesselRoute:
    vessel_id: str
    assigned_target_ids: tuple[str, ...]
    coordinates: tuple[GeoCoordinate, ...]
    estimated_distance_km: float | None = None
    estimated_travel_hours: float | None = None


@dataclass(frozen=True)
class OptimizationOutput:
    routes: tuple[VesselRoute, ...]
    status: Literal["optimal", "feasible", "infeasible", "not_solved", "error"]
    message: str | None = None
