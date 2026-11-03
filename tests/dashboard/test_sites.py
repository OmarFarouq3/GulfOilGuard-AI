"""Per-site layout: outputs/sites/<id>/{drift,routing}/, one folder per spill marker (folder name = id).

The site folders are written into the test outputs folder (TEST_OUTPUTS/sites) and removed after
each test, so every other test keeps the single-folder layout. Drift files come from
test_drift_page.drift_files (the drift/export_outputs.py format), moved to each site's release point.
"""

from __future__ import annotations

import json
import os
import shutil

import pytest
from dashboard_testkit import APP, page_text
from streamlit.testing.v1 import AppTest
from test_drift_page import RELEASE, drift_files

import config
from components.data import _stage
from services import mock_data, scenario, selection
from services.drift_loader import load_drift
from services.models import SpillSite
from services.routing_loader import load_routing
from services.schema import GeoCoordinate
from services.spill_loader import load_site_spills, site_ids

SITES = {"S1": (25.85, 55.65), "S2": (25.70, 55.40), "S3": (25.45, 55.35), "S4": (25.98, 55.85)}
FORECAST_CHIP = "Real forecast, simulated release"
SIMULATED_CHIP = "Simulated scenario"


def site_drift_files(site_id: str, lat: float, lon: float, gone: dict | None = None) -> tuple[dict, dict]:
    """drift_files() moved from the agreed release point to (lat, lon), with this site's own simulation_id."""
    collection, meta = drift_files(gone=gone if gone is not None else {})
    dlat, dlon = lat - RELEASE[0], lon - RELEASE[1]

    def move(coords):
        if coords and isinstance(coords[0], (int, float)):
            return [round(coords[0] + dlon, 6), round(coords[1] + dlat, 6)]
        return [move(c) for c in coords]

    for feature in collection["features"]:
        feature["geometry"]["coordinates"] = move(feature["geometry"]["coordinates"])
    meta["simulation_id"] = f"openoil-{lat:.2f}N-{lon:.2f}E-20261023T1200Z"
    meta["initial_location"] = {"latitude": lat, "longitude": lon}
    for position in meta["positions"]:
        c = position["coordinate"]
        c["latitude"], c["longitude"] = round(c["latitude"] + dlat, 6), round(c["longitude"] + dlon, 6)
    return collection, meta


def routing_files(site_id: str, lat: float, lon: float, simulation_id: str) -> dict[str, dict]:
    port = [56.048, 25.981]
    target = [round(lon + 0.05, 5), round(lat + 0.01, 5)]
    return {
        "routes": {"type": "FeatureCollection", "features": [{
            "type": "Feature", "geometry": {"type": "LineString", "coordinates": [port, target, port]},
            "properties": {"vessel_id": f"V-{site_id}", "assigned_target_ids": ["T01"], "estimated_distance_km": 80.0,
                           "estimated_travel_hours": 2.5, "oil_collected_m3": 140.0}}]},
        "summary": {"status": "feasible", "message": f"plan for {site_id}", "synthetic": True,
                    "scenario_id": f"{simulation_id}@dispatch6h"},
        "targets": {"type": "FeatureCollection", "features": [{
            "type": "Feature", "geometry": {"type": "Point", "coordinates": target},
            "properties": {"target_id": "T01", "oil_volume_m3": 140.0, "source_hours": 8}}]},
    }


@pytest.fixture
def sites():
    """Write sites/<id>/drift and sites/<id>/routing into the test outputs folder; removed afterwards."""

    def write(*ids: str, routing: bool = True, gone: dict | None = None, at: dict | None = None,
              validation: dict | None = None) -> None:
        for site_id in ids:
            lat, lon = (at or {}).get(site_id, SITES.get(site_id, RELEASE))
            files = config.site_files(site_id)
            collection, meta = site_drift_files(site_id, lat, lon, (gone or {}).get(site_id))
            files["drift"]["drift"].parent.mkdir(parents=True, exist_ok=True)
            files["drift"]["drift"].write_text(json.dumps(collection), encoding="utf-8")
            files["drift"]["meta"].write_text(json.dumps(meta), encoding="utf-8")
            if routing:
                files["routing"]["routes"].parent.mkdir(parents=True, exist_ok=True)
                for key, content in routing_files(site_id, lat, lon, meta["simulation_id"]).items():
                    files["routing"][key].write_text(json.dumps(content), encoding="utf-8")
            if validation is not None:
                files["site"]["validation"].write_text(json.dumps(validation), encoding="utf-8")

    yield write
    shutil.rmtree(config.SITES_DIR, ignore_errors=True)
    config.SPILLS_FILE.unlink(missing_ok=True)
    for path in [*config.DRIFT_DIR.glob("*"), *config.ROUTING_DIR.glob("*")]:
        path.unlink()


