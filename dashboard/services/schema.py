"""Bridge to the project-wide contract in ``shared/schemas.py`` (the single source of truth).

The dashboard imports the shared dataclasses directly. ``shared.schemas`` only uses the
standard library (dataclasses, datetime, pathlib, typing); ``check_schema.py`` verifies
that importing it never pulls in torch, opendrift or ortools.

The dataclasses do no runtime validation ("callers must validate provider data at
boundaries"), so the builders below validate before constructing them and raise
``SchemaError`` with a technical message (shown only under Diagnostics).

Conventions taken from the schema module and shared/README.md:
- coordinates: WGS84 degrees, ``GeoCoordinate(latitude, longitude)``; GeoJSON files store
  ``[longitude, latitude]``, so positions are converted explicitly here
- timestamps: timezone-aware UTC (ISO 8601 in files)
- units are encoded in field-name suffixes: ``_km``, ``_hours``, ``_m3``, ``_m_per_s``
- measurements are nonnegative, speeds positive, IDs unique, confidence in [0, 1]
"""

from __future__ import annotations

import dataclasses
import math
import sys
import typing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

if str(config.REPO_ROOT) not in sys.path:
    sys.path.append(str(config.REPO_ROOT))  # appended, so nothing shadows dashboard modules

from shared.schemas import (  # noqa: E402  (import after the path tweak)
    DetectionOutput,
    DriftOutput,
    GeoCoordinate,
    OptimizationOutput,
    ResponseTarget,
    TimedPosition,
    Vessel,
    VesselRoute,
)

__all__ = [
    "DetectionOutput", "DriftOutput", "GeoCoordinate", "OptimizationOutput", "ResponseTarget",
    "TimedPosition", "Vessel", "VesselRoute", "SOLVER_STATUSES", "SchemaError", "unit", "suffix_unit",
]

# Allowed solver statuses, read from the Literal type of OptimizationOutput.status.
SOLVER_STATUSES: tuple[str, ...] = typing.get_args(typing.get_type_hints(OptimizationOutput)["status"])

# Unit suffix convention used by the schema's field names (longest suffix first).
UNIT_SUFFIXES: tuple[tuple[str, str], ...] = (("_m_per_s", "m/s"), ("_hours", "h"), ("_km", "km"), ("_m3", "m³"))


class SchemaError(ValueError):
    """Data does not conform to shared/schemas.py."""


def suffix_unit(name: str) -> str:
    """Display unit for a field name that follows the schema's suffix convention."""
    for suffix, label in UNIT_SUFFIXES:
        if name.endswith(suffix):
            return label
    raise KeyError(f"{name!r} has no unit suffix")


def unit(schema_class: type, field_name: str) -> str:
    """Display unit of a schema dataclass field, e.g. unit(VesselRoute, 'estimated_distance_km') -> 'km'."""
    names = {f.name for f in dataclasses.fields(schema_class)}
    if field_name not in names:
        raise KeyError(f"{schema_class.__name__} has no field {field_name!r}")
    return suffix_unit(field_name)


# --- Primitive validators ------------------------------------------------------------


def number(value: Any, name: str, *, required: bool = False, positive: bool = False,
           maximum: float | None = None) -> float | None:
    """Finite, nonnegative (or positive) float; None when absent and not required."""
    if value is None:
        if required:
            raise SchemaError(f"`{name}` is required")
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SchemaError(f"`{name}` must be a finite number, got {value!r}")
    if value < 0 or (positive and value == 0):
        raise SchemaError(f"`{name}` must be {'positive' if positive else 'nonnegative'}, got {value}")
    if maximum is not None and value > maximum:
        raise SchemaError(f"`{name}` must be at most {maximum}, got {value}")
    return float(value)


def text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"`{name}` must be a non-empty string, got {value!r}")
    return value


