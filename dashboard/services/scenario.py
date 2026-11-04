"""Results for the selected spill: detection, drift and routing positioned at that spill.

What is real and what is simulated:
- Detection: the mask is a real U-Net prediction on a real dataset image when inference ran
  (``mask_source="model"``), else the demo scene (``"simulated"``). The dataset images are
  not geolocated, so the mask has no position: the outline on the map is the demo slick moved
  to the spill (``outline_simulated``), without a confidence (meaningless for a placeholder).
- Drift: a real OpenDrift forecast (outputs/drift with ``DriftData.model_run``) is valid only
  for its own release point, so it is shown as is for the spill at that point and never moved;
  any other spill gets the demo scenario moved there (``selected_drift``). Other drift files
  (e.g. written by make_sample_outputs.py) are translated rigidly so their origin sits on the spill.
- Routing: the existing plan (outputs/routing, else the demo plan) moved by the same offset as
  the drift, so routes still meet the oil. Vessel bases move too (they are simulated);
  distances, times and volumes stay those of the source plan.

Everything built here is labelled synthetic, so its stage shows "Simulated scenario"; the real
forecast at its own release point shows "Real forecast, simulated release".

Per-site layout (``sites_mode``: outputs/sites/ has site folders, demo off): drift and routing
come from the selected spill's own folder ``outputs/sites/<spill_id>/``, never moved. A spill
without a folder has no data (None, "No data yet"): never another site's results, never the demo
mixed in with real sites. A forecast whose release point is more than RELEASE_MATCH_KM from its
marker keeps a warning and is not presented as a real forecast.
"""

from __future__ import annotations

import dataclasses
import re

import config
from services import mock_data
from services.detection_loader import load_scene, parse_spill
from services.drift_loader import load_drift
from services.files import read_json_object
from services.geo import features_center, haversine_km, offset_deg, translate_coords, translate_features
from services.inference import DetectionRun
from services.models import DetectionData, DriftData, RouteEntry, RoutingData, SpillSite
from services.routing_loader import load_comparison, load_routing
from services.schema import GeoCoordinate
from services.spill_loader import site_ids

Offset = tuple[float, float]  # (dlat, dlon)
SIMULATED_OUTLINE = "Simulated outline, not derived from the image"  # tooltip text of the placeholder


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
                                 "outline": SIMULATED_OUTLINE, "synthetic": True}
    return {"type": "FeatureCollection", "features": moved}


def selected_detection(site: SpillSite, run: DetectionRun | None, simulated_accepted: bool) -> DetectionData | None:
    """Model result for the selected image, else the accepted simulated detection, else None."""
    mask_dir = None
    if run is not None and run.ok:
        mask_dir = config.LIVE_DETECTION_DIR  # live runs never write into outputs/
        data = load_scene(run.image_id, mask_dir)
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
    parse_spill(_simulated_outline(site, image_id), data, mask_dir=mask_dir)
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


RELEASE_MATCH_KM = 1.0  # a spill this close to the forecast's release point is the one it was made for


def real_forecast(demo: bool) -> DriftData | None:
    """outputs/drift when it is a real OpenDrift run (and the demo is off), else None."""
    loaded = None if demo else load_drift()
    return loaded if loaded and loaded.has_content and loaded.model_run else None


def forecast_applies(drift: DriftData, site: SpillSite) -> bool:
    """The spill sits at the forecast's release point (meta.json initial_location)."""
    shift = shift_km(drift, site)
    return shift is not None and shift <= RELEASE_MATCH_KM


def sites_mode(demo: bool) -> bool:
    """Per-site results: outputs/sites/ has at least one site folder, and the demo is off."""
    return not demo and bool(site_ids())


def site_drift(site: SpillSite) -> DriftData | None:
    """The drift files of this spill's site folder, unmoved; None if it has none."""
    data = load_drift(config.site_files(site.spill_id)["drift"])
    if data is None or not data.has_content:
        return None
    shift = shift_km(data, site)
    if shift is None or shift > RELEASE_MATCH_KM:  # not the release point this marker stands for
        where = "has no release point" if shift is None else f"was made for a release {shift:,.1f} km away"
        data = dataclasses.replace(data, model_run=False, synthetic=True, warnings=[
            *data.warnings, f"Site `{site.spill_id}`: the forecast {where} from the marker (more than "
                            f"{RELEASE_MATCH_KM:g} km), so it is not shown as a real forecast."])
    return dataclasses.replace(data, anchored_to=site.spill_id)


