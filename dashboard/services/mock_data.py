"""DEMO SCENARIO: a synthetic, obviously fake Gulf oil spill scenario.

Nothing here comes from a model, a satellite or a solver. It exists only to demo and
test the dashboard layout before the detection, drift and routing modules produce outputs. Every generated file
carries ``"synthetic": true`` and names are marked as simulated.

Field names, types, units and enums follow shared/schemas.py. The page models are built by
the same parse/validate functions the loaders apply to real files, so the demo cannot
contain anything a real file would fail on. ``write_sample_outputs()`` writes the same
content as files, which doubles as a reference example of the format.

Scenario: a slick about 45 km NW of Abu Dhabi drifts SE under a NW (shamal) wind;
three simulated vessels from three simulated bases are routed to the 12 h oil patches.

Spill catalogue: four simulated incident sites offshore Ras Al Khaimah / Umm Al Quwain, around
config.MAP_CENTER, offered on the Overview map. They are separate from the scenario above,
which still sits off Abu Dhabi until the pages are wired to the selected spill.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import streamlit as st
from PIL import Image, ImageDraw

from services.geo import path_length_km
from services.imaging import compose_overlay, to_png
from services.detection_loader import build_detection
from services.drift_loader import build_drift
from services.models import DetectionData, DetectionScene, DriftData, RoutingData, SpillData
from services.routing_loader import build_routing
from services.spill_loader import build_spills

SEED = 2026
MOCK_START = datetime(2026, 3, 14, 6, 42, tzinfo=timezone.utc)
SPILL_CENTER = (24.88, 53.98)  # lat, lon (offshore, synthetic)
DRIFT_BEARING_DEG = 125.0  # towards SE
DRIFT_SPEED_KMH = 0.9  # ~3% of 8 m/s wind plus a weak current
HOURS = (0, 6, 12, 24)
KM_PER_DEG_LAT = 111.0

MOCK_PORTS = {
    "Base A (simulated)": (24.53, 54.37),
    "Base B (simulated)": (24.80, 54.62),
    "Base C (simulated)": (25.12, 53.70),
}
# Vessel fields follow shared/schemas.py: speed in m/s, capacity in m3, availability in hours.
MOCK_VESSELS = (  # vessel_id, base, speed_m_per_s, capacity_m3, assigned_target_ids (visiting order)
    ("Skimmer 1", "Base C (simulated)", 5.0, 150.0, ["T1", "T2"]),
    ("Skimmer 2", "Base A (simulated)", 4.5, 120.0, ["T3", "T4"]),
    ("Boom vessel 3", "Base B (simulated)", 3.9, 80.0, ["T5"]),
)
AVAILABLE_HOURS = 8.0
IMAGE_ID = "S1A_SIM_20260314T0642"  # simulated Sentinel-1 scene identifier
SIMULATION_ID = "SIM-GULF-20260314"
SKIM_HOURS_PER_TARGET = 0.75
RECOVERY_RATE = 0.85

# Incident sites for the Overview map, all at sea and 20+ km apart (so clicks are unambiguous).
MOCK_SPILL_SITES = (  # spill_id, name, lat, lon
    ("GOG-SIM-01", "Offshore Ras Al Khaimah (simulated)", 25.85, 55.65),
    ("GOG-SIM-02", "North of Ras Al Khaimah (simulated)", 26.02, 55.58),
    ("GOG-SIM-03", "Off Umm Al Quwain (simulated)", 25.66, 55.42),
    ("GOG-SIM-04", "Western shipping lane (simulated)", 25.92, 55.36),
)


def _offset(lat: float, lon: float, east_km: float, north_km: float) -> tuple[float, float]:
    """Move a (lat, lon) point by km east/north (small-distance approximation)."""
    km_per_deg_lon = KM_PER_DEG_LAT * math.cos(math.radians(lat))
    return lat + north_km / KM_PER_DEG_LAT, lon + east_km / km_per_deg_lon


def _drift_center(hours: float) -> tuple[float, float]:
    distance = DRIFT_SPEED_KMH * hours
    bearing = math.radians(DRIFT_BEARING_DEG)
    return _offset(*SPILL_CENTER, distance * math.sin(bearing), distance * math.cos(bearing))


def _slick_polygon(center: tuple[float, float], scale: float, rng: np.random.Generator) -> list[list[float]]:
    """Irregular ellipse elongated along the drift direction, as a closed [lon, lat] ring."""
    major, minor = 2.4 * scale, 0.9 * scale
    axis = math.radians(90 - DRIFT_BEARING_DEG)  # math angle of the drift axis
    ring = []
    for theta in np.linspace(0, 2 * math.pi, 28, endpoint=False):
        wobble = 1 + 0.12 * rng.standard_normal()
        x, y = major * math.cos(theta) * wobble, minor * math.sin(theta) * wobble
        east = x * math.cos(axis) - y * math.sin(axis)
        north = x * math.sin(axis) + y * math.cos(axis)
        lat, lon = _offset(*center, east, north)
        ring.append([round(lon, 5), round(lat, 5)])
    ring.append(ring[0])
    return ring


# --- Raw file contents (the data contract, filled with fake values) -----------------


def _sar_scene(rng: np.random.Generator, size: int = 320) -> tuple[np.ndarray, np.ndarray]:
    """Speckled SAR-like backscatter with a dark elongated slick, plus its binary mask."""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    cx, cy, angle = size * 0.52, size * 0.48, math.radians(-35)
    u = (xx - cx) * math.cos(angle) + (yy - cy) * math.sin(angle)
    v = -(xx - cx) * math.sin(angle) + (yy - cy) * math.cos(angle)
    ripple = 1 + 0.15 * np.sin(u / 9.0)
    slick = (u / (size * 0.33)) ** 2 + (v * ripple / (size * 0.09)) ** 2 < 1
    mask = (slick * 255).astype(np.uint8)

    backscatter = 0.55 + 0.08 * np.sin(xx / 40.0) * np.cos(yy / 55.0)
    backscatter = np.where(slick, 0.16, backscatter)  # oil damps waves -> dark in SAR
    speckle = rng.gamma(shape=4.0, scale=0.25, size=(size, size))  # multiplicative speckle
    image = np.clip(backscatter * speckle * 255, 0, 255).astype(np.uint8)
    rgb = np.stack([image] * 3, axis=-1)

    canvas = Image.fromarray(rgb)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, 112, 20], fill=(255, 210, 0))
    draw.text((6, 5), "SIMULATED SCENE", fill=(0, 0, 0))
    return np.asarray(canvas), mask


def _iso(moment: datetime) -> str:
    """Timezone-aware UTC timestamp in ISO 8601 (schema convention)."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mock_files() -> dict[str, Any]:
    """Return {relative path: bytes | JSON-serialisable object} for a full fake run."""
    rng = np.random.default_rng(SEED)
    files: dict[str, Any] = {}

    # Detection module
    image, mask = _sar_scene(rng)
    files["detection/image.png"] = to_png(image)
    files["detection/mask.png"] = to_png(mask)
    files["detection/overlay.png"] = compose_overlay(files["detection/image.png"], files["detection/mask.png"])
    files["detection/metrics.json"] = {
        "synthetic": True,
        "model": "U-Net (simulated, illustrative values)",
        "split": "Validation set (simulated)",
        "n_images": 120,
        "threshold": 0.5,
        "dice": 0.78, "iou": 0.64, "precision": 0.81, "recall": 0.75,
        "per_class": {
            "oil": {"dice": 0.78, "iou": 0.64, "precision": 0.81, "recall": 0.75},
            "background": {"dice": 0.98, "iou": 0.96, "precision": 0.98, "recall": 0.99},
        },
    }
    files["detection/spill.geojson"] = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"image_id": IMAGE_ID, "confidence": 0.81, "area_km2": 6.8, "synthetic": True},
            "geometry": {"type": "Polygon", "coordinates": [_slick_polygon(SPILL_CENTER, 1.0, rng)]},
        }],
    }

    # Drift module
    drift_features = []
    for hours in HOURS:
        center = _drift_center(hours)
        scale = 1 + 0.07 * hours
        drift_features.append({
            "type": "Feature",
            "properties": {"hours": hours, "kind": "envelope", "synthetic": True,
                           "timestamp": _iso(MOCK_START + timedelta(hours=hours))},
            "geometry": {"type": "Polygon", "coordinates": [_slick_polygon(center, scale, rng)]},
        })
        spread_km = 0.8 * scale
        particles = []
        for _ in range(40):
            lat, lon = _offset(*center, *(rng.standard_normal(2) * spread_km))
            particles.append([round(lon, 5), round(lat, 5)])
        drift_features.append({
            "type": "Feature",
            "properties": {"hours": hours, "kind": "particles", "synthetic": True,
                           "timestamp": _iso(MOCK_START + timedelta(hours=hours))},
            "geometry": {"type": "MultiPoint", "coordinates": particles},
        })
    files["drift/drift.geojson"] = {"type": "FeatureCollection", "features": drift_features}
    files["drift/meta.json"] = {
        "synthetic": True,
        # DriftOutput (shared/schemas.py): representative centre-of-mass trajectory
        "simulation_id": SIMULATION_ID,
        "initial_location": {"latitude": SPILL_CENTER[0], "longitude": SPILL_CENTER[1]},
        "duration_hours": float(max(HOURS)),
        "positions": [
            {"timestamp": _iso(MOCK_START + timedelta(hours=h)),
             "coordinate": {"latitude": round(_drift_center(h)[0], 5), "longitude": round(_drift_center(h)[1], 5)}}
            for h in HOURS
        ],
        "start_time": _iso(MOCK_START),
        # Model inputs (not in shared/schemas.py); speeds use the schema's _m_per_s suffix
        "model": "OpenDrift OpenOil (simulated, illustrative)",
        "wind_source": "ERA5 (simulated)",
        "current_source": "Copernicus Marine (simulated)",
        "wind_speed_m_per_s": 8.0, "wind_from_deg": 315.0,
        "current_speed_m_per_s": 0.2, "current_to_deg": 110.0,
        "n_particles": 40,
        "oil_type": "Medium crude (simulated)",
    }

    # Routing module (targets = oil patches along the 12 h envelope)
    center_12 = _drift_center(12)
    targets = {}
    for i, along_km in enumerate((-2.4, -1.2, 0.0, 1.2, 2.4)):
        bearing = math.radians(DRIFT_BEARING_DEG)
        lat, lon = _offset(*center_12, along_km * math.sin(bearing), along_km * math.cos(bearing))
        targets[f"T{i + 1}"] = (lon, lat, float(rng.integers(25, 90)))
    files["routing/targets.geojson"] = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"target_id": tid, "oil_volume_m3": vol, "source_hours": 12, "synthetic": True},
            "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
        } for tid, (lon, lat, vol) in targets.items()],
    }

    route_features = []
    for vessel_id, base, speed_m_per_s, capacity_m3, assigned in MOCK_VESSELS:
        base_lat, base_lon = MOCK_PORTS[base]
        coords = [[base_lon, base_lat]] + [[round(targets[t][0], 5), round(targets[t][1], 5)] for t in assigned]
        distance_km = path_length_km(coords)
        sailing_hours = distance_km * 1000 / speed_m_per_s / 3600
        collected = min(capacity_m3, RECOVERY_RATE * sum(targets[t][2] for t in assigned))
        route_features.append({
            "type": "Feature",
            "properties": {
                # VesselRoute
                "vessel_id": vessel_id,
                "assigned_target_ids": assigned,
                "estimated_distance_km": round(distance_km, 1),
                "estimated_travel_hours": round(sailing_hours, 2),  # sailing only, as in dashboard_export.py
                "finish_hours": round(sailing_hours + SKIM_HOURS_PER_TARGET * len(assigned), 2),  # + skimming
                # Vessel (location = first route coordinate)
                "speed_m_per_s": speed_m_per_s,
                "capacity_m3": capacity_m3,
                "available_hours": AVAILABLE_HOURS,
                # Not in shared/schemas.py
                "oil_collected_m3": round(collected, 1),
                "synthetic": True,
            },
            "geometry": {"type": "LineString", "coordinates": coords},
        })
    files["routing/routes.geojson"] = {"type": "FeatureCollection", "features": route_features}
    # OptimizationOutput without routes (they are in routes.geojson)
    files["routing/summary.json"] = {
        "status": "feasible",
        "message": "Simulated plan for demonstration; no optimiser was run.",
        "synthetic": True,
    }

    # Spill catalogue (Overview map)
    files["spills.geojson"] = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"spill_id": spill_id, "name": name, "synthetic": True},
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
        } for spill_id, name, lat, lon in MOCK_SPILL_SITES],
    }
    return files


