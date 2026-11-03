"""Write a plan as the files the dashboard reads (outputs/routing/).

The file layout is the one in dashboard/README.md ("Routing module"), so the Respond page
fills in with no change on the dashboard side:

  routes.geojson   one LineString per vessel that has work: its start, then its stops in
                   visiting order, then its start again: the vessel sails back to the port it
                   started from (VesselRoute.coordinates). Idle vessels are left out, so
                   the dashboard's "Vessels deployed" tile counts only working vessels.
  summary.json     OptimizationOutput without its routes: status and message.
  targets.geojson  one Point per ResponseTarget.

Fields marked "extension" are not in shared/schemas.py. The dashboard ignores the ones it
does not know, so they are safe to add and ready for the dashboard to pick up:
  oil_collected_m3   (the dashboard already reads this one) pure oil the vessel recovers
  emulsion_collected_m3, tank_used_percent
                     (routes, when the targets know their emulsion) what the vessel takes on:
                     oil plus the water mixed into it, and how full that leaves its tank
  emulsion_m3, water_fraction
                     (targets, same condition) the patch's emulsion when the vessel meets it
  cleanup_hours      hours spent cleaning (skimming the emulsion when known), at the assumed
                     rate in config.py
  finish_hours       sailing + cleanup: when this vessel is back in port. estimated_travel_hours
                     is sailing only (the trip back included), so "response time" should be
                     the largest finish_hours
  sea_path           [[lon, lat], ...] through water, for drawing the route around land.
                     The LineString itself is only the stops (the dashboard puts a stop
                     marker on every point of it).
  served_by          (targets) the vessel that serves the target, or null
  source_hours       (targets, and summary) the drift forecast step whose oil layer fits
                     these targets best. The dashboard already reads it.
  meet_hours, ...    (targets) anything passed in `target_properties`, e.g. for moving oil
                     the time the vessel meets the patch

Next to them (the dashboard does not read these yet):
  comparison.json    export_comparison: optimized vs baseline, metrics from evaluate_routes,
                     each plan's assignments and rule check, plus any extra details (drift)
  baseline/          the baseline plan as the same three files (export_for_dashboard into
                     the sub-folder), ready for a toggle

Old files are replaced (or removed) on every export, so the dashboard never mixes a new
summary with old routes.
"""

import json
import os
from math import isnan
from pathlib import Path

from optimization.checks import check_plan
from optimization.config import DEFAULT_CONFIG, REPO_ROOT, RoutingConfig
from optimization.evaluate_routes import evaluate_routes
from optimization.limits import EmulsionTarget, service_hours, tank_m3
from shared.schemas import GeoCoordinate, OptimizationOutput, ResponseTarget, Vessel

DEFAULT_DIR = REPO_ROOT / "outputs" / "routing"


def _lon_lat(point: GeoCoordinate) -> list[float]:
    return [point.longitude, point.latitude]  # GeoJSON order


def _sea_path(provider, coordinates) -> list[list[float]] | None:
    """The water path through all stops, or None if this provider cannot draw one."""
    if not hasattr(provider, "path"):
        return None  # straight-line provider: nothing better than the stops themselves
    try:
        points: list[GeoCoordinate] = [coordinates[0]]
        for a, b in zip(coordinates, coordinates[1:]):
            points.extend(provider.path(a, b)[1:])
        return [_lon_lat(p) for p in points]
    except ValueError:  # SeaRoutingError: leave the extension out rather than fail the export
        return None