def site(site_id: str, lat: float | None = None, lon: float | None = None) -> SpillSite:
    lat, lon = (lat, lon) if lat is not None else SITES[site_id]
    return SpillSite(site_id, f"Site {site_id}", GeoCoordinate(lat, lon), True)


def write_spills(*markers: tuple[str, float, float]) -> None:
    config.SPILLS_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.SPILLS_FILE.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
         "properties": {"spill_id": spill_id, "name": f"Marker {spill_id}", "synthetic": True}}
        for spill_id, lat, lon in markers]}), encoding="utf-8")


def positions(drift) -> list:
    return [f["geometry"]["coordinates"] for h in drift.hours for f in drift.steps[h]]


# --- Paths and loaders --------------------------------------------------------------------------


def test_site_files_mirror_the_single_folder_files():
    files = config.site_files("S3")
    base = config.SITES_DIR / "S3"
    assert set(files["drift"]) == set(config.DRIFT_FILES)
    assert set(config.ROUTING_FILES) <= set(files["routing"])
    assert files["drift"]["meta"] == base / "drift" / "meta.json"
    assert files["routing"]["summary"] == base / "routing" / "summary.json"
    assert files["site"]["validation"] == base / "validation.json"


def test_loaders_default_to_the_single_folders(sites):
    sites("S1")
    assert load_drift() is None and load_routing() is None  # outputs/drift and outputs/routing are empty
    assert load_drift(config.site_files("S1")["drift"]).trajectory.simulation_id.startswith("openoil-25.85N")
    assert load_routing(config.site_files("S1")["routing"]).message == "plan for S1"


def test_cache_isolation_between_sites(sites):
    """S1 and S2 files of the same size and modification time never return each other's data."""
    sites("S1", "S2")
    for key in ("drift", "meta"):  # S2 = S1's text with only the (same-length) release in the id changed
        text = config.site_files("S1")["drift"][key].read_text(encoding="utf-8")
        config.site_files("S2")["drift"][key].write_text(text.replace("25.85N", "25.70N"), encoding="utf-8")
    paths = [config.site_files(s)["drift"]["meta"] for s in ("S1", "S2")]
    assert os.path.getsize(paths[0]) == os.path.getsize(paths[1])  # same length: only digits differ
    stamp = paths[0].stat().st_mtime_ns
    for path in paths:
        os.utime(path, ns=(stamp, stamp))
    for _round in range(2):
        for site_id, lat in (("S1", "25.85"), ("S2", "25.70"), ("S1", "25.85")):
            drift = load_drift(config.site_files(site_id)["drift"])
            routing = load_routing(config.site_files(site_id)["routing"])
            assert drift.trajectory.simulation_id.startswith(f"openoil-{lat}N")
            assert routing.message == f"plan for {site_id}" and routing.routes[0].route.vessel_id == f"V-{site_id}"


# --- Markers ------------------------------------------------------------------------------------


def test_markers_from_site_folders(sites):
    sites("S2", "S1", "S3")
    markers = load_site_spills()
    assert [s.spill_id for s in markers.sites] == ["S1", "S2", "S3"] and not markers.warnings
    s3 = markers.get("S3")
    assert (s3.location.latitude, s3.location.longitude) == SITES["S3"] and s3.synthetic and s3.name == "Site S3"


