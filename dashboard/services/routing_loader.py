"""Load routing module outputs from ``outputs/routing/``.

- ``routes.geojson``: one LineString per vessel; properties ``vessel_id``, ``order``
  (list of target IDs in visiting order), ``eta_hours``, optional ``distance_km``,
  ``oil_collected_m3``.
- ``summary.json``: total_time_hours, total_distance_km, oil_collected_m3, vessel_count,
  optional status (optimal / feasible / infeasible / not_solved / error).
- ``targets.geojson`` (optional): target points/areas with ``target_id``, ``oil_volume_m3``.
"""

from __future__ import annotations

from typing import Any

import config
from services.files import as_float, read_geojson, read_json_object
from services.models import RoutingData, VesselRoute


def _parse_order(value: Any) -> list[str]:
    """Accept a list of IDs or a 'T1 > T2 > T3' / 'T1,T2' string."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        separator = ">" if ">" in value else ","
        return [part.strip() for part in value.split(separator) if part.strip()]
    return []


def _line_coordinates(geometry: dict) -> list[list[float]] | None:
    if geometry["type"] == "LineString":
        return geometry["coordinates"]
    if geometry["type"] == "MultiLineString":
        return [pos for line in geometry["coordinates"] for pos in line]
    return None


def load_routing() -> RoutingData | None:
    """Return routing outputs, or None if no routing files exist."""
    data = RoutingData()

    collection, warning = read_geojson(config.ROUTING_FILES["routes"])
    if warning:
        data.warnings.append(warning)
    if collection is not None:
        for i, feature in enumerate(collection["features"]):
            coords = _line_coordinates(feature["geometry"])
            if coords is None:
                data.warnings.append(
                    f"`routes.geojson`: feature {i} is a {feature['geometry']['type']}, expected LineString; skipped."
                )
                continue
            props = feature["properties"]
            data.routes.append(
                VesselRoute(
                    vessel_id=str(props.get("vessel_id", f"vessel-{i + 1}")),
                    coordinates=coords,
                    order=_parse_order(props.get("order")),
                    eta_hours=as_float(props.get("eta_hours", props.get("eta"))),
                    distance_km=as_float(props.get("distance_km")),
                    oil_collected_m3=as_float(props.get("oil_collected_m3")),
                    properties=props,
                )
            )

    data.summary, warning = read_json_object(config.ROUTING_FILES["summary"])
    if warning:
        data.warnings.append(warning)

    data.targets, warning = read_geojson(config.ROUTING_FILES["targets"])
    if warning:
        data.warnings.append(warning)

    if not data.has_content and not data.warnings:
        return None
    return data
