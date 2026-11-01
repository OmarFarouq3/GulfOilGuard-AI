"""Read scenario files and save plans.

The JSON uses the SAME field names as shared/schemas.py, so a scenario file maps
straight onto Vessel and ResponseTarget, and a saved plan is just an
OptimizationOutput written as JSON.
"""

import json
from dataclasses import asdict
from pathlib import Path

from shared.schemas import (
    GeoCoordinate,
    OptimizationOutput,
    ResponseTarget,
    Vessel,
    VesselRoute,
)


def _coordinate(data: dict, where: str) -> GeoCoordinate:
    try:
        return GeoCoordinate(
            latitude=float(data["latitude"]), longitude=float(data["longitude"])
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{where}: needs numeric 'latitude' and 'longitude'") from exc


def load_scenario(
    path: str | Path,
) -> tuple[str, tuple[Vessel, ...], tuple[ResponseTarget, ...]]:
    """Return (scenario_id, vessels, targets)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    vessels: list[Vessel] = []
    targets: list[ResponseTarget] = []
    try:
        for item in data["vessels"]:
            vessels.append(
                Vessel(
                    vessel_id=str(item["vessel_id"]),
                    location=_coordinate(
                        item["location"], f"vessel {item['vessel_id']}"
                    ),
                    speed_m_per_s=float(item["speed_m_per_s"]),
                    capacity_m3=float(item["capacity_m3"]),
                    available_hours=float(item["available_hours"]),
                )
            )
        for item in data["targets"]:
            targets.append(
                ResponseTarget(
                    target_id=str(item["target_id"]),
                    location=_coordinate(
                        item["location"], f"target {item['target_id']}"
                    ),
                    oil_volume_m3=float(item["oil_volume_m3"]),
                )
            )
    except KeyError as exc:
        raise ValueError(f"scenario file is missing the field {exc}") from exc
    return str(data.get("scenario_id", Path(path).stem)), tuple(vessels), tuple(targets)


def save_plan(plan: OptimizationOutput, path: str | Path) -> None:
    Path(path).write_text(json.dumps(asdict(plan), indent=2), encoding="utf-8")


def load_plan(path: str | Path) -> OptimizationOutput:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    routes = tuple(
        VesselRoute(
            vessel_id=r["vessel_id"],
            assigned_target_ids=tuple(r["assigned_target_ids"]),
            coordinates=tuple(
                _coordinate(c, "route coordinate") for c in r["coordinates"]
            ),
            estimated_distance_km=r.get("estimated_distance_km"),
            estimated_travel_hours=r.get("estimated_travel_hours"),
        )
        for r in data["routes"]
    )
    return OptimizationOutput(
        routes=routes, status=data["status"], message=data.get("message")
    )