def test_folder_without_a_release_point_gets_no_marker(sites):
    sites("S1", "S2")
    config.site_files("S2")["drift"]["meta"].unlink()
    (config.SITES_DIR / "not a valid id").mkdir()
    markers = load_site_spills()
    assert [s.spill_id for s in markers.sites] == ["S1"]
    assert site_ids() == ["S1", "S2"]  # the folder name with spaces is not a marker id


def test_no_site_folders_means_no_site_markers():
    assert site_ids() == [] and load_site_spills() is None


def test_marker_source_order(sites, session):
    from components.data import spills_stage
    assert spills_stage().data.is_mock  # nothing on disk: the GOG-SIM catalogue
    sites("S1", "S2")
    assert [s.spill_id for s in spills_stage().data.sites] == ["S1", "S2"]  # site folders
    write_spills(("S1", 25.85, 55.65), ("S9", 26.0, 55.5))
    assert [s.spill_id for s in spills_stage().data.sites] == ["S1", "S9"]  # spills.geojson wins
    session["demo_mode"] = True
    assert [s.spill_id for s in spills_stage().data.sites] == [s[0] for s in mock_data.MOCK_SPILL_SITES]


# --- Binding --------------------------------------------------------------------------------------


def test_each_site_reads_its_own_folder_unmoved(sites):
    sites("S1", "S2", "S3")
    assert scenario.sites_mode(demo=False) and not scenario.sites_mode(demo=True)
    for site_id in ("S1", "S2", "S3"):
        shown = scenario.selected_drift(site(site_id), demo=False)
        assert positions(shown) == positions(load_drift(config.site_files(site_id)["drift"]))  # no offset
        assert shown.anchored_to == site_id and shown.model_run and not shown.is_mock
        assert _stage("predict", shown).status == "forecast"
        plan = scenario.selected_routing(site(site_id), demo=False)
        assert plan.message == f"plan for {site_id}" and plan.anchored_to == site_id
        assert plan.routes[0].route.coordinates == load_routing(config.site_files(site_id)["routing"]).routes[0].route.coordinates


def test_marker_without_a_folder_gets_no_data_never_another_site(sites):
    sites("S1")
    write_drift_too = load_drift(config.site_files("S1")["drift"])
    assert write_drift_too is not None
    assert scenario.selected_drift(site("S9", 26.0, 55.5), demo=False) is None
    assert scenario.selected_routing(site("S9", 26.0, 55.5), demo=False) is None
    assert _stage("predict", None).status == "empty"


def test_site_with_drift_but_no_routing(sites):
    sites("S1", routing=False)
    assert scenario.selected_drift(site("S1"), demo=False) is not None
    assert scenario.selected_routing(site("S1"), demo=False) is None


def test_release_point_far_from_the_marker_is_not_shown_as_real(sites):
    sites("S1")
    shown = scenario.selected_drift(site("S1", 25.90, 55.65), demo=False)  # marker ~5.5 km north
    assert not shown.model_run and shown.synthetic
    assert _stage("predict", shown).status == "simulated"
    assert any("not shown as a real forecast" in w and "S1" in w for w in shown.warnings)
    near = scenario.selected_drift(site("S1", 25.855, 55.65), demo=False)  # ~0.6 km: the same release point
    assert near.model_run and not near.warnings


def test_without_site_folders_the_single_folder_behaviour_stays(sites):
    from test_drift_page import drift_files as single
    collection, meta = single()
    config.DRIFT_DIR.mkdir(parents=True, exist_ok=True)
    config.DRIFT_FILES["drift"].write_text(json.dumps(collection), encoding="utf-8")
    config.DRIFT_FILES["meta"].write_text(json.dumps(meta), encoding="utf-8")
    assert not scenario.sites_mode(demo=False)
    at_release = scenario.selected_drift(site("GOG-SIM-01", *RELEASE), demo=False)
    assert at_release.model_run  # the real forecast at its own release point
    elsewhere = scenario.selected_drift(site("GOG-SIM-02", 26.02, 55.58), demo=False)
    assert elsewhere.is_mock  # the demo moved there, as before


