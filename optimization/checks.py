"""Rule checks. Both our plan and the baseline must pass the same checks."""

from math import isfinite

from shared.schemas import GeoCoordinate, OptimizationOutput, ResponseTarget, Vessel


def _bad_coordinate(c: GeoCoordinate) -> bool:
    return (
        not (isfinite(c.latitude) and isfinite(c.longitude))
        or not -90 <= c.latitude <= 90
        or not -180 <= c.longitude <= 180
    )


def validate_inputs(
    vessels: tuple[Vessel, ...], targets: tuple[ResponseTarget, ...]
) -> list[str]:
    """Return a list of problems. An empty list means the input is usable."""
    problems: list[str] = []

    vessel_ids = [v.vessel_id for v in vessels]
    if len(set(vessel_ids)) != len(vessel_ids):
        problems.append("duplicate vessel_id")
    target_ids = [t.target_id for t in targets]
    if len(set(target_ids)) != len(target_ids):
        problems.append("duplicate target_id")

    for v in vessels:
        if not v.vessel_id:
            problems.append("vessel with empty vessel_id")
        if _bad_coordinate(v.location):
            problems.append(f"vessel {v.vessel_id}: bad coordinate")
        if not (isfinite(v.speed_m_per_s) and v.speed_m_per_s > 0):
            problems.append(f"vessel {v.vessel_id}: speed must be above 0")
        if not (isfinite(v.capacity_m3) and v.capacity_m3 > 0):
            problems.append(f"vessel {v.vessel_id}: capacity must be above 0")
        if not (isfinite(v.available_hours) and v.available_hours >= 0):
            problems.append(f"vessel {v.vessel_id}: available_hours must be 0 or more")

    for t in targets:
        if not t.target_id:
            problems.append("target with empty target_id")
        if _bad_coordinate(t.location):
            problems.append(f"target {t.target_id}: bad coordinate")
        if not (isfinite(t.oil_volume_m3) and t.oil_volume_m3 > 0):
            problems.append(f"target {t.target_id}: oil volume must be above 0")

    return problems


def check_plan(
    plan: OptimizationOutput,
    vessels: tuple[Vessel, ...],
    targets: tuple[ResponseTarget, ...],
) -> list[str]:
    """Return a list of rule violations in a plan. An empty list means it is valid.

    Phase 1 checks: known ids, no target served twice, capacity, route shape.
    Phase 3 will add the working-hours check.
    """
    violations: list[str] = []
    vessels_by_id = {v.vessel_id: v for v in vessels}
    volume_by_id = {t.target_id: t.oil_volume_m3 for t in targets}
    seen_targets: set[str] = set()
    seen_vessels: set[str] = set()

    for route in plan.routes:
        vessel = vessels_by_id.get(route.vessel_id)
        if vessel is None:
            violations.append(f"unknown vessel {route.vessel_id}")
            continue
        if route.vessel_id in seen_vessels:
            violations.append(f"vessel {route.vessel_id} has two routes")
        seen_vessels.add(route.vessel_id)

        load = 0.0
        for target_id in route.assigned_target_ids:
            if target_id not in volume_by_id:
                violations.append(f"unknown target {target_id}")
                continue
            if target_id in seen_targets:
                violations.append(f"target {target_id} served twice")
            seen_targets.add(target_id)
            load += volume_by_id[target_id]

        if load > vessel.capacity_m3 + 1e-9:
            violations.append(
                f"vessel {route.vessel_id} over capacity: {load} > {vessel.capacity_m3}"
            )
        if len(route.coordinates) != 1 + len(route.assigned_target_ids):
            violations.append(
                f"vessel {route.vessel_id}: coordinates do not match stops"
            )
        for value in (route.estimated_distance_km, route.estimated_travel_hours):
            if value is not None and value < 0:
                violations.append(
                    f"vessel {route.vessel_id}: negative distance or time"
                )

    return violations
