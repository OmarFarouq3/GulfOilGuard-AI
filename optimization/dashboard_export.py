"""Write a plan as the files the dashboard reads (outputs/routing/).

The file layout is the one in dashboard/README.md ("Routing module"), so the Respond page
fills in with no change on the dashboard side:

  routes.geojson   one LineString per vessel that has work: its start, then its stops in
                   visiting order (VesselRoute.coordinates). Idle vessels are left out, so
                   the dashboard's "Vessels deployed" tile counts only working vessels.
  summary.json     OptimizationOutput without its routes: status and message.
  targets.geojson  one Point per ResponseTarget.

Fields marked "extension" are not in shared/schemas.py. The dashboard ignores the ones it
does not know, so they are safe to add and ready for the dashboard to pick up:
  oil_collected_m3   (the dashboard already reads this one) oil the vessel recovers
  cleanup_hours      hours spent cleaning, at the assumed rate in config.py
  finish_hours       sailing + cleanup: when this vessel is done. estimated_travel_hours is
                     sailing only, so "response time" should be the largest finish_hours
  sea_path           [[lon, lat], ...] through water, for drawing the route around land.
                     The LineString itself is only the stops (the dashboard puts a stop
                     marker on every point of it).
  served_by          (targets) the vessel that serves the target, or null

Old files are replaced (or removed) on every export, so the dashboard never mixes a new
summary with old routes.
"""

import json
import os
from pathlib import Path

from optimization.config import DEFAULT_CONFIG, REPO_ROOT, RoutingConfig
from optimization.limits import service_hours
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
) -> list[Path]:
    """Write routes.geojson, summary.json and targets.geojson. Returns the files written.

    `synthetic=True` makes the dashboard label the page "Simulated scenario". Keep it True
    for every made-up scenario. Pass the plan's distance_provider to add sea paths.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    vessels_by_id = {v.vessel_id: v for v in vessels}
    volume_by_id = {t.target_id: t.oil_volume_m3 for t in targets}
    served_by: dict[str, str] = {}

    route_features = []
    idle: list[str] = []
    for route in plan.routes:
        if not route.assigned_target_ids:
            idle.append(route.vessel_id)
            continue
        oil = sum(volume_by_id.get(t, 0.0) for t in route.assigned_target_ids)
        cleanup = sum(service_hours(volume_by_id[t], config) for t in route.assigned_target_ids if t in volume_by_id)
        properties = {
            "vessel_id": route.vessel_id,
            "assigned_target_ids": list(route.assigned_target_ids),
            "estimated_distance_km": route.estimated_distance_km,
            "estimated_travel_hours": route.estimated_travel_hours,
            "oil_collected_m3": oil,
            "cleanup_hours": cleanup,
            "finish_hours": (route.estimated_travel_hours or 0.0) + cleanup,
        }
        vessel = vessels_by_id.get(route.vessel_id)
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
    _write_json(summary_file, {
        "status": plan.status,
        "message": plan.message,
        "synthetic": synthetic,
        "scenario_id": scenario_id,  # extension
        "idle_vessel_ids": idle,  # extension
        "unserved_target_ids": [t.target_id for t in targets if t.target_id not in served_by],  # extension
    })
    written.append(summary_file)

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
                    },
                }
                for t in targets
            ],
        })
        written.append(targets_file)
    else:
        targets_file.unlink(missing_ok=True)
    return written