def test_demo_mode_ignores_site_folders(sites):
    sites("S1")
    shown = scenario.selected_drift(site("GOG-SIM-02", 26.02, 55.58), demo=True)
    assert shown.is_mock and shown.anchored_to == "GOG-SIM-02"
    assert scenario.selected_routing(site("GOG-SIM-02", 26.02, 55.58), demo=True).is_mock


# --- The pages ---------------------------------------------------------------------------------------


def new_app(spill: str | None = None, demo: bool = False) -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=120)
    at.session_state["demo_mode"] = demo
    if spill:
        at.session_state[selection.SPILL_KEY] = spill
        at.session_state[selection.DETECT_SIMULATED_KEY] = True  # Detect done, so Predict unlocks
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def go(at: AppTest, page: str, button: str | None = None) -> AppTest:
    at.switch_page(page)
    at.run()
    if button:
        next(b for b in at.button if b.key == button).click()
        at.run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def bodies(at: AppTest, text: str) -> list[str]:
    return [h.proto.body for h in at.get("html") if text in h.proto.body and not h.proto.body.lstrip().startswith("/*")]


def heading(at: AppTest) -> str:
    return bodies(at, 'class="gog-heading"')[0]


def test_overview_offers_the_site_markers_and_says_numbers_are_per_site(sites):
    sites("S1", "S2", "S3", "S4")
    at = new_app()
    assert "pick a site on the map to see its numbers" in " ".join(bodies(at, "gog-kpi-scope"))
    assert ">—<" in bodies(at, "Spread at 24")[0]  # no single dataset behind the headline numbers
    go(at, "views/drift.py")
    assert FORECAST_CHIP not in heading(at) and SIMULATED_CHIP not in heading(at)  # no data until a site is picked


def test_stranding_at_24_h_on_the_selected_site(sites):
    sites("S1", "S3", gone={"S3": {12: {"stranded": 1}, 24: {"stranded": 4}}})
    at = go(new_app("S3"), "views/drift.py", "flow_run_predict")
    assert FORECAST_CHIP in heading(at)
    assert "Real OpenDrift forecast for site S3" in " ".join(bodies(at, "gog-flow-note"))
    expected = {0: (10, 0), 6: (10, 0), 12: (9, 1), 24: (6, 4)}
    for hours, (afloat, gone) in expected.items():
        next(b for b in at.button if b.key == f"drift_jump_{hours}").click()
        at.run()
        tile = bodies(at, "Particles afloat")[0]
        assert f">{afloat}<" in tile
        assert (f"{gone} no longer afloat" in tile) is bool(gone)
        legend = next(b for b in bodies(at, "gog-legend") if b.lstrip().startswith('<div class="gog-legend"'))
        assert ("No longer afloat" in legend) is bool(gone)


def test_selected_site_drives_predict_respond_and_the_headline(sites):
    sites("S1", "S2")
    at = go(new_app("S2"), "views/drift.py", "flow_run_predict")
    details = " ".join(h.proto.body for e in at.expander if e.label == "Run details" for h in e.get("html"))
    assert "openoil-25.70N-55.40E" in details and "openoil-25.85N" not in details
    go(at, "views/cleanup.py", "flow_run_respond")
    assert "Response plan for site S2" in " ".join(bodies(at, "Response plan for site"))
    assert "V-S2" in page_text(at) and "V-S1" not in page_text(at)
    go(at, "views/overview.py")
    assert "These numbers are for site S2" in " ".join(bodies(at, "gog-kpi-scope"))
    assert ">1<" in bodies(at, "Vessels deployed")[0]


def test_marker_without_a_folder_shows_no_data_on_predict_and_respond(sites):
    sites("S1")
    write_spills(("S1", 25.85, 55.65), ("S9", 26.0, 55.5))
    at = go(new_app("S9"), "views/drift.py", "flow_run_predict")
    assert "There is no drift forecast for site S9 yet." in " ".join(bodies(at, "no drift forecast"))
    assert FORECAST_CHIP not in heading(at) and SIMULATED_CHIP not in heading(at)
    assert "openoil-25.85N" not in page_text(at)  # never another site's data
    go(at, "views/cleanup.py", "flow_run_respond")
    assert "There is no response plan for site S9 yet." in " ".join(bodies(at, "no response plan"))
    assert "plan for S1" not in page_text(at) and "V-S1" not in page_text(at)


