"""Load synthetic demo scenarios into the shared dataclasses.

Every scenario file in tests/scenarios/ is synthetic and labelled as such.
Results from these inputs must not be presented as real detections,
drift forecasts or response plans.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from shared.schemas import (
    DriftOutput,
    GeoCoordinate,
    ResponseTarget,
    TimedPosition,
    Vessel,
)

SCENARIO_DIR = Path(__file__).parent / "scenarios"


@dataclass(frozen=True)
class SensitiveSite:
    name: str
    location: GeoCoordinate


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    title: str
    synthetic: bool
    note: str
    release_time: datetime
    release_location: GeoCoordinate
    estimated_oil_volume_m3: float
    drift: DriftOutput
    targets_forecast_time: datetime
    targets_note: str
    targets: tuple[ResponseTarget, ...]
    vessels: tuple[Vessel, ...]
    sensitive_sites: tuple[SensitiveSite, ...]
    expected: str


def _coord(d: dict) -> GeoCoordinate:
    return GeoCoordinate(float(d["latitude"]), float(d["longitude"]))


def _parse_utc(text: str) -> datetime:
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp {text!r} has no timezone")
    return dt.astimezone(timezone.utc)


def load_scenario(path: Path) -> Scenario:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    release_time = _parse_utc(raw["release_time_utc"])
    release = _coord(raw["release_location"])

    drift_raw = raw["synthetic_drift"]
    positions = tuple(
        TimedPosition(release_time + timedelta(hours=p["hours_after_release"]), _coord(p))
        for p in drift_raw["positions"]
    )
    drift = DriftOutput(
        simulation_id=f"{raw['scenario_id']}-synthetic-drift",
        initial_location=release,
        positions=positions,
        duration_hours=float(drift_raw["duration_hours"]),
    )

    # All targets in a scenario are separate patches at one forecast time.
    targets_forecast_time = release_time + timedelta(hours=raw["targets_forecast_hours_after_release"])
    targets = tuple(
        ResponseTarget(t["target_id"], _coord(t), float(t["oil_volume_m3"])) for t in raw["targets"]
    )
    vessels = tuple(
        Vessel(v["vessel_id"], _coord(v), float(v["speed_m_per_s"]),
               float(v["capacity_m3"]), float(v["available_hours"]))
        for v in raw["vessels"]
    )
    sites = tuple(SensitiveSite(s["name"], _coord(s)) for s in raw.get("sensitive_sites", []))

    return Scenario(
        scenario_id=raw["scenario_id"],
        title=raw["title"],
        synthetic=bool(raw["synthetic"]),
        note=raw["note"],
        release_time=release_time,
        release_location=release,
        estimated_oil_volume_m3=float(raw["estimated_oil_volume_m3"]),
        drift=drift,
        targets_forecast_time=targets_forecast_time,
        targets_note=raw["targets_note"],
        targets=targets,
        vessels=vessels,
        sensitive_sites=sites,
        expected=raw["expected"],
    )


def load_all() -> list[Scenario]:
    return [load_scenario(p) for p in sorted(SCENARIO_DIR.glob("*.json"))]