def site_drift_unreadable(site: SpillSite) -> list[str]:
    """Why this site's drift files give no forecast although they exist (unreadable or invalid); [] otherwise.

    ``site_drift`` returns None both for a site with no drift files and for files that could not be read;
    these are the loader's warnings for the second case, for Diagnostics and Predict's note.
    """
    data = load_drift(config.site_files(site.spill_id)["drift"])
    if data is None or data.has_content:
        return []
    return [f"Site `{site.spill_id}`: {w}" for w in data.warnings]


def site_routing(site: SpillSite) -> RoutingData | None:
    """The routing files of this spill's site folder, unmoved; None if it has none."""
    data = load_routing(config.site_files(site.spill_id)["routing"])
    if data is None or not data.has_content:
        return None
    return dataclasses.replace(data, anchored_to=site.spill_id)


def site_comparison(site: SpillSite) -> tuple[dict | None, RoutingData | None, list[str]]:
    """The site's comparison.json and its nearest-target baseline plan (routing/baseline/), with warnings."""
    files = config.site_files(site.spill_id)
    comparison, warnings = load_comparison(files["routing"]["comparison"])
    baseline = load_routing(files["baseline"])
    if baseline is not None:
        warnings += baseline.warnings
        baseline = baseline if baseline.has_content else None
    return comparison, baseline, warnings


# The team's per-site checks (validation.json) a viewer should know about, shown as written.
VIEWER_CHECKS = ("unserved targets", "as emulsion", "patch size")


_ID_LIST = re.compile(r"\[('[^'\[\]]*'(?:,\s*'[^'\[\]]*')*)\]")


def _plain_lists(text: str) -> str:
    """"unserved targets: ['T05', 'T06']" -> "unserved targets: T05, T06" (only lists of quoted ids)."""
    return _ID_LIST.sub(lambda m: ", ".join(part.strip().strip("'") for part in m.group(1).split(",")), text)


def site_validation_warnings(site: SpillSite) -> list[str]:
    """WARN lines of the site's validation.json about unserved oil, emulsion volume and patch width."""
    raw, _warning = read_json_object(config.site_files(site.spill_id)["site"]["validation"])
    checks = raw.get("checks") if isinstance(raw, dict) else None
    return [f"{c.get('group', '')}: {_plain_lists(c['text'])}" for c in checks or []
            if isinstance(c, dict) and c.get("level") == "WARN" and isinstance(c.get("text"), str)
            and any(word in c["text"] for word in VIEWER_CHECKS)]


def plan_belongs_to(routing: RoutingData, drift: DriftData | None) -> bool:
    """The plan's scenario_id names this drift run (``<simulation_id>`` or ``<simulation_id>@...``)."""
    sim = drift.trajectory.simulation_id if drift and drift.trajectory else None
    return bool(sim and routing.scenario_id and (routing.scenario_id == sim or routing.scenario_id.startswith(f"{sim}@")))


def selected_drift(site: SpillSite, demo: bool) -> DriftData | None:
    """The real forecast for the spill it was made for (not moved); otherwise a scenario moved to the spill.

    A real forecast never moves to another spill: the wind and currents there differ. That spill
    gets the demo scenario instead (components.flow explains why). In the per-site layout the
    spill's own folder is read instead (``site_drift``).
    """
    if sites_mode(demo):
        return site_drift(site)
    real = real_forecast(demo)
    if real is not None:
        if forecast_applies(real, site):
            return dataclasses.replace(real, anchored_to=site.spill_id)
        drift = mock_data.drift()
    else:
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
            oil_collected_m3=e.oil_collected_m3, finish_hours=e.finish_hours,
        )
        for e in routing.routes
    ]
    return RoutingData(
        routes=routes, status=routing.status, message=routing.message,
        targets=[dataclasses.replace(t, location=_shift(t.location, offset)) for t in routing.targets],
        target_source_hours=routing.target_source_hours, synthetic=True, warnings=list(routing.warnings),
        is_mock=routing.is_mock, anchored_to=site.spill_id, target_info=dict(routing.target_info),
        unserved_target_ids=list(routing.unserved_target_ids), idle_vessel_ids=list(routing.idle_vessel_ids),
        scenario_id=routing.scenario_id,  # sea paths are left out: they don't fit a moved plan
    )


def selected_routing(site: SpillSite, demo: bool) -> RoutingData | None:
    """The plan moved by the drift scenario's offset, so it stays on the predicted oil.

    In the per-site layout, the spill's own routing folder instead, unmoved (``site_routing``).
    """
    if sites_mode(demo):
        return site_routing(site)
    return anchor_routing(source_routing(demo), site, drift_offset(source_drift(demo), site))