def test_diagnostics_list_site_files_and_validation(sites):
    sites("S1", validation={"counts": {"OK": 52, "WARN": 7, "FAIL": 0}})
    sites("S2", validation={"counts": {"OK": 40, "WARN": 2, "FAIL": 1}})
    sites("S3")
    config.site_files("S3")["routing"]["targets"].unlink()
    write_spills(("S1", 25.85, 55.65), ("S2", 25.70, 55.40), ("S3", 25.45, 55.35), ("S9", 26.0, 55.5))
    at = new_app()
    code = "\n".join(c.value for c in at.code)
    assert "S1: validation 52 OK, 7 WARN, 0 FAIL" in code and "S2: validation 40 OK, 2 WARN, 1 FAIL" in code
    assert "S3: validation.json missing" in code
    rows = [(s, f, m) for frame in at.dataframe if "Site" in frame.value
            for s, f, m in zip(frame.value["Site"], frame.value["File"], frame.value["Modified"])]
    assert ("S3", "routing/targets.geojson", "missing") in rows
    assert any(r[:2] == ("S1", "drift/drift.geojson") and r[2] != "missing" for r in rows)
    warnings = " ".join(m.value for m in at.markdown)
    assert "Site `S2`: its validation.json reports failed checks." in warnings
    assert "Marker `S9` has no site folder" in warnings


def test_diagnostics_warn_about_a_marker_far_from_its_release_point(sites):
    sites("S1")
    write_spills(("S1", 25.90, 55.65))
    at = new_app()
    assert any("not shown as a real forecast" in m.value for m in at.markdown)


def test_demo_mode_keeps_the_gog_sim_markers_with_sites_present(sites):
    sites("S1", "S2")
    at = go(new_app("GOG-SIM-02", demo=True), "views/drift.py", "flow_run_predict")
    assert SIMULATED_CHIP in heading(at) and FORECAST_CHIP not in heading(at)
    assert "gog-kpi-scope" not in page_text(go(at, "views/overview.py"))



# --- Browser-check fixes: side panel, Overview tile, Now step, Diagnostics, maps, Continue link ------------


def side_panel(at: AppTest) -> str:
    return " ".join(bodies(at, "gog-incident-head") + bodies(at, "gog-details"))


def test_side_panel_labels_the_site_like_predict(sites):
    sites("S1", "S2")
    at = new_app("S2")
    panel = side_panel(at)
    assert FORECAST_CHIP in panel and SIMULATED_CHIP not in panel
    assert "openoil-25.70N-55.40E-20261023T1200Z" in panel and "Release point" in panel and "25.700° N, 55.400° E" in panel
    legend = next(b for b in bodies(at, "gog-legend") if b.lstrip().startswith('<div class="gog-legend"'))
    assert "Forecast site (simulated release point)" in legend and "Simulated spill site" not in legend


def test_side_panel_for_a_marker_without_a_folder(sites):
    sites("S1")
    write_spills(("S1", 25.85, 55.65), ("S9", 26.0, 55.5))
    panel = side_panel(new_app("S9"))
    assert "None for this site yet" in panel and FORECAST_CHIP not in panel and "openoil" not in panel


def test_side_panel_outside_the_site_layout_is_unchanged():
    at = new_app("GOG-SIM-01")
    panel = side_panel(at)
    assert SIMULATED_CHIP in panel and "Simulation" not in panel and "Release point" not in panel


def test_overview_shows_the_site_release_footprint_not_the_demo_slick(sites):
    from services.geo import polygon_area_km2
    sites("S1", "S2")
    at = go(new_app("S2"), "views/drift.py", "flow_run_predict")
    go(at, "views/overview.py")
    tile = bodies(at, "Spread at 24")[0]
    assert "Release footprint, simulated" in tile and "Slick detected" not in tile and "not a detected slick" in tile
    drift = load_drift(config.site_files("S2")["drift"])
    assert f">{polygon_area_km2(drift.steps[0]):.1f}<" in tile