def write_sample_outputs(target_dir: Path) -> list[Path]:
    """Write the mock run as real files (e.g. to test loaders or show the file format)."""
    written = []
    for relative, content in mock_files().items():
        path = target_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(json.dumps(content, indent=2), encoding="utf-8")
        written.append(path)
    return written


# --- Models for the pages -----------------------------------------------------------


@st.cache_data(show_spinner=False)
def _files() -> dict[str, Any]:
    return mock_files()


# Built with the loaders' own validation; check_schema.py asserts there are no warnings.
def detection() -> DetectionData:
    files = _files()
    scene = DetectionScene(IMAGE_ID, files["detection/image.png"], files["detection/mask.png"],
                           files["detection/overlay.png"])
    data = build_detection([scene], files["detection/spill.geojson"])
    data.is_mock = True
    return data


def drift() -> DriftData:
    files = _files()
    data = build_drift(files["drift/drift.geojson"], files["drift/meta.json"])
    data.is_mock = True
    return data


def routing() -> RoutingData:
    files = _files()
    data = build_routing(files["routing/routes.geojson"], files["routing/summary.json"],
                         files["routing/targets.geojson"])
    data.is_mock = True
    return data


def spill_outline() -> dict:
    """The demo slick as a GeoJSON FeatureCollection (raw, before validation)."""
    return _files()["detection/spill.geojson"]


def spills() -> SpillData:
    data = build_spills(_files()["spills.geojson"])
    data.is_mock = True
    return data
