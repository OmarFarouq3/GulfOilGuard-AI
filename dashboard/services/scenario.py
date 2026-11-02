"""Results for the selected spill: detection, drift and routing positioned at that spill.

What is real and what is simulated:
- Detection: the mask is a real U-Net prediction on a real dataset image when inference ran
  (``mask_source="model"``), else the demo scene (``"simulated"``). The dataset images are
  not geolocated, so the mask has no position: the outline on the map is the demo slick moved
  to the spill (``outline_simulated``), without a confidence (meaningless for a placeholder).
- Drift: ``simulate_drift`` is not implemented, so the existing drift results (outputs/drift,
  else the demo scenario) are translated rigidly so that their origin sits on the spill.
- Routing: the existing plan (outputs/routing, else the demo plan) moved by the same offset as
  the drift, so routes still meet the oil. Vessel bases move too (they are simulated);
  distances, times and volumes stay those of the source plan.

Everything built here is labelled synthetic, so its stage shows "Simulated scenario".
"""

from __future__ import annotations

import dataclasses

from services import mock_data
from services.detection_loader import load_scene, parse_spill
from services.drift_loader import load_drift
from services.geo import features_center, haversine_km, offset_deg, translate_coords, translate_features
from services.inference import DetectionRun
from services.models import DetectionData, DriftData, RouteEntry, RoutingData, SpillSite
from services.routing_loader import load_routing
from services.schema import GeoCoordinate

Offset = tuple[float, float]  # (dlat, dlon)


def site_point(site: SpillSite) -> tuple[float, float]:
    return site.location.latitude, site.location.longitude


def _shift(coordinate: GeoCoordinate, offset: Offset) -> GeoCoordinate:
    return GeoCoordinate(latitude=round(coordinate.latitude + offset[0], 6),
                         longitude=round(coordinate.longitude + offset[1], 6))


# --- Detection --------------------------------------------------------------------------


def _simulated_outline(site: SpillSite, image_id: str) -> dict:
    """The demo slick moved onto the spill, labelled synthetic, without a confidence."""
    features = mock_data.spill_outline()["features"]
    origin = features_center(features)
    moved = translate_features(features, *offset_deg(origin, site_point(site)))
    for feature in moved:
        feature["properties"] = {"image_id": image_id, "area_km2": feature["properties"].get("area_km2"),
                                 "synthetic": True}
    return {"type": "FeatureCollection", "features": moved}


def selected_detection(site: SpillSite, run: DetectionRun | None, simulated_accepted: bool) -> DetectionData | None:
    """Model result for the selected image, else the accepted simulated detection, else None."""
    if run is not None and run.ok:
        data = load_scene(run.image_id)
        if data is None:  # result files were removed since the run
            return None
        data.mask_source = "model"
    elif simulated_accepted:
        data = mock_data.detection()
        data.mask_source = "simulated"
    else:
        return None
    image_id = data.scenes[0].image_id if data.scenes else site.spill_id
    data.spill, data.detections = None, []
    parse_spill(_simulated_outline(site, image_id), data)
    data.outline_simulated = True
    return data


# --- Drift --------------------------------------------------------------------------------


def source_drift(demo: bool) -> DriftData:
    """outputs/drift when it has content (and the demo is off), else the demo scenario."""
    loaded = None if demo else load_drift()
    return loaded if loaded and loaded.has_content else mock_data.drift()


def drift_origin(drift: DriftData) -> tuple[float, float] | None:
    """The scenario's release point: DriftOutput.initial_location, else the earliest step's centre."""
    if drift.trajectory:
        return drift.trajectory.initial_location.latitude, drift.trajectory.initial_location.longitude
    return features_center(drift.steps[drift.hours[0]]) if drift.steps else None


def drift_offset(drift: DriftData, site: SpillSite) -> Offset:
    origin = drift_origin(drift)
    return offset_deg(origin, site_point(site)) if origin else (0.0, 0.0)


def shift_km(drift: DriftData, site: SpillSite) -> float | None:
    """How far the scenario was moved to reach the spill."""
    origin = drift_origin(drift)
    return haversine_km(origin[1], origin[0], site.location.longitude, site.location.latitude) if origin else None


def anchor_drift(drift: DriftData, site: SpillSite, offset: Offset) -> DriftData:
    trajectory = drift.trajectory
    if trajectory:
        trajectory = dataclasses.replace(
            trajectory,
            initial_location=_shift(trajectory.initial_location, offset),
            positions=tuple(dataclasses.replace(p, coordinate=_shift(p.coordinate, offset))
                            for p in trajectory.positions),
        )
    meta = dict(drift.meta) if drift.meta else None
    if meta and isinstance(meta.get("initial_location"), dict):  # keep meta consistent with the trajectory
        location = meta["initial_location"]
        moved = translate_coords([location.get("longitude"), location.get("latitude")], *offset)
        meta["initial_location"] = {"latitude": moved[1], "longitude": moved[0]}
    return DriftData(
        steps={h: translate_features(features, *offset) for h, features in drift.steps.items()},
        trajectory=trajectory, meta=meta, synthetic=True, warnings=list(drift.warnings),
        is_mock=drift.is_mock, anchored_to=site.spill_id,
    )


def selected_drift(site: SpillSite, demo: bool) -> DriftData:
    drift = source_drift(demo)
    return anchor_drift(drift, site, drift_offset(drift, site))


# --- Routing ------------------------------------------------------------------------------


def source_routing(demo: bool) -> RoutingData:
    loaded = None if demo else load_routing()
    return loaded if loaded and loaded.has_content else mock_data.routing()


def anchor_routing(routing: RoutingData, site: SpillSite, offset: Offset) -> RoutingData:
    routes = [
        RouteEntry(
            route=dataclasses.replace(e.route, coordinates=tuple(_shift(c, offset) for c in e.route.coordinates)),
            vessel=dataclasses.replace(e.vessel, location=_shift(e.vessel.location, offset)) if e.vessel else None,
            oil_collected_m3=e.oil_collected_m3,
        )
        for e in routing.routes
    ]
    return RoutingData(
        routes=routes, status=routing.status, message=routing.message,
        targets=[dataclasses.replace(t, location=_shift(t.location, offset)) for t in routing.targets],
        target_source_hours=routing.target_source_hours, synthetic=True, warnings=list(routing.warnings),
        is_mock=routing.is_mock, anchored_to=site.spill_id,
    )


def selected_routing(site: SpillSite, demo: bool) -> RoutingData:
    """The plan moved by the drift scenario's offset, so it stays on the predicted oil."""
    return anchor_routing(source_routing(demo), site, drift_offset(source_drift(demo), site))