def test_overview_slick_tile_is_unchanged_outside_the_site_layout():
    tile = bodies(new_app(), "Spread at 24")[0]
    assert "Slick detected" in tile and "Release footprint" not in tile


def test_drift_distance_at_the_release_step(sites):
    sites("S1")
    at = go(new_app("S1"), "views/drift.py", "flow_run_predict")
    next(b for b in at.button if b.key == "drift_jump_0").click()
    at.run()
    tile = bodies(at, "Drift distance")[0]
    assert ">0.0<" in tile and "At the release point: no drift yet" in tile and "now → Now" not in tile
    next(b for b in at.button if b.key == "drift_jump_6").click()
    at.run()
    assert "Centre of the slick, now → +6 h" in bodies(at, "Drift distance")[0]


def diagnostics_rows(at: AppTest) -> list[tuple[str, str, str]]:
    return [(m, f, s) for frame in at.dataframe if "Module" in frame.value
            for m, f, s in zip(frame.value["Module"], frame.value["File"], frame.value["Modified"])]


def test_diagnostics_in_the_site_layout_list_only_expected_files(sites):
    sites("S1")
    files = [f for _m, f, _s in diagnostics_rows(new_app())]
    for unexpected in ("routing/routes.geojson", "routing/summary.json", "drift/drift.geojson", "spills.geojson",
                       "detection/mask.png", "detection/spill.geojson", "detection/summary.json"):
        assert unexpected not in files
    assert "detection/metrics.json" in files and "report/summary.json" in files  # still expected


def test_diagnostics_mark_present_single_folders_as_unused_in_the_site_layout(sites):
    from test_drift_page import drift_files as single
    sites("S1")
    collection, meta = single()
    config.DRIFT_DIR.mkdir(parents=True, exist_ok=True)
    config.DRIFT_FILES["drift"].write_text(json.dumps(collection), encoding="utf-8")
    rows = {f: s for _m, f, s in diagnostics_rows(new_app())}
    assert rows["drift/drift.geojson"].endswith("(not used: per-site layout)")


def test_diagnostics_outside_the_site_layout_still_list_missing_files():
    rows = {f: s for _m, f, s in diagnostics_rows(new_app())}
    assert rows["routing/routes.geojson"] == "missing" and rows["spills.geojson"].startswith("missing")


def test_maps_scroll_the_page_instead_of_zooming():
    from components import maps
    m = maps.base_map()
    assert m.options.get("scrollWheelZoom") is False and m.options.get("zoomControl", True) is not False


def page_order(at: AppTest) -> list[str]:
    """Continue link, map legend and the next section, in page order."""
    order = []

    def walk(node):
        text = str(getattr(node, "proto", ""))
        if getattr(node, "type", "") == "page_link" and "Continue to Respond" in text:
            order.append("continue")
        elif "gog-legend" in text and "Path of the slick" in text:
            order.append("legend")
        elif "What drives the forecast" in text:
            order.append("inputs")
        for child in getattr(node, "children", {}).values():
            walk(child)

    walk(at.main)
    return order


def test_continue_to_respond_follows_the_map(sites):
    sites("S1")
    at = go(new_app("S1"), "views/drift.py", "flow_run_predict")
    assert page_order(at) == ["legend", "continue", "inputs"]


def test_continue_to_respond_without_a_forecast_follows_the_note(sites):
    sites("S1")
    write_spills(("S1", 25.85, 55.65), ("S9", 26.0, 55.5))
    at = go(new_app("S9"), "views/drift.py", "flow_run_predict")
    assert page_order(at) == ["continue"]


def test_selected_step_is_kept_after_leaving_the_page(sites):
    sites("S1")
    at = go(new_app("S1"), "views/drift.py", "flow_run_predict")
    next(b for b in at.button if b.key == "drift_jump_12").click()
    at.run()
    go(at, "views/overview.py")
    assert go(at, "views/drift.py").select_slider[0].value == 12
