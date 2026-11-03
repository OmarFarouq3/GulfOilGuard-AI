"""Simulated scenarios, vessels, response targets, and marine metrics for cleanup optimization.

Provides regional Arabian Gulf infrastructure (depots, distances, drift aggregation)
alongside focused demonstration scenarios for Ras Al Khaimah (RAK) coastal waters
to align with team drift simulations.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from shared.schemas import DriftOutput, GeoCoordinate, ResponseTarget, TimedPosition, Vessel

# Conversion helpers
KNOTS_TO_M_PER_S = 0.514444
M_PER_S_TO_KNOTS = 1.0 / KNOTS_TO_M_PER_S
EARTH_RADIUS_KM = 6371.0088

# Representative Regional Ports & Marine Staging Depots across the Arabian Gulf (WGS84)
GULF_DEPOTS = {
    # Northern Emirates / RAK demonstration bases. Vessels start and end here, so the two
    # demo bases are their harbour entrances (gap between the breakwaters, from OpenStreetMap),
    # not points on the quayside roads, which the routing sea grid treats as land.
    "port_saqr_rak": GeoCoordinate(latitude=25.9810, longitude=56.0482),      # Primary RAK deepwater port (entrance)
    "rak_maritime_city": GeoCoordinate(latitude=25.9050, longitude=55.9900),  # RAK maritime facility
    "hamriyah_sharjah": GeoCoordinate(latitude=25.4773, longitude=55.4798),   # Regional backup base (entrance)
    # Wider Arabian Gulf staging bases
    "jebel_ali_dubai": GeoCoordinate(latitude=25.0110, longitude=55.0610),
    "mina_zayed_abu_dhabi": GeoCoordinate(latitude=24.5260, longitude=54.3750),
    "ras_laffan_qatar": GeoCoordinate(latitude=25.9180, longitude=51.5510),
    "jubail_saudi": GeoCoordinate(latitude=27.0110, longitude=49.6580),
    "ras_tanura_saudi": GeoCoordinate(latitude=26.6430, longitude=50.1590),
}


def haversine_distance_km(coord1: GeoCoordinate, coord2: GeoCoordinate) -> float:
    """Calculate great-circle distance between two WGS84 coordinates in kilometres."""
    lat1_rad = math.radians(coord1.latitude)
    lon1_rad = math.radians(coord1.longitude)
    lat2_rad = math.radians(coord2.latitude)
    lon2_rad = math.radians(coord2.longitude)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_KM * c


def compute_travel_time_hours(distance_km: float, speed_m_per_s: float) -> float:
    """Calculate travel time in hours given distance in km and speed in m/s."""
    if speed_m_per_s <= 0:
        raise ValueError("Vessel speed must be strictly positive.")
    speed_km_per_h = speed_m_per_s * 3.6
    return distance_km / speed_km_per_h


def build_distance_matrix(locations: Sequence[GeoCoordinate]) -> list[list[float]]:
    """Build an NxN symmetric distance matrix in kilometres between all coordinates."""
    n = len(locations)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            dist = haversine_distance_km(locations[i], locations[j])
            matrix[i][j] = round(dist, 3)
            matrix[j][i] = round(dist, 3)
    return matrix


def build_time_matrix(
    locations: Sequence[GeoCoordinate],
    speed_m_per_s: float,
    service_times_hours: Sequence[float] | None = None,
) -> list[list[float]]:
    """Build an NxN travel + service time matrix in hours for a specific vessel speed."""
    n = len(locations)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                matrix[i][j] = 0.0
            else:
                dist = haversine_distance_km(locations[i], locations[j])
                travel_h = compute_travel_time_hours(dist, speed_m_per_s)
                service_h = service_times_hours[j] if service_times_hours else 0.0
                matrix[i][j] = round(travel_h + service_h, 3)
    return matrix


# --- Scenario Generators: Ras Al Khaimah (RAK) Demonstration Focus ---


def create_smoke_test_scenario() -> tuple[tuple[Vessel, ...], tuple[ResponseTarget, ...]]:
    """Minimal scenario (2 vessels, 4 targets) for fast solver debugging.

    Staged at Port Saqr (Ras Al Khaimah) with targets located in coastal waters.
    """
    vessels = (
        Vessel(
            vessel_id="RAK-FAST-01",
            location=GULF_DEPOTS["port_saqr_rak"],
            speed_m_per_s=round(20.0 * KNOTS_TO_M_PER_S, 2),  # ~10.29 m/s (~20 kn)
            capacity_m3=50.0,
            available_hours=8.0,
        ),
        Vessel(
            vessel_id="RAK-OSRV-01",
            location=GULF_DEPOTS["port_saqr_rak"],
            speed_m_per_s=round(14.0 * KNOTS_TO_M_PER_S, 2),  # ~7.20 m/s (~14 kn)
            capacity_m3=200.0,
            available_hours=12.0,
        ),
    )

    targets = (
        ResponseTarget(
            target_id="RAK-TGT-01",
            location=GeoCoordinate(latitude=25.9200, longitude=55.9500),  # ~12 km offshore RAK
            oil_volume_m3=25.0,
        ),
        ResponseTarget(
            target_id="RAK-TGT-02",
            location=GeoCoordinate(latitude=25.9600, longitude=55.9200),  # ~15 km offshore RAK
            oil_volume_m3=35.0,
        ),
        ResponseTarget(
            target_id="RAK-TGT-03",
            location=GeoCoordinate(latitude=26.0100, longitude=55.9400),  # Northern offshore
            oil_volume_m3=40.0,
        ),
        ResponseTarget(
            target_id="RAK-TGT-04",
            location=GeoCoordinate(latitude=26.0400, longitude=55.9900),  # Near Port Saqr approach
            oil_volume_m3=20.0,
        ),
    )

    return vessels, targets


def create_rak_standard_scenario() -> tuple[tuple[Vessel, ...], tuple[ResponseTarget, ...]]:
    """Standard operational scenario for a Ras Al Khaimah (RAK) oil spill demo.

    Features:
    - 2 vessels stationed at Port Saqr (RAK)
    - 1 regional backup vessel staged at Hamriyah (Sharjah)
    - 10 clustered response targets representing an oil slick drifting in RAK waters
      towards the northern coastline and shipping corridor.
    """
    vessels = (
        Vessel(
            vessel_id="RAK-FRV-FALCON",
            location=GULF_DEPOTS["port_saqr_rak"],
            speed_m_per_s=round(22.0 * KNOTS_TO_M_PER_S, 2),  # ~11.32 m/s
            capacity_m3=60.0,
            available_hours=10.0,
        ),
        Vessel(
            vessel_id="RAK-OSRV-SAQR",
            location=GULF_DEPOTS["port_saqr_rak"],
            speed_m_per_s=round(15.0 * KNOTS_TO_M_PER_S, 2),  # ~7.72 m/s
            capacity_m3=250.0,
            available_hours=16.0,
        ),
        Vessel(
            vessel_id="HAMRIYAH-OSRV-RESERVE",
            location=GULF_DEPOTS["hamriyah_sharjah"],
            speed_m_per_s=round(14.0 * KNOTS_TO_M_PER_S, 2),  # ~7.20 m/s
            capacity_m3=300.0,
            available_hours=20.0,
        ),
    )

    # 10 targets drifting along RAK coastal/offshore waters (lat 25.84 - 26.08, lon 55.82 - 55.96)
    targets = (
        ResponseTarget(
            target_id="RAK-SPILL-01",
            location=GeoCoordinate(latitude=25.8400, longitude=55.8200),
            oil_volume_m3=45.0,
        ),
        ResponseTarget(
            target_id="RAK-SPILL-02",
            location=GeoCoordinate(latitude=25.8700, longitude=55.8500),
            oil_volume_m3=30.0,
        ),
        ResponseTarget(
            target_id="RAK-SPILL-03",
            location=GeoCoordinate(latitude=25.9000, longitude=55.8300),
            oil_volume_m3=55.0,
        ),
        ResponseTarget(
            target_id="RAK-SPILL-04",
            location=GeoCoordinate(latitude=25.9300, longitude=55.8800),
            oil_volume_m3=25.0,
        ),
        ResponseTarget(
            target_id="RAK-SPILL-05",
            location=GeoCoordinate(latitude=25.9500, longitude=55.8400),
            oil_volume_m3=60.0,
        ),
        ResponseTarget(
            target_id="RAK-SPILL-06",
            location=GeoCoordinate(latitude=25.9800, longitude=55.9100),
            oil_volume_m3=40.0,
        ),
        ResponseTarget(
            target_id="RAK-SPILL-07",
            location=GeoCoordinate(latitude=26.0000, longitude=55.8700),
            oil_volume_m3=35.0,
        ),
        ResponseTarget(
            target_id="RAK-SPILL-08",
            location=GeoCoordinate(latitude=26.0300, longitude=55.9300),
            oil_volume_m3=50.0,
        ),
        ResponseTarget(
            target_id="RAK-SPILL-09",
            location=GeoCoordinate(latitude=26.0500, longitude=55.9000),
            oil_volume_m3=70.0,
        ),
        ResponseTarget(
            target_id="RAK-SPILL-10",
            location=GeoCoordinate(latitude=26.0800, longitude=55.9600),
            oil_volume_m3=40.0,
        ),
    )

    return vessels, targets


# Alias for backward compatibility with existing tests and fixtures
create_gulf_standard_scenario = create_rak_standard_scenario


def create_constrained_triage_scenario() -> tuple[tuple[Vessel, ...], tuple[ResponseTarget, ...]]:
    """Resource-constrained scenario in RAK where total spill volume exceeds fleet capacity.

    Fleet total capacity: 150 m3. Total spill demand: 380 m3.
    Used to test solver priority penalty, partial fulfillment, or infeasibility detection.
    """
    vessels = (
        Vessel(
            vessel_id="RAK-SCOUT-01",
            location=GULF_DEPOTS["port_saqr_rak"],
            speed_m_per_s=round(18.0 * KNOTS_TO_M_PER_S, 2),
            capacity_m3=50.0,
            available_hours=6.0,
        ),
        Vessel(
            vessel_id="RAK-SKIMMER-01",
            location=GULF_DEPOTS["port_saqr_rak"],
            speed_m_per_s=round(12.0 * KNOTS_TO_M_PER_S, 2),
            capacity_m3=100.0,
            available_hours=8.0,
        ),
    )

    targets = (
        ResponseTarget(
            target_id="RAK-PRIORITY-PORT-APPROACH",
            location=GeoCoordinate(latitude=25.9900, longitude=56.0100),
            oil_volume_m3=60.0,
        ),
        ResponseTarget(
            target_id="RAK-PRIORITY-COASTAL",
            location=GeoCoordinate(latitude=25.9200, longitude=55.9300),
            oil_volume_m3=50.0,
        ),
        ResponseTarget(
            target_id="RAK-LARGE-OFFSHORE-1",
            location=GeoCoordinate(latitude=26.0400, longitude=55.8500),
            oil_volume_m3=120.0,
        ),
        ResponseTarget(
            target_id="RAK-LARGE-OFFSHORE-2",
            location=GeoCoordinate(latitude=26.1200, longitude=55.8000),
            oil_volume_m3=150.0,
        ),
    )

    return vessels, targets


# --- Wider Arabian Gulf Regional Scenario ---


def create_gulf_wide_scenario() -> tuple[tuple[Vessel, ...], tuple[ResponseTarget, ...]]:
    """Wider regional scenario across the central Arabian Gulf (UAE, Qatar, Saudi Arabia)."""
    vessels = (
        Vessel(
            vessel_id="GULF-FRV-HAWK",
            location=GULF_DEPOTS["mina_zayed_abu_dhabi"],
            speed_m_per_s=round(22.0 * KNOTS_TO_M_PER_S, 2),
            capacity_m3=60.0,
            available_hours=12.0,
        ),
        Vessel(
            vessel_id="GULF-OSRV-DANA",
            location=GULF_DEPOTS["jebel_ali_dubai"],
            speed_m_per_s=round(15.0 * KNOTS_TO_M_PER_S, 2),
            capacity_m3=250.0,
            available_hours=18.0,
        ),
        Vessel(
            vessel_id="GULF-OSRV-QATAR",
            location=GULF_DEPOTS["ras_laffan_qatar"],
            speed_m_per_s=round(14.0 * KNOTS_TO_M_PER_S, 2),
            capacity_m3=300.0,
            available_hours=20.0,
        ),
    )

    targets = (
        ResponseTarget(
            target_id="GULF-PATCH-01",
            location=GeoCoordinate(latitude=25.2500, longitude=53.4000),
            oil_volume_m3=45.0,
        ),
        ResponseTarget(
            target_id="GULF-PATCH-02",
            location=GeoCoordinate(latitude=25.3200, longitude=53.3800),
            oil_volume_m3=55.0,
        ),
        ResponseTarget(
            target_id="GULF-PATCH-03",
            location=GeoCoordinate(latitude=25.4000, longitude=53.3500),
            oil_volume_m3=60.0,
        ),
        ResponseTarget(
            target_id="GULF-PATCH-04",
            location=GeoCoordinate(latitude=25.5000, longitude=53.5000),
            oil_volume_m3=50.0,
        ),
    )

    return vessels, targets


def trajectory_to_targets(
    drift: DriftOutput,
    total_volume_m3: float = 200.0,
    max_targets: int = 8,
    forecast_time: datetime | None = None,
) -> tuple[ResponseTarget, ...]:
    """Convert a Team B DriftOutput simulation into discrete cleanup ResponseTargets.

    Selects oil patch positions at a single forecast time (defaulting to the latest /
    forecast horizon timestamp) so that the same moving slick is not counted multiple
    times across different time steps.
    """
    if not drift.positions:
        return ()

    # Default to the latest forecast timestamp in the simulation
    if forecast_time is None:
        target_time = max(tp.timestamp for tp in drift.positions)
    else:
        target_time = forecast_time

    # Filter positions to only patches present at the chosen forecast time
    positions_at_time = [tp for tp in drift.positions if tp.timestamp == target_time]
    if not positions_at_time:
        return ()

    n_pos = len(positions_at_time)
    step = max(1, n_pos // max_targets)
    sampled = positions_at_time[::step][:max_targets]

    vol_per_target = round(total_volume_m3 / len(sampled), 2)
    targets: list[ResponseTarget] = []

    for i, tp in enumerate(sampled, start=1):
        target_id = f"TGT-DRIFT-{drift.simulation_id[:6]}-{i:02d}"
        targets.append(
            ResponseTarget(
                target_id=target_id,
                location=tp.coordinate,
                oil_volume_m3=vol_per_target,
            )
        )

    return tuple(targets)


def create_synthetic_gulf_drift(
    simulation_id: str = "GULF-OPENOIL-24H",
    start_coord: GeoCoordinate = GeoCoordinate(latitude=25.85, longitude=55.65),
    start_time: datetime = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc),
    checkpoints_hours: Sequence[int] = (0, 6, 12, 24),
    particles_per_cloud: int = 12,
) -> DriftOutput:
    """Generate a 24-hour Gulf oil-drift simulation aligned with Team B OpenDrift results.

    Uses Maqqavi's simulation findings from the feature/drift-simulation branch (release at
    25.85° N, 55.65° E, 300 m3 Generic Medium Crude, 2026-10-23 12:00 UTC), reflecting net
    tidal and wind drift and OpenDrift particle spread at 0, 6, 12, and 24 hours.
    """
    # OpenDrift displacement from release point (east_km, north_km) and cloud width (km)
    hourly_centers = {
        0: (0.0, 0.0, 0.5),
        6: (7.7, 0.5, 0.8),
        12: (10.3, 0.9, 1.1),
        24: (12.0, 0.6, 1.7),
    }
    cos_lat = math.cos(math.radians(start_coord.latitude))
    positions: list[TimedPosition] = []

    for h in checkpoints_hours:
        t = start_time + timedelta(hours=h)
        if h in hourly_centers:
            center_east_km, center_north_km, spread_km = hourly_centers[h]
        else:
            # Interpolate if another hour is requested
            center_east_km = 0.5 * h
            center_north_km = 0.03 * h
            spread_km = 0.5 + 0.05 * h

        center_lat = start_coord.latitude + center_north_km / 111.2
        center_lon = start_coord.longitude + center_east_km / (111.2 * cos_lat)

        n_pts = 1 if h == 0 else particles_per_cloud

        for i in range(n_pts):
            if n_pts == 1:
                p_lat, p_lon = center_lat, center_lon
            else:
                # Radial dispersion pattern around slick center
                angle = 2.0 * math.pi * i / n_pts
                r = spread_km * (0.4 + 0.6 * ((i % 3) / 2.0))
                p_north = r * math.cos(angle)
                p_east = r * math.sin(angle)
                p_lat = center_lat + p_north / 111.2
                p_lon = center_lon + p_east / (111.2 * cos_lat)

            positions.append(
                TimedPosition(
                    timestamp=t,
                    coordinate=GeoCoordinate(latitude=round(p_lat, 5), longitude=round(p_lon, 5)),
                )
            )

    return DriftOutput(
        simulation_id=simulation_id,
        initial_location=start_coord,
        positions=tuple(positions),
        duration_hours=float(max(checkpoints_hours)),
    )


def create_gulf_drift_scenario(
    forecast_hour: float = 12.0,
    total_volume_m3: float = 196.9,
    max_targets: int = 8,
) -> tuple[tuple[Vessel, ...], tuple[ResponseTarget, ...]]:
    """Derive a realistic cleanup scenario from the Gulf 24-hour drift simulation.

    Selects oil patches at the chosen forecast checkpoint (default: T+12h, 196.9 m3 afloat
    per OpenDrift weathering budget) to ensure targets represent separate patches at a single
    time slice, paired with the operational RAK/Hamriyah fleet.
    """
    drift = create_synthetic_gulf_drift()
    start_time = drift.positions[0].timestamp
    target_time = start_time + timedelta(hours=forecast_hour)

    targets = trajectory_to_targets(
        drift=drift,
        total_volume_m3=total_volume_m3,
        max_targets=max_targets,
        forecast_time=target_time,
    )
    vessels = create_rak_standard_scenario()[0]
    return vessels, targets


# --- JSON Serialization Helpers ---


def scenario_to_dict(
    vessels: Sequence[Vessel], targets: Sequence[ResponseTarget], name: str = "custom"
) -> dict:
    """Convert vessel and target tuples to a clean JSON-serializable dictionary."""
    return {
        "scenario_name": name,
        "vessels": [asdict(v) for v in vessels],
        "targets": [asdict(t) for t in targets],
        "summary": {
            "num_vessels": len(vessels),
            "total_fleet_capacity_m3": sum(v.capacity_m3 for v in vessels),
            "num_targets": len(targets),
            "total_oil_volume_m3": sum(t.oil_volume_m3 for t in targets),
        },
    }


def export_scenario_to_json(
    vessels: Sequence[Vessel],
    targets: Sequence[ResponseTarget],
    filepath: Path | str,
    name: str = "custom",
) -> Path:
    """Export a scenario to a JSON file on disk."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = scenario_to_dict(vessels, targets, name=name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path


