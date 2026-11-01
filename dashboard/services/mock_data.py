"""DEMO SCENARIO: a synthetic, obviously fake Gulf oil spill scenario.

Nothing here comes from a model, a satellite or a solver. It exists only to demo and
test the dashboard layout before the detection, drift and routing modules produce outputs. Every generated file
carries ``"synthetic": true`` and names are marked as simulated.

The generator produces the exact file contents defined in the data contract, so
``write_sample_outputs()`` doubles as a reference example of the file format.

Scenario: a slick about 45 km NW of Abu Dhabi drifts SE under a NW (shamal) wind;
three simulated vessels from three simulated bases are routed to the 12 h oil patches.
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
from services.models import DetectionData, DetectionScene, DriftData, RoutingData, VesselRoute

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
MOCK_VESSELS = (  # id, port, speed (km/h), target IDs in visiting order
    ("Skimmer 1", "Base C (simulated)", 18.0, ["T1", "T2"]),
    ("Skimmer 2", "Base A (simulated)", 16.0, ["T3", "T4"]),
    ("Boom vessel 3", "Base B (simulated)", 14.0, ["T5"]),
)
SKIM_HOURS_PER_TARGET = 0.75
RECOVERY_RATE = 0.85


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
            "properties": {"id": "Slick 1", "synthetic": True, "area_km2": 6.8,
                           "confidence": 0.81, "detected_at": MOCK_START.strftime("%Y-%m-%dT%H:%M:%SZ")},
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
                           "timestamp": (MOCK_START + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")},
            "geometry": {"type": "Polygon", "coordinates": [_slick_polygon(center, scale, rng)]},
        })
        spread_km = 0.8 * scale
        particles = []
        for _ in range(40):
            lat, lon = _offset(*center, *(rng.standard_normal(2) * spread_km))
            particles.append([round(lon, 5), round(lat, 5)])
        drift_features.append({
            "type": "Feature",
            "properties": {"hours": hours, "kind": "particles", "synthetic": True},
            "geometry": {"type": "MultiPoint", "coordinates": particles},
        })
    files["drift/drift.geojson"] = {"type": "FeatureCollection", "features": drift_features}
    files["drift/meta.json"] = {
        "synthetic": True,
        "model": "OpenDrift OpenOil (simulated, illustrative)",
        "start_time": MOCK_START.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "wind_source": "ERA5 (simulated)",
        "current_source": "Copernicus Marine (simulated)",
        "wind_speed_ms": 8.0, "wind_from_deg": 315,
        "current_speed_ms": 0.2, "current_to_deg": 110,
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
    for vessel_id, port, speed_kmh, order in MOCK_VESSELS:
        port_lat, port_lon = MOCK_PORTS[port]
        coords = [[port_lon, port_lat]] + [[round(targets[t][0], 5), round(targets[t][1], 5)] for t in order]
        distance = path_length_km(coords)
        route_features.append({
            "type": "Feature",
            "properties": {
                "vessel_id": vessel_id, "order": order, "depot": port, "synthetic": True,
                "speed_kmh": speed_kmh,
                "distance_km": round(distance, 1),
                "eta_hours": round(distance / speed_kmh + SKIM_HOURS_PER_TARGET * len(order), 2),
                "oil_collected_m3": round(RECOVERY_RATE * sum(targets[t][2] for t in order), 1),
            },
            "geometry": {"type": "LineString", "coordinates": coords},
        })
    files["routing/routes.geojson"] = {"type": "FeatureCollection", "features": route_features}
    props = [f["properties"] for f in route_features]
    files["routing/summary.json"] = {
        "synthetic": True,
        "solver": "Simulated plan (no optimiser run)",
        "status": "feasible",
        "vessel_count": len(props),
        "total_time_hours": max(p["eta_hours"] for p in props),
        "total_distance_km": round(sum(p["distance_km"] for p in props), 1),
        "oil_collected_m3": round(sum(p["oil_collected_m3"] for p in props), 1),
        "oil_total_m3": sum(v for _, _, v in targets.values()),
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


def detection() -> DetectionData:
    files = _files()
    metrics = files["detection/metrics.json"]
    keys = ("dice", "iou", "precision", "recall")
    return DetectionData(
        scenes=[DetectionScene("default", files["detection/image.png"], files["detection/mask.png"],
                               files["detection/overlay.png"])],
        metrics={k: metrics[k] for k in keys},
        per_class=metrics["per_class"],
        metrics_info={k: v for k, v in metrics.items() if k not in (*keys, "per_class")},
        spill=files["detection/spill.geojson"],
        is_mock=True,
    )


def drift() -> DriftData:
    files = _files()
    steps: dict[float, list[dict]] = {}
    for feature in files["drift/drift.geojson"]["features"]:
        steps.setdefault(feature["properties"]["hours"], []).append(feature)
    return DriftData(steps=steps, meta=files["drift/meta.json"], is_mock=True)


def routing() -> RoutingData:
    files = _files()
    routes = []
    for feature in files["routing/routes.geojson"]["features"]:
        p = feature["properties"]
        routes.append(VesselRoute(
            vessel_id=p["vessel_id"], coordinates=feature["geometry"]["coordinates"], order=p["order"],
            eta_hours=p["eta_hours"], distance_km=p["distance_km"], oil_collected_m3=p["oil_collected_m3"],
            properties=p,
        ))
    return RoutingData(routes=routes, summary=files["routing/summary.json"],
                       targets=files["routing/targets.geojson"], is_mock=True)
