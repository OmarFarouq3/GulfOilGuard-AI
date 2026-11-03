"""Load routing module outputs from ``outputs/routing/`` and validate them against shared/schemas.py.

- ``routes.geojson``: one LineString per vessel (``VesselRoute``). Properties: ``vessel_id``,
  ``assigned_target_ids`` (visiting order), optional ``estimated_distance_km``,
  ``estimated_travel_hours``; optional ``Vessel`` fields ``speed_m_per_s``, ``capacity_m3``,
  ``available_hours``; extension ``oil_collected_m3`` (not in schema).
- ``summary.json``: ``OptimizationOutput`` without routes: ``status`` (required), ``message``.
- ``targets.geojson`` (optional): Point features (``ResponseTarget``) with ``target_id`` and
  ``oil_volume_m3``; extension ``source_hours`` (not in schema).

Extensions from optimization/dashboard_export.py, all optional (not in schema): ``sea_path``
(routes: [[lon, lat], ...] around land), ``served_by``, ``meet_hours``, ``position_hours``
(targets), ``unserved_target_ids``, ``idle_vessel_ids``, ``scenario_id`` (summary).
``comparison.json`` (optimised vs baseline metrics) is read by ``load_comparison``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import config
from services import schema
from services.files import as_float, read_geojson, read_json_object, validate_geojson
from services.models import RouteEntry, RoutingData


def _is_synthetic(*sources: Any) -> bool:
    return any(isinstance(s, dict) and s.get("synthetic") is True for s in sources)


def parse_routes(collection: dict | None, data: RoutingData, name: str = "routes.geojson") -> None:
    """Validate route features into VesselRoute (+ Vessel) and append them to ``data``."""
    if collection is None:
        return
    seen: set[str] = set()
    for i, feature in enumerate(collection["features"]):
        geometry, props = feature["geometry"], feature["properties"]
        data.synthetic |= _is_synthetic(props)
        if geometry["type"] != "LineString":
            data.warnings.append(f"`{name}` feature {i}: {geometry['type']} is not a LineString; skipped.")
            continue
        try:
            route = schema.vessel_route(props, geometry["coordinates"])
            vessel = schema.vessel(props, route.coordinates[0])
            collected = schema.number(props.get("oil_collected_m3"), "oil_collected_m3")
        except schema.SchemaError as exc:
            data.warnings.append(f"`{name}` feature {i}: {exc}; skipped.")
            continue
        if route.vessel_id in seen:
            data.warnings.append(f"`{name}` feature {i}: duplicate vessel_id {route.vessel_id!r}; skipped.")
            continue
        seen.add(route.vessel_id)
        if vessel and collected is not None and collected > vessel.capacity_m3:
            data.warnings.append(f"`{name}` {route.vessel_id}: oil_collected_m3 {collected} exceeds capacity_m3 "
                                 f"{vessel.capacity_m3}.")
        if vessel and route.estimated_travel_hours is not None and route.estimated_travel_hours > vessel.available_hours:
            data.warnings.append(f"`{name}` {route.vessel_id}: estimated_travel_hours exceeds available_hours.")
        data.routes.append(RouteEntry(route=route, vessel=vessel, oil_collected_m3=collected))
        path = props.get("sea_path")
        if path is not None:
            try:
                data.route_paths[route.vessel_id] = [(p.latitude, p.longitude) for p in map(schema.geo, path)]
            except (schema.SchemaError, TypeError) as exc:
                data.warnings.append(f"`{name}` {route.vessel_id}: sea_path ignored ({exc}).")


def parse_summary(summary: dict | None, data: RoutingData, name: str = "summary.json") -> None:
    """Validate the OptimizationOutput status and message."""
    if summary is None:
        return
    data.synthetic |= _is_synthetic(summary)
    try:
        data.status = schema.solver_status(summary.get("status"))
    except schema.SchemaError as exc:
        data.warnings.append(f"`{name}`: {exc}.")
    message = summary.get("message")
    if message is not None and not isinstance(message, str):
        data.warnings.append(f"`{name}`: `message` must be a string or null.")
    else:
        data.message = message
    for key in ("unserved_target_ids", "idle_vessel_ids"):
        value = summary.get(key)
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            setattr(data, key, list(value))
        elif value is not None:
            data.warnings.append(f"`{name}`: `{key}` must be a list of ids; ignored.")
    if isinstance(summary.get("scenario_id"), str):
        data.scenario_id = summary["scenario_id"]


def parse_targets(collection: dict | None, data: RoutingData, name: str = "targets.geojson") -> None:
    """Validate target features into ResponseTarget and cross-check route assignments."""
    if collection is not None:
        seen: set[str] = set()
        for i, feature in enumerate(collection["features"]):
            props = feature["properties"]
            data.synthetic |= _is_synthetic(props)
            try:
                target = schema.response_target(props, feature["geometry"])
            except schema.SchemaError as exc:
                data.warnings.append(f"`{name}` feature {i}: {exc}; skipped.")
                continue
            if target.target_id in seen:
                data.warnings.append(f"`{name}` feature {i}: duplicate target_id {target.target_id!r}; skipped.")
                continue
            seen.add(target.target_id)
            data.targets.append(target)
            info = {"served_by": props["served_by"]} if isinstance(props.get("served_by"), str) else {}
            for key in ("meet_hours", "position_hours"):
                hours = as_float(props.get(key))
                if hours is not None and hours >= 0:
                    info[key] = hours
            data.target_info[target.target_id] = info
            source = props.get("source_hours")
            if source is not None:
                try:
                    data.target_source_hours = schema.number(source, "source_hours")
                except schema.SchemaError as exc:
                    data.warnings.append(f"`{name}` feature {i}: {exc}.")
    if data.targets:
        known = {t.target_id for t in data.targets}
        for entry in data.routes:
            missing = [t for t in entry.route.assigned_target_ids if t not in known]
            if missing:
                data.warnings.append(f"{entry.route.vessel_id}: assigned_target_ids not found in targets: {missing}.")


COMPARISON_PLANS = ("optimized", "baseline")


def load_comparison(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """comparison.json (optimisation/dashboard_export.export_comparison): (content, warnings).

    Only finite numbers are kept in ``metrics`` and lists of ids in each plan's ``assignments``;
    anything else is dropped with a warning. None when the file is missing or unusable.
    """
    raw, warning = read_json_object(path)
    if raw is None:
        return None, [warning] if warning else []
    warnings, metrics = [], {}
    for key, value in (raw.get("metrics") or {}).items():
        number = as_float(value)
        if number is None and value is not None:
            warnings.append(f"`comparison.json`: metric `{key}` is not a number; ignored.")
        elif number is not None:
            metrics[key] = number
    plans = {}
    for plan in COMPARISON_PLANS:
        assignments = (raw.get(plan) or {}).get("assignments")
        if isinstance(assignments, dict) and all(isinstance(v, list) for v in assignments.values()):
            plans[plan] = {str(k): [str(t) for t in v] for k, v in assignments.items()}
        elif plan in raw:
            warnings.append(f"`comparison.json`: `{plan}.assignments` should map vessel ids to target lists.")
    drift = raw.get("drift") if isinstance(raw.get("drift"), dict) else {}
    return {"scenario_id": raw.get("scenario_id"), "fleet": raw.get("fleet"), "metrics": metrics,
            "assignments": plans, "dispatch_hours": as_float(drift.get("dispatch_hours")),
            "dispatch_time": drift.get("dispatch_time") if isinstance(drift.get("dispatch_time"), str) else None}, warnings


def build_routing(routes: Any, summary: Any, targets: Any) -> RoutingData:
    """Validate already-parsed routing objects (used for demo data)."""
    data = RoutingData()
    collection, warning = validate_geojson(routes, "routes")
    data.warnings += [warning] if warning else []
    parse_routes(collection, data)
    parse_summary(summary, data)
    collection, warning = validate_geojson(targets, "targets")
    data.warnings += [warning] if warning else []
    parse_targets(collection, data)  # after routes: cross-checks assigned_target_ids
    return data


def load_routing(files: dict[str, Path] | None = None) -> RoutingData | None:
    """Return routing outputs, or None if no routing files exist.

    ``files`` is a config.ROUTING_FILES-style dict (e.g. ``config.site_files(id)["routing"]``);
    None reads outputs/routing.
    """
    files = files or config.ROUTING_FILES
    data = RoutingData()

    collection, warning = read_geojson(files["routes"])
    if warning:
        data.warnings.append(warning)
    parse_routes(collection, data)

    summary, warning = read_json_object(files["summary"])
    if warning:
        data.warnings.append(warning)
    parse_summary(summary, data)

    collection, warning = read_geojson(files["targets"])
    if warning:
        data.warnings.append(warning)
    parse_targets(collection, data)

    if not data.has_content and not data.warnings:
        return None
    return data
