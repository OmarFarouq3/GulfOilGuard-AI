"""A made-up drift forecast, so the drift-to-routing pipeline can be tested before the real run.

This is NOT a simulation result and must never be shown as one. It only has the same
shape as the files Maqqavi's OpenDrift run will write to outputs/drift/ (format in
dashboard/README.md, "Drift module"), and every file is marked "synthetic": true.
Once the real files exist, run_drift_plan reads those instead.

What is agreed (drift/DATA_SOURCES.md): the synthetic release point 25.85 N, 55.65 E,
Generic Medium Crude, and Joud's data window (from 2026-10-19 00:00 UTC).
What is made up here: everything about the motion. The slick moves as a whole at a fixed
speed and heading (a placeholder, NOT read from Joud's wind and current files), and spreads
like a random walk. A particle that ends up on land is marked "stranded" (needs the land
file, see sea_grid.py). The share of oil still afloat is a placeholder weathering curve.
Steps are hourly and every particle keeps its number (particle_ids), as an OpenDrift export
would, so the routing can follow each patch as it moves.

Run from the repository root:
    python -m optimization.drift_standin
"""

import json
from datetime import datetime, timedelta, timezone
from math import cos, radians, sin, sqrt
from pathlib import Path

import numpy as np

from optimization.config import DEFAULT_CONFIG
from optimization.sea_distance import default_provider
from shared.schemas import GeoCoordinate

OUT_DIR = Path(__file__).parent / "examples" / "drift_standin"

START = GeoCoordinate(latitude=25.85, longitude=55.65)  # agreed synthetic release point
RELEASE_TIME = datetime(2026, 10, 19, 0, tzinfo=timezone.utc)  # first hour of Joud's data
HOURS = tuple(range(25))  # hourly, 0 to 24 h
N_PARTICLES = 400
RELEASE_VOLUME_M3 = 300.0  # same placeholder as DriftTargetConfig.release_volume_m3
SEED = 7

# --- placeholders, not from any data ---
DRIFT_SPEED_M_PER_S = 0.18  # whole-slick drift
DRIFT_TO_DEG = 125.0  # towards the south-east, as a north-westerly (shamal) wind would push it
SPREAD_KM_AT_24H = (6.0, 3.5)  # one standard deviation: along the drift, across it
AFLOAT_AT = ((0, 6, 12, 24), (1.0, 0.85, 0.78, 0.72))  # share still afloat; the rest evaporated or dispersed

KM_PER_DEG_LAT = 111.2


def _offset(point: GeoCoordinate, east_km: float, north_km: float) -> GeoCoordinate:
    return GeoCoordinate(
        latitude=point.latitude + north_km / KM_PER_DEG_LAT,
        longitude=point.longitude + east_km / (KM_PER_DEG_LAT * cos(radians(point.latitude))),
    )


def make_standin() -> tuple[dict, dict]:
    """Return (drift.geojson, meta.json) contents."""
    rng = np.random.default_rng(SEED)
    along_unit = (sin(radians(DRIFT_TO_DEG)), cos(radians(DRIFT_TO_DEG)))  # (east, north)
    across_unit = (along_unit[1], -along_unit[0])
    z = rng.standard_normal((N_PARTICLES, 2))  # each particle keeps its place in the cloud
    mask = getattr(default_provider(DEFAULT_CONFIG), "mask", None)

    features, centre_path = [], []
    stranded = np.zeros(N_PARTICLES, dtype=bool)
    for hours in HOURS:
        moved_km = DRIFT_SPEED_M_PER_S * 3.6 * hours
        centre = _offset(START, moved_km * along_unit[0], moved_km * along_unit[1])
        spread = sqrt(hours / 24)
        points = []
        for i in range(N_PARTICLES):
            along = z[i, 0] * SPREAD_KM_AT_24H[0] * spread
            across = z[i, 1] * SPREAD_KM_AT_24H[1] * spread
            p = _offset(
                centre,
                along * along_unit[0] + across * across_unit[0],
                along * along_unit[1] + across * across_unit[1],
            )
            if mask is not None and (cell := mask.cell_of(p)) is not None and mask.land[cell]:
                stranded[i] = True  # once on the beach, it stays there
            points.append(p)

        timestamp = (RELEASE_TIME + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        afloat = ~stranded
        share = RELEASE_VOLUME_M3 / N_PARTICLES
        for status, chosen, volume in (
            ("active", afloat, share * float(np.interp(hours, *AFLOAT_AT)) * afloat.sum()),
            ("stranded", stranded, share * stranded.sum()),
        ):
            if not chosen.any():
                continue
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "MultiPoint",
                    "coordinates": [
                        [round(p.longitude, 5), round(p.latitude, 5)] for p, c in zip(points, chosen) if c
                    ],
                },
                "properties": {
                    "hours": hours, "timestamp": timestamp, "kind": "particles",
                    "particle_ids": [i for i, c in enumerate(chosen) if c],
                    "status": status, "oil_volume_m3": round(float(volume), 2), "synthetic": True,
                },
            })
        centre_path.append({
            "timestamp": timestamp,
            "coordinate": {"latitude": round(centre.latitude, 5), "longitude": round(centre.longitude, 5)},
        })

    meta = {
        "simulation_id": "standin-25.85N-55.65E",
        "synthetic": True,
        "note": "STAND-IN, not an OpenDrift result. Made by optimization/drift_standin.py "
                "to test the routing pipeline; replace with the real outputs/drift/ files.",
        "initial_location": {"latitude": START.latitude, "longitude": START.longitude},
        "positions": centre_path,
        "duration_hours": max(HOURS),
        "start_time": RELEASE_TIME.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": "stand-in: fixed drift + random-walk spread (not OpenDrift)",
        "oil_type": "GENERIC MEDIUM CRUDE",
        "n_particles": N_PARTICLES,
        "release_volume_m3": RELEASE_VOLUME_M3,
    }
    return {"type": "FeatureCollection", "features": features}, meta


def main() -> None:
    drift, meta = make_standin()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "drift.geojson").write_text(json.dumps(drift), encoding="utf-8")
    (OUT_DIR / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Wrote a SYNTHETIC stand-in drift forecast to {OUT_DIR}")
    for f in drift["features"]:
        p = f["properties"]
        print(f"  {p['hours']:>2} h  {p['status']:<9} {len(f['geometry']['coordinates']):>4} particles  "
              f"{p['oil_volume_m3']:>6.1f} m3")


if __name__ == "__main__":
    main()
