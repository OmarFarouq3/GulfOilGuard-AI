"""Write the drift files the routing and dashboard teams read: outputs/drift/.

Formats: optimization/README.md section 3.1 (what routing needs) and dashboard/README.md,
"Drift module" (what the dashboard draws). Both are met by the same two files.

  drift.geojson  one MultiPoint feature of particles per output hour and status (the same
                 particle keeps its `particle_ids` entry at every hour), plus one Polygon
                 "envelope" per hour for the dashboard.
  meta.json      the centre path (the shared `DriftOutput`), the run settings and the assumptions.

Coordinates are WGS84 [longitude, latitude] in GeoJSON and latitude/longitude in meta.json.
Times are UTC with a Z. Volumes are pure oil (mass / density), not emulsion.
"""

from __future__ import annotations

import json
from datetime import datetime
from math import atan2, degrees
from pathlib import Path

import numpy as np

from drift.simulate_drift import DriftRun, default_simulation_id, drift_output_from_run, hourly_summary

DECIMALS = 5  # about 1 m

SYNTHETIC_NOTE = (
    "SYNTHETIC scenario: the release point and time are agreed test inputs, not a detection result. "
    "Weathering depends on an assumed water temperature, salinity and diffusivity (no data for them)."
)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _hours(value: float) -> int | float:
    return int(value) if float(value).is_integer() else float(value)


def convex_hull(points) -> list[tuple[float, float]]:
    """Convex hull of (x, y) points, counter-clockwise, without repeating the first point."""
    pts = sorted({(float(x), float(y)) for x, y in points})
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _round_pair(lon: float, lat: float) -> list[float]:
    return [round(float(lon), DECIMALS), round(float(lat), DECIMALS)]


def build_drift_geojson(run: DriftRun, synthetic: bool = True) -> dict:
    """The oil at every output hour, as GeoJSON features (see the module docstring)."""
    features = []
    for step, (hour, moment) in enumerate(zip(run.hours, run.timestamps)):
        common = {"hours": _hours(hour), "timestamp": _iso(moment), "synthetic": synthetic}
        for code, name in enumerate(run.status_names):
            chosen = run.status[:, step] == code
            if not chosen.any():
                continue
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "MultiPoint",
                    "coordinates": [_round_pair(x, y) for x, y in zip(run.lon[chosen, step], run.lat[chosen, step])],
                },
                "properties": {
                    **common, "kind": "particles", "status": name,
                    "particle_ids": [int(i) for i in run.particle_ids[chosen]],
                    "oil_volume_m3": round(run.volume_m3(step, chosen), 3),
                },
            })
        afloat = run.active(step)
        if afloat.sum() >= 3:  # outline of the oil afloat, for the dashboard
            ring = [_round_pair(x, y) for x, y in convex_hull(zip(run.lon[afloat, step], run.lat[afloat, step]))]
            if len({tuple(p) for p in ring}) >= 3:
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [ring + [ring[0]]]},
                    "properties": {**common, "kind": "envelope", "status": "active"},
                })
    return {"type": "FeatureCollection", "features": features}


def _mean_direction(x: np.ndarray, y: np.ndarray) -> float:
    """Direction the mean vector points to, degrees clockwise from north, 0 to 360."""
    return float(degrees(atan2(float(np.mean(x)), float(np.mean(y)))) % 360)


def build_meta(run: DriftRun, simulation_id: str | None = None, synthetic: bool = True) -> dict:
    """meta.json: the centre path, the run settings, the forcing summary and the assumptions."""
    simulation_id = simulation_id or default_simulation_id(run.release, run.start_time)
    output = drift_output_from_run(run, simulation_id)
    afloat = np.stack([run.active(i) for i in range(len(run.hours))], axis=1)  # (particle, step)
    wx, wy = run.wind_x[afloat], run.wind_y[afloat]
    cx, cy = run.current_x[afloat], run.current_y[afloat]
    s = run.settings
    last = hourly_summary(run)[-1]
    return {
        "simulation_id": simulation_id,
        "synthetic": synthetic,
        "note": SYNTHETIC_NOTE,
        "initial_location": {"latitude": run.release.latitude, "longitude": run.release.longitude},
        "positions": [
            {"timestamp": _iso(p.timestamp),
             "coordinate": {"latitude": round(p.coordinate.latitude, DECIMALS),
                            "longitude": round(p.coordinate.longitude, DECIMALS)}}
            for p in output.positions
        ],
        "duration_hours": output.duration_hours,
        "start_time": _iso(run.start_time),
        "model": f"OpenDrift {run.opendrift_version} OpenOil",
        "oil_type": s.oil_type,
        "n_particles": run.n_particles,
        "release_volume_m3": s.release_volume_m3,
        "oil_volume_basis": "pure oil (mass / density); recovered emulsion would be larger by 1 / (1 - water_fraction)",
        "wind_source": "ERA5 hourly 10 m wind (Copernicus Climate Change Service)",
        "current_source": "Copernicus Marine GLOBAL_ANALYSISFORECAST_PHY_001_024: currents + tide, wave (Stokes) drift",
        "wind_speed_m_per_s": round(float(np.mean(np.hypot(wx, wy))), 3),
        "wind_from_deg": round((_mean_direction(wx, wy) + 180) % 360, 1),
        "current_speed_m_per_s": round(float(np.mean(np.hypot(cx, cy))), 3),
        "current_to_deg": round(_mean_direction(cx, cy), 1),
        "assumptions": {
            "release": "instantaneous, at the surface, inside a circle of radius "
                       f"{s.release_radius_m:g} m",
            "vertical_mixing": s.vertical_mixing,
            "sea_water_temperature_c": s.sea_water_temperature_c,
            "sea_water_salinity_psu": s.sea_water_salinity_psu,
            "horizontal_diffusivity_m2_per_s": s.horizontal_diffusivity_m2_per_s,
            "random_seed": s.seed,
            "time_step_s": s.time_step_s,
            "output_step_s": s.output_step_s,
        },
        "oil_afloat_m3_at_end": last["oil_afloat_m3"],
        "summary_by_hour": hourly_summary(run),
    }


def write_drift_outputs(run: DriftRun, out_dir: Path | str, simulation_id: str | None = None,
                        synthetic: bool = True) -> tuple[Path, Path]:
    """Write drift.geojson and meta.json into `out_dir` (created if needed); return both paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    geojson_path, meta_path = out_dir / "drift.geojson", out_dir / "meta.json"
    geojson_path.write_text(json.dumps(build_drift_geojson(run, synthetic), separators=(",", ":")), encoding="utf-8")
    meta_path.write_text(json.dumps(build_meta(run, simulation_id, synthetic), indent=2), encoding="utf-8")
    return geojson_path, meta_path