def load_scenario_from_json(
    filepath: Path | str,
) -> tuple[tuple[Vessel, ...], tuple[ResponseTarget, ...]]:
    """Load a scenario from a JSON file into typed dataclasses."""
    path = Path(filepath)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    vessels = tuple(
        Vessel(
            vessel_id=v["vessel_id"],
            location=GeoCoordinate(**v["location"]),
            speed_m_per_s=v["speed_m_per_s"],
            capacity_m3=v["capacity_m3"],
            available_hours=v["available_hours"],
        )
        for v in data["vessels"]
    )

    targets = tuple(
        ResponseTarget(
            target_id=t["target_id"],
            location=GeoCoordinate(**t["location"]),
            oil_volume_m3=t["oil_volume_m3"],
        )
        for t in data["targets"]
    )

    return vessels, targets


if __name__ == "__main__":
    fixtures_dir = Path(__file__).resolve().parent / "fixtures"
    scenarios = [
        ("smoke_test", create_smoke_test_scenario),
        ("gulf_standard", create_rak_standard_scenario),
        ("constrained_triage", create_constrained_triage_scenario),
        ("gulf_drift_t12", create_gulf_drift_scenario),
    ]

    print(f"Exporting scenario fixtures to {fixtures_dir} (Ras Al Khaimah focused)...")
    for scn_name, generator in scenarios:
        v_list, t_list = generator()
        target_file = fixtures_dir / f"{scn_name}.json"
        export_scenario_to_json(v_list, t_list, target_file, name=scn_name)
        print(f"  -> {scn_name}.json: {len(v_list)} vessels, {len(t_list)} targets saved.")
