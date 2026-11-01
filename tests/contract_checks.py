"""Contract checks for the shared handoff dataclasses.

Each check_* function returns a list of human-readable problems.
An empty list means the object satisfies the contract in shared/schemas.py.
Teams can call these on their own outputs before opening a pull request.
"""

from datetime import timedelta
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

# Rough box around the Arabian Gulf and Gulf of Oman (WGS84 degrees).
GULF_LAT_RANGE = (22.0, 31.0)
GULF_LON_RANGE = (47.0, 60.0)

VALID_STATUSES = {"optimal", "feasible", "infeasible", "not_solved", "error"}


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_utc(dt) -> bool:
    return dt.tzinfo is not None and dt.utcoffset() == timedelta(0)


def check_coordinate(coord: GeoCoordinate, name: str = "coordinate", gulf_only: bool = True) -> list[str]:
    problems = []
    if not isinstance(coord, GeoCoordinate):
        return [f"{name}: expected GeoCoordinate, got {type(coord).__name__}"]
    if not _is_number(coord.latitude) or not _is_number(coord.longitude):
        return [f"{name}: latitude and longitude must be finite numbers"]
    if not -90 <= coord.latitude <= 90:
        problems.append(f"{name}: latitude {coord.latitude} outside [-90, 90]")
    if not -180 <= coord.longitude <= 180:
        problems.append(f"{name}: longitude {coord.longitude} outside [-180, 180]")
    if gulf_only and not problems:
        in_lat = GULF_LAT_RANGE[0] <= coord.latitude <= GULF_LAT_RANGE[1]
        in_lon = GULF_LON_RANGE[0] <= coord.longitude <= GULF_LON_RANGE[1]
        if not (in_lat and in_lon):
            swapped = (GULF_LAT_RANGE[0] <= coord.longitude <= GULF_LAT_RANGE[1]
                       and GULF_LON_RANGE[0] <= coord.latitude <= GULF_LON_RANGE[1])
            hint = " (looks like latitude and longitude are swapped)" if swapped else ""
            problems.append(
                f"{name}: ({coord.latitude}, {coord.longitude}) is outside the Gulf demo region{hint}"
            )
    return problems


def check_detection(out: DetectionOutput) -> list[str]:
    problems = []
    if not out.image_id:
        problems.append("detection: image_id is empty")
    if out.confidence is not None and not (_is_number(out.confidence) and 0 <= out.confidence <= 1):
        problems.append(f"detection: confidence {out.confidence} must be in [0, 1]")
    if out.oil_coordinates is not None:
        if len(out.oil_coordinates) == 0:
            problems.append("detection: oil_coordinates is an empty tuple; use None when georeferencing is missing")
        for i, c in enumerate(out.oil_coordinates):
            problems += check_coordinate(c, f"detection.oil_coordinates[{i}]")
    return problems


def check_environment(env: EnvironmentalData) -> list[str]:
    problems = []
    for label, dt in (("start_time", env.start_time), ("end_time", env.end_time)):
        if not _is_utc(dt):
            problems.append(f"environment: {label} must be timezone-aware UTC")
    if not problems and env.end_time <= env.start_time:
        problems.append("environment: end_time must be after start_time")
    return problems


def check_drift(out: DriftOutput, tolerance_hours: float = 0.5) -> list[str]:
    problems = check_coordinate(out.initial_location, "drift.initial_location")
    if not _is_number(out.duration_hours) or out.duration_hours <= 0:
        problems.append(f"drift: duration_hours {out.duration_hours} must be positive")
    if len(out.positions) < 2:
        problems.append("drift: need at least two timed positions")
        return problems
    for i, p in enumerate(out.positions):
        if not _is_utc(p.timestamp):
            problems.append(f"drift.positions[{i}]: timestamp must be timezone-aware UTC")
        problems += check_coordinate(p.coordinate, f"drift.positions[{i}]")
    if any("UTC" in p for p in problems):
        return problems
    times = [p.timestamp for p in out.positions]
    if any(b <= a for a, b in zip(times, times[1:])):
        problems.append("drift: timestamps must be strictly increasing")
    span = (times[-1] - times[0]).total_seconds() / 3600
    if _is_number(out.duration_hours) and abs(span - out.duration_hours) > tolerance_hours:
        problems.append(f"drift: positions span {span:.2f} h but duration_hours is {out.duration_hours}")
    return problems


def check_vessel(v: Vessel) -> list[str]:
    problems = check_coordinate(v.location, f"vessel {v.vessel_id}.location")
    for field in ("speed_m_per_s", "capacity_m3", "available_hours"):
        value = getattr(v, field)
        if not _is_number(value) or value <= 0:
            problems.append(f"vessel {v.vessel_id}: {field} {value} must be positive")
    return problems


def check_target(t: ResponseTarget) -> list[str]:
    problems = check_coordinate(t.location, f"target {t.target_id}.location")
    if not _is_number(t.oil_volume_m3) or t.oil_volume_m3 <= 0:
        problems.append(f"target {t.target_id}: oil_volume_m3 {t.oil_volume_m3} must be positive")
    return problems


def check_optimization(out: OptimizationOutput, vessels: list[Vessel], targets: list[ResponseTarget]) -> list[str]:
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
            problems += check_coordinate(c, f"route {r.vessel_id}.coordinates[{i}]")
        hours = r.estimated_travel_hours
        if hours is not None and hours > fleet[r.vessel_id].available_hours:
            problems.append(
                f"route {r.vessel_id}: {hours} h exceeds available_hours {fleet[r.vessel_id].available_hours}"
            )
    return problems