def _write_json(path: Path, content: dict) -> None:
    """Write via a temporary file, so the dashboard never reads a half-written file."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(content, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def export_for_dashboard(
    plan: OptimizationOutput,
    vessels: tuple[Vessel, ...],
    targets: tuple[ResponseTarget, ...],
    out_dir: str | Path = DEFAULT_DIR,
    *,
    scenario_id: str | None = None,
    synthetic: bool = True,
    config: RoutingConfig = DEFAULT_CONFIG,
    distance_provider=None,
    source_hours: float | None = None,
    target_properties: dict[str, dict] | None = None,
) -> list[Path]:
    """Write routes.geojson, summary.json and targets.geojson. Returns the files written.

    `synthetic=True` makes the dashboard label the page "Simulated scenario". Keep it True
    for every made-up scenario. Pass the plan's distance_provider to add sea paths,
    `source_hours` when the targets come from a drift forecast, and `target_properties`
    ({target_id: {name: value}}) for extra per-target fields.
    """
    target_properties = target_properties or {}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    vessels_by_id = {v.vessel_id: v for v in vessels}
    targets_by_id = {t.target_id: t for t in targets}
    served_by: dict[str, str] = {}

    route_features = []
    idle: list[str] = []
    for route in plan.routes:
        if not route.assigned_target_ids:
            idle.append(route.vessel_id)
            continue
        served = [targets_by_id[t] for t in route.assigned_target_ids if t in targets_by_id]
        load = sum(tank_m3(t) for t in served)
        cleanup = service_hours(load, config)
        properties = {
            "vessel_id": route.vessel_id,
            "assigned_target_ids": list(route.assigned_target_ids),
            "estimated_distance_km": route.estimated_distance_km,
            "estimated_travel_hours": route.estimated_travel_hours,
            "oil_collected_m3": sum(t.oil_volume_m3 for t in served),
            "cleanup_hours": cleanup,
            "finish_hours": (route.estimated_travel_hours or 0.0) + cleanup,
        }
        vessel = vessels_by_id.get(route.vessel_id)
        if any(isinstance(t, EmulsionTarget) for t in served):
            properties["emulsion_collected_m3"] = load
            if vessel is not None:
                properties["tank_used_percent"] = 100 * load / vessel.capacity_m3
        if vessel is not None:  # the dashboard wants all three or none
            properties["speed_m_per_s"] = vessel.speed_m_per_s
            properties["capacity_m3"] = vessel.capacity_m3
            properties["available_hours"] = vessel.available_hours
        sea_path = _sea_path(distance_provider, route.coordinates)
        if sea_path is not None:
            properties["sea_path"] = sea_path
        route_features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [_lon_lat(c) for c in route.coordinates]},
            "properties": properties,
        })
        for target_id in route.assigned_target_ids:
            served_by[target_id] = route.vessel_id

    written: list[Path] = []
    routes_file = out / "routes.geojson"
    if route_features:
        _write_json(routes_file, {"type": "FeatureCollection", "features": route_features})
        written.append(routes_file)
    else:
        routes_file.unlink(missing_ok=True)  # an empty collection shows as a broken file

    summary_file = out / "summary.json"
    summary = {
        "status": plan.status,
        "message": plan.message,
        "synthetic": synthetic,
        "scenario_id": scenario_id,  # extension
        "idle_vessel_ids": idle,  # extension
        "unserved_target_ids": [t.target_id for t in targets if t.target_id not in served_by],  # extension
    }
    if source_hours is not None:
        summary["source_hours"] = source_hours  # extension
    _write_json(summary_file, summary)
    written.append(summary_file)

    extra = {} if source_hours is None else {"source_hours": source_hours}
    targets_file = out / "targets.geojson"
    if targets:
        _write_json(targets_file, {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": _lon_lat(t.location)},
                    "properties": {
                        "target_id": t.target_id,
                        "oil_volume_m3": t.oil_volume_m3,
                        "served_by": served_by.get(t.target_id),
                        **({"emulsion_m3": t.emulsion_m3, "water_fraction": t.water_fraction}
                           if isinstance(t, EmulsionTarget) else {}),
                        **extra,
                        **target_properties.get(t.target_id, {}),
                    },
                }
                for t in targets
            ],
        })
        written.append(targets_file)
    else:
        targets_file.unlink(missing_ok=True)
    return written


def _plan_record(plan: OptimizationOutput, vessels, targets, config) -> dict:
    return {
        "status": plan.status,
        "message": plan.message,
        "assignments": {r.vessel_id: list(r.assigned_target_ids) for r in plan.routes},
        "rule_violations": check_plan(plan, vessels, targets, config),
    }


def export_comparison(
    plan: OptimizationOutput,
    baseline: OptimizationOutput,
    vessels: tuple[Vessel, ...],
    targets: tuple[ResponseTarget, ...],
    out_dir: str | Path = DEFAULT_DIR,
    *,
    scenario_id: str | None = None,
    synthetic: bool = True,
    config: RoutingConfig = DEFAULT_CONFIG,
    baseline_targets: tuple[ResponseTarget, ...] | None = None,
    details: dict | None = None,
) -> Path:
    """Write comparison.json and return its path.

    Both plans must come from the same vessels, oil and distance provider (see
    evaluate_routes.py). When the oil moves, pass each plan's own targets as met
    (`baseline_targets` for the baseline). `details` is added as is, e.g. the drift.
    Write the baseline's own map files with export_for_dashboard(..., out_dir / "baseline").
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    baseline_targets = baseline_targets or targets
    content = {
        "scenario_id": scenario_id,
        "synthetic": synthetic,
        "optimized": _plan_record(plan, vessels, targets, config),
        "baseline": _plan_record(baseline, vessels, baseline_targets, config),
    }
    try:
        metrics = evaluate_routes(plan, baseline, targets, config, baseline_targets=baseline_targets)
        # JSON has no NaN (distance per target when a plan covers nothing)
        content["metrics"] = {k: None if isnan(v) else v for k, v in metrics.items()}
    except ValueError as exc:  # one plan failed: say why instead of leaving old numbers
        content["metrics"] = None
        content["metrics_error"] = str(exc)
    content |= details or {}
    comparison_file = out / "comparison.json"
    _write_json(comparison_file, content)
    return comparison_file
