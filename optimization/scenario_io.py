"""Read scenario files and save plans.

The JSON uses the SAME field names as shared/schemas.py, so a scenario file maps
straight onto Vessel and ResponseTarget, and a saved plan is just an
OptimizationOutput written as JSON.

Both team scenario formats load:
  - Nihal's (optimization/fixtures/): "location": {"latitude": .., "longitude": ..}
    and "scenario_name"
  - Maria's (tests/scenarios/): "latitude" and "longitude" directly on each vessel
    and target, "scenario_id" and "synthetic"
Extra fields (summary, drift, sensitive_sites, notes) are ignored here.
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


def _location(item: dict, where: str) -> GeoCoordinate:
    """A nested "location" object, or latitude/longitude directly on the item."""
    return _coordinate(item.get("location", item), where)


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
                    location=_location(item, f"vessel {item['vessel_id']}"),
                    speed_m_per_s=float(item["speed_m_per_s"]),
                    capacity_m3=float(item["capacity_m3"]),
                    available_hours=float(item["available_hours"]),
                )
            )
        for item in data["targets"]:
            targets.append(
                ResponseTarget(
                    target_id=str(item["target_id"]),
                    location=_location(item, f"target {item['target_id']}"),
                    oil_volume_m3=float(item["oil_volume_m3"]),
                )
            )
    except KeyError as exc:
        raise ValueError(f"scenario file is missing the field {exc}") from exc
    scenario_id = data.get("scenario_id") or data.get("scenario_name") or Path(path).stem
    return str(scenario_id), tuple(vessels), tuple(targets)


def scenario_is_synthetic(path: str | Path) -> bool:
    """True unless the file says "synthetic": false.

    Every scenario we have today is made up, so a file has to say otherwise on purpose.
    The dashboard uses this to label the plan as a simulated scenario.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get("synthetic") is not False


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
