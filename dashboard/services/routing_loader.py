"""Load routing module outputs from ``outputs/routing/`` and validate them against shared/schemas.py.

- ``routes.geojson``: one LineString per vessel (``VesselRoute``). Properties: ``vessel_id``,
  ``assigned_target_ids`` (visiting order), optional ``estimated_distance_km``,
  ``estimated_travel_hours``; optional ``Vessel`` fields ``speed_m_per_s``, ``capacity_m3``,
  ``available_hours``; extension ``oil_collected_m3`` (not in schema).
- ``summary.json``: ``OptimizationOutput`` without routes: ``status`` (required), ``message``.
- ``targets.geojson`` (optional): Point features (``ResponseTarget``) with ``target_id`` and
  ``oil_volume_m3``; extension ``source_hours`` (not in schema).
"""

from __future__ import annotations

from typing import Any

import config
from services import schema
from services.files import read_geojson, read_json_object, validate_geojson
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


def load_routing() -> RoutingData | None:
    """Return routing outputs, or None if no routing files exist."""
    data = RoutingData()

    collection, warning = read_geojson(config.ROUTING_FILES["routes"])
    if warning:
        data.warnings.append(warning)
    parse_routes(collection, data)

    summary, warning = read_json_object(config.ROUTING_FILES["summary"])
    if warning:
        data.warnings.append(warning)
    parse_summary(summary, data)

    collection, warning = read_geojson(config.ROUTING_FILES["targets"])
    if warning:
        data.warnings.append(warning)
    parse_targets(collection, data)

    if not data.has_content and not data.warnings:
        return None
    return data
