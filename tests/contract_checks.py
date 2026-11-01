"""Contract checks for the shared handoff dataclasses.

Each check_* function returns a list of human-readable problems.
An empty list means the object satisfies the contract in shared/schemas.py.
Teams can call these on their own outputs before opening a pull request.

Global WGS84 validation always runs. A regional check is optional: pass a
Region (for example GULF_REGION) to also require points inside that box.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
import math

from shared.schemas import (
    DetectionOutput,
    DriftOutput,
    EnvironmentalData,
    GeoCoordinate,
    OptimizationOutput,
    ResponseTarget,
    Vessel,
)


@dataclass(frozen=True)
class Region:
    """Latitude/longitude bounding box in WGS84 degrees."""

    name: str
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float

    def contains(self, lat: float, lon: float) -> bool:
        return self.lat_min <= lat <= self.lat_max and self.lon_min <= lon <= self.lon_max


# Rough box around the Arabian Gulf and Gulf of Oman. Optional; not applied by default.
GULF_REGION = Region("Arabian Gulf and Gulf of Oman", 22.0, 31.0, 47.0, 60.0)

VALID_STATUSES = {"optimal", "feasible", "infeasible", "not_solved", "error"}


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_utc(value) -> bool:
    """True only for a datetime with a zero UTC offset. Never raises."""
    if not isinstance(value, datetime) or value.tzinfo is None:
        return False
    return value.utcoffset() == timedelta(0)


def _utc_problem(value, name: str) -> list[str]:
    if not isinstance(value, datetime):
        return [f"{name}: expected a datetime, got {type(value).__name__}"]
    if not _is_utc(value):
        return [f"{name}: must be timezone-aware UTC"]
    return []


def check_coordinate(coord: GeoCoordinate, name: str = "coordinate") -> list[str]:
    """Global WGS84 validation only."""
    if not isinstance(coord, GeoCoordinate):
        return [f"{name}: expected GeoCoordinate, got {type(coord).__name__}"]
    if not _is_number(coord.latitude) or not _is_number(coord.longitude):
        return [f"{name}: latitude and longitude must be finite numbers"]
    problems = []
    if not -90 <= coord.latitude <= 90:
        problems.append(f"{name}: latitude {coord.latitude} outside [-90, 90]")
    if not -180 <= coord.longitude <= 180:
        problems.append(f"{name}: longitude {coord.longitude} outside [-180, 180]")
    return problems


def check_in_region(coord: GeoCoordinate, region: Region, name: str = "coordinate") -> list[str]:
    """Regional check, applied only when a caller asks for it."""
    problems = check_coordinate(coord, name)
    if problems:
        return problems
    if region.contains(coord.latitude, coord.longitude):
        return []
    swapped = region.contains(coord.longitude, coord.latitude)
    hint = " (looks like latitude and longitude are swapped)" if swapped else ""
    return [f"{name}: ({coord.latitude}, {coord.longitude}) is outside {region.name}{hint}"]


def _check_point(coord, name: str, region: Region | None) -> list[str]:
    return check_in_region(coord, region, name) if region else check_coordinate(coord, name)


def check_detection(out: DetectionOutput, region: Region | None = None) -> list[str]:
    problems = []
    if not out.image_id:
        problems.append("detection: image_id is empty")
    if out.confidence is not None and not (_is_number(out.confidence) and 0 <= out.confidence <= 1):
        problems.append(f"detection: confidence {out.confidence} must be in [0, 1]")
    if out.oil_coordinates is not None:
        if len(out.oil_coordinates) == 0:
            problems.append("detection: oil_coordinates is an empty tuple; use None when georeferencing is missing")
        for i, c in enumerate(out.oil_coordinates):
            problems += _check_point(c, f"detection.oil_coordinates[{i}]", region)
    return problems


def check_environment(env: EnvironmentalData) -> list[str]:
    problems = _utc_problem(env.start_time, "environment.start_time")
    problems += _utc_problem(env.end_time, "environment.end_time")
    if not problems and env.end_time <= env.start_time:
        problems.append("environment: end_time must be after start_time")
    return problems


def check_drift(out: DriftOutput, region: Region | None = None, tolerance_hours: float = 0.5) -> list[str]:
    problems = _check_point(out.initial_location, "drift.initial_location", region)
    if not _is_number(out.duration_hours) or out.duration_hours <= 0:
        problems.append(f"drift: duration_hours {out.duration_hours} must be positive")
    if len(out.positions) < 2:
        problems.append("drift: need at least two timed positions")
        return problems
    time_problems = []
    for i, p in enumerate(out.positions):
        time_problems += _utc_problem(p.timestamp, f"drift.positions[{i}].timestamp")
        problems += _check_point(p.coordinate, f"drift.positions[{i}]", region)
    if time_problems:
        return problems + time_problems
    times = [p.timestamp for p in out.positions]
    if any(b <= a for a, b in zip(times, times[1:])):
        problems.append("drift: timestamps must be strictly increasing")
    span = (times[-1] - times[0]).total_seconds() / 3600
    if _is_number(out.duration_hours) and abs(span - out.duration_hours) > tolerance_hours:
        problems.append(f"drift: positions span {span:.2f} h but duration_hours is {out.duration_hours}")
    return problems


def check_vessel(v: Vessel, region: Region | None = None) -> list[str]:
    problems = _check_point(v.location, f"vessel {v.vessel_id}.location", region)
    for field in ("speed_m_per_s", "capacity_m3", "available_hours"):
        value = getattr(v, field)
        if not _is_number(value) or value <= 0:
            problems.append(f"vessel {v.vessel_id}: {field} {value} must be positive")
    return problems


def check_target(t: ResponseTarget, region: Region | None = None) -> list[str]:
    problems = _check_point(t.location, f"target {t.target_id}.location", region)
    if not _is_number(t.oil_volume_m3) or t.oil_volume_m3 <= 0:
        problems.append(f"target {t.target_id}: oil_volume_m3 {t.oil_volume_m3} must be positive")
    return problems


def check_optimization(
    out: OptimizationOutput,
    vessels: list[Vessel],
    targets: list[ResponseTarget],
    region: Region | None = None,
    require_full_coverage: bool = False,
) -> list[str]:
    """Check a routing result against the fleet and targets it was solved for.

    require_full_coverage: set True if Team C's formulation must assign every
    target. Leave False if partial coverage is allowed (e.g. prioritised
    response with limited vessels). To be confirmed with Team C.
    """
    problems = []
    if out.status not in VALID_STATUSES:
        return [f"optimization: unknown status {out.status!r}"]
    if out.status in {"infeasible", "not_solved", "error"}:
        if out.routes:
            problems.append(f"optimization: status {out.status!r} should not return routes")
        if not out.message:
            problems.append(f"optimization: status {out.status!r} needs a message explaining why")
        return problems

    fleet = {v.vessel_id: v for v in vessels}
    target_ids = {t.target_id for t in targets}
    seen_vessels, seen_targets = set(), set()
    for r in out.routes:
        if r.vessel_id not in fleet:
            problems.append(f"route: unknown vessel {r.vessel_id}")
            continue
        if r.vessel_id in seen_vessels:
            problems.append(f"route: vessel {r.vessel_id} has more than one route")
        seen_vessels.add(r.vessel_id)
        for tid in r.assigned_target_ids:
            if tid not in target_ids:
                problems.append(f"route {r.vessel_id}: unknown target {tid}")
            if tid in seen_targets:
                problems.append(f"route {r.vessel_id}: target {tid} assigned to more than one vessel")
            seen_targets.add(tid)
        if r.assigned_target_ids and not r.coordinates:
            problems.append(f"route {r.vessel_id}: has targets but no coordinates")
        for i, c in enumerate(r.coordinates):
            problems += _check_point(c, f"route {r.vessel_id}.coordinates[{i}]", region)

        distance = r.estimated_distance_km
        if distance is not None and not (_is_number(distance) and distance >= 0):
            problems.append(f"route {r.vessel_id}: estimated_distance_km {distance} must be finite and non-negative")

        hours = r.estimated_travel_hours
        if hours is not None:
            if not (_is_number(hours) and hours >= 0):
                problems.append(f"route {r.vessel_id}: estimated_travel_hours {hours} must be finite and non-negative")
            elif hours > fleet[r.vessel_id].available_hours:
                problems.append(
                    f"route {r.vessel_id}: {hours} h exceeds available_hours {fleet[r.vessel_id].available_hours}"
                )

    if require_full_coverage:
        missing = sorted(target_ids - seen_targets)
        if missing:
            problems.append(f"optimization: targets not assigned to any vessel: {', '.join(missing)}")
    return problems