def utc(value: Any, name: str = "timestamp") -> datetime:
    """Parse an ISO 8601 timestamp that must be timezone-aware; return it in UTC."""
    if not isinstance(value, str):
        raise SchemaError(f"`{name}` must be an ISO 8601 string, got {value!r}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SchemaError(f"`{name}` is not ISO 8601: {value!r}") from exc
    if parsed.tzinfo is None:
        raise SchemaError(f"`{name}` must be timezone-aware UTC, got naive {value!r}")
    return parsed.astimezone(timezone.utc)


def geo(position: Any) -> GeoCoordinate:
    """GeoJSON position [longitude, latitude] -> GeoCoordinate(latitude, longitude)."""
    if not isinstance(position, (list, tuple)) or len(position) < 2:
        raise SchemaError(f"position must be [longitude, latitude], got {position!r}")
    lon, lat = position[0], position[1]
    return _coordinate(lat, lon)


def geo_object(value: Any, name: str) -> GeoCoordinate:
    """JSON object {"latitude": .., "longitude": ..} (the schema's own field names)."""
    if not isinstance(value, dict):
        raise SchemaError(f"`{name}` must be an object with latitude and longitude")
    return _coordinate(value.get("latitude"), value.get("longitude"))


def _coordinate(lat: Any, lon: Any) -> GeoCoordinate:
    for label, v in (("latitude", lat), ("longitude", lon)):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise SchemaError(f"{label} must be a finite number, got {v!r}")
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise SchemaError(f"coordinate out of range (latitude {lat}, longitude {lon})")
    return GeoCoordinate(latitude=float(lat), longitude=float(lon))


# --- Schema builders -----------------------------------------------------------------


def solver_status(value: Any) -> str:
    if value not in SOLVER_STATUSES:
        raise SchemaError(f"`status` must be one of {', '.join(SOLVER_STATUSES)}, got {value!r}")
    return value


def vessel_route(props: dict, line: list) -> VesselRoute:
    """Build a VesselRoute from GeoJSON LineString coordinates and feature properties."""
    ids = props.get("assigned_target_ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) and i for i in ids):
        raise SchemaError("`assigned_target_ids` must be a list of target ID strings (visiting order)")
    if len(ids) != len(set(ids)):
        raise SchemaError("`assigned_target_ids` contains duplicates")
    return VesselRoute(
        vessel_id=text(props.get("vessel_id"), "vessel_id"),
        assigned_target_ids=tuple(ids),
        coordinates=tuple(geo(p) for p in line),
        estimated_distance_km=number(props.get("estimated_distance_km"), "estimated_distance_km"),
        estimated_travel_hours=number(props.get("estimated_travel_hours"), "estimated_travel_hours"),
    )


def vessel(props: dict, location: GeoCoordinate) -> Vessel | None:
    """Vessel from route properties when its fields are present; location = route start."""
    keys = ("speed_m_per_s", "capacity_m3", "available_hours")
    if not any(k in props for k in keys):
        return None
    return Vessel(
        vessel_id=text(props.get("vessel_id"), "vessel_id"),
        location=location,
        speed_m_per_s=number(props.get("speed_m_per_s"), "speed_m_per_s", required=True, positive=True),
        capacity_m3=number(props.get("capacity_m3"), "capacity_m3", required=True),
        available_hours=number(props.get("available_hours"), "available_hours", required=True),
    )


def response_target(props: dict, geometry: dict) -> ResponseTarget:
    if geometry.get("type") != "Point":
        raise SchemaError(f"target geometry must be a Point (ResponseTarget.location), got {geometry.get('type')}")
    return ResponseTarget(
        target_id=text(props.get("target_id"), "target_id"),
        location=geo(geometry["coordinates"]),
        oil_volume_m3=number(props.get("oil_volume_m3"), "oil_volume_m3", required=True),
    )


def detection_output(props: dict, ring: list, mask_path: Path) -> DetectionOutput:
    """A detected slick as DetectionOutput: outline vertices become oil_coordinates."""
    return DetectionOutput(
        image_id=text(props.get("image_id"), "image_id"),
        mask_path=mask_path,
        oil_coordinates=tuple(geo(p) for p in ring),
        confidence=number(props.get("confidence"), "confidence", maximum=1.0),
    )


def drift_output(meta: dict) -> DriftOutput | None:
    """DriftOutput from meta.json when it carries the schema fields (else None)."""
    keys = ("simulation_id", "initial_location", "positions", "duration_hours")
    if not any(k in meta for k in keys):
        return None
    positions = meta.get("positions")
    if not isinstance(positions, list):
        raise SchemaError("`positions` must be a list of {timestamp, coordinate}")
    timed = tuple(
        TimedPosition(timestamp=utc(p.get("timestamp"), f"positions[{i}].timestamp"),
                      coordinate=geo_object(p.get("coordinate"), f"positions[{i}].coordinate"))
        for i, p in enumerate(positions) if isinstance(p, dict)
    )
    if len(timed) != len(positions):
        raise SchemaError("every entry in `positions` must be an object")
    if any(a.timestamp > b.timestamp for a, b in zip(timed, timed[1:])):
        raise SchemaError("`positions` must be ordered by timestamp")
    return DriftOutput(
        simulation_id=text(meta.get("simulation_id"), "simulation_id"),
        initial_location=geo_object(meta.get("initial_location"), "initial_location"),
        positions=timed,
        duration_hours=number(meta.get("duration_hours"), "duration_hours", required=True),
    )
