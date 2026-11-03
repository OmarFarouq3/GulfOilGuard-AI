"""Respond page for a site in the per-site layout: oil layer, labels, home port, sea paths, unserved
patches, plan assumptions, optimised vs baseline, the team's warnings and the step selector.

Most tests run on COPIES of the real outputs/sites/S1..S4 (copied into the test outputs folder,
removed afterwards; skipped when the real folders are not on this machine). The parsing rules
and edge cases use small fixtures. Nothing writes to the real outputs/.
"""

from __future__ import annotations

import json
import shutil

import folium
import pytest
from dashboard_testkit import REPO_ROOT, page_text
from test_sites import FORECAST_CHIP, SIMULATED_CHIP, bodies, go, heading, new_app, sites  # noqa: F401  (fixture)

import config
from components import maps
from services import scenario, selection
from services.drift_loader import load_drift
from services.models import RoutingData
from services.routing_loader import load_comparison, load_routing
from services.spill_loader import load_site_spills

REAL_SITES = REPO_ROOT / "outputs" / "sites"
LAYER_HOURS = {"S1": 8, "S2": 9, "S3": 10, "S4": 7}  # the routing files' source_hours
UNSERVED = {"S1": ("T06", "0.4"), "S2": ("T05", "0.4"), "S3": ("T06", "0.2"), "S4": ("T06", "0.4")}
needs_real = pytest.mark.skipif(not (REAL_SITES / "S1" / "routing" / "comparison.json").is_file(),
                                reason="the real outputs/sites/S1..S4 are not on this machine")


@pytest.fixture
def real_sites():
    """Copy the real site folders into the test outputs folder (never touching the real ones)."""
    shutil.copytree(REAL_SITES, config.SITES_DIR)
    yield
    shutil.rmtree(config.SITES_DIR, ignore_errors=True)


def respond(spill: str, demo: bool = False):
    """The Respond page for ``spill`` with Detect and Predict done, after 'Plan the response'."""
    at = new_app(spill, demo=demo)
    at.session_state[selection.PREDICT_DONE_KEY] = True
    at.run()
    return go(at, "views/cleanup.py", "flow_run_respond")


@pytest.fixture
def drawn(monkeypatch):
    """Circle markers (tooltips), lines (points, dashed?) and the map's fit features, as the page draws them."""
    calls = {"markers": [], "lines": [], "fit": [], "layers": []}
    marker, line, render, add = folium.CircleMarker, folium.PolyLine, maps.render, maps.add_features

    def record_marker(*args, **kwargs):
        calls["markers"].append(str(kwargs.get("tooltip")))
        return marker(*args, **kwargs)

    def record_line(locations, *args, **kwargs):
        calls["lines"].append((len(locations), kwargs.get("dash_array"), str(kwargs.get("tooltip"))))
        return line(locations, *args, **kwargs)

    def record_render(m, fit, key, **kwargs):
        if key == "cleanup_map":
            calls["fit"] = [f["geometry"]["type"] for f in fit or []]
        return render(m, fit, key, **kwargs)

    def record_add(target, features, color, **kwargs):
        calls["layers"].append({f["properties"].get("status") for f in features if f["geometry"]["type"] == "MultiPoint"})
        calls["layers"][-1].add(sum(len(f["geometry"]["coordinates"]) for f in features
                                    if f["geometry"]["type"] == "MultiPoint"))
        return add(target, features, color, **kwargs)

    monkeypatch.setattr(folium, "CircleMarker", record_marker)
    monkeypatch.setattr(folium, "PolyLine", record_line)
    monkeypatch.setattr(maps, "render", record_render)
    monkeypatch.setattr(maps, "add_features", record_add)
    return calls


def html_table(at, css: str) -> list[list[str]]:
    """Rows (header first) of the ui.table with class ``css``, as plain text cells."""
    import html as markup
    import re
    body = next(b for b in bodies(at, css) if f"gog-table-wrap {css}" in b)
    return [[markup.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row)]
            for row in re.findall(r"<tr>(.*?)</tr>", body)]


def comparison_rows(at) -> dict[str, tuple[str, str]]:
    return {label: (optimised, baseline) for label, optimised, baseline in html_table(at, "gog-compare")[1:]}


def has_comparison(at) -> bool:
    return any("gog-table-wrap gog-compare" in b for b in bodies(at, "gog-compare"))


def captions(at) -> str:
    return " ".join(c.value for c in at.caption)


# --- Labels and captions (real files) ----------------------------------------------------------------


@needs_real
@pytest.mark.parametrize("spill", ["S1", "S2", "S3", "S4"])
def test_real_site_plan_is_labelled_like_its_forecast(real_sites, spill):
    at = respond(spill)
    assert FORECAST_CHIP in heading(at) and SIMULATED_CHIP not in heading(at)
    text = captions(at)
    assert "Assumptions, not observations: the vessels and their start positions, taken as home ports (fleet file " \
           "gulf_standard.json), and the dispatch time (+6 h after the release, 2026-10-23 18:00 UTC)." in text
    assert "It excludes the time spent cleaning." in text
    assert f"The map opens at +{LAYER_HOURS[spill]} h: the forecast step closest to the average meeting time" in text
    assert "cut from the oil afloat at the +6 h dispatch" in text


@needs_real
def test_demo_mode_keeps_simulated_scenario(real_sites):
    at = respond("GOG-SIM-01", demo=True)
    assert SIMULATED_CHIP in heading(at) and FORECAST_CHIP not in heading(at)
    assert "Assumptions, not observations" not in captions(at)
    assert not has_comparison(at)  # no comparison for the demo


def test_plan_for_another_forecast_is_not_labelled_real(sites):
    sites("S1")
    summary = config.site_files("S1")["routing"]["summary"]
    content = json.loads(summary.read_text(encoding="utf-8"))
    content["scenario_id"] = "openoil-25.70N-55.40E-20261023T1200Z@dispatch6h"  # S2's run
    summary.write_text(json.dumps(content), encoding="utf-8")
    assert SIMULATED_CHIP in heading(respond("S1"))


def test_plan_belongs_to():
    drift = type("D", (), {"trajectory": type("T", (), {"simulation_id": "run-1"})()})()
    for scenario_id, expected in (("run-1", True), ("run-1@dispatch6h", True), ("run-10@dispatch6h", False), (None, False)):
        assert scenario.plan_belongs_to(RoutingData(scenario_id=scenario_id), drift) is expected


# --- Oil layer and step selector ---------------------------------------------------------------------


@needs_real
@pytest.mark.parametrize("spill", ["S1", "S2", "S3", "S4"])
def test_oil_layer_slider_opens_at_the_plans_layer_hour(real_sites, spill):
    at = respond(spill)
    slider = at.select_slider[0]
    assert slider.label == "Predicted oil shown" and len(slider.options) == 25 and slider.value == LAYER_HOURS[spill]
    assert [b.label for b in at.button if (b.key or "").startswith("respond_jump_")] == ["Now", "+6 h", "+12 h", "+24 h"]
    assert not any(e.label == "Predicted oil shown" for e in at.get("segmented_control"))


@needs_real
def test_s3_at_24_h_draws_only_oil_still_afloat(real_sites, drawn):
    at = respond("S3")
    drawn["layers"].clear()
    next(b for b in at.button if b.key == "respond_jump_24").click()
    at.run()
    raw = load_drift(config.site_files("S3")["drift"])
    stranded = sum(len(f["geometry"]["coordinates"]) for f in raw.steps[24] if f["properties"]["status"] == "stranded")
    assert stranded == 444  # the real file: 444 of 1,000 stranded by 24 h
    oil_layers = [layer for layer in drawn["layers"] if "active" in layer or "stranded" in layer]
    assert oil_layers == [{"active", 556}]  # 556 afloat drawn, the stranded ones are not


@needs_real
def test_oil_step_is_kept_per_site_when_leaving_and_returning(real_sites):
    at = respond("S3")
    next(b for b in at.button if b.key == "respond_jump_24").click()
    at.run()
    go(at, "views/overview.py")
    assert go(at, "views/cleanup.py").select_slider[0].value == 24


# --- Routes, home port, sea paths, unserved, fit (real files) -------------------------------------------


@needs_real
@pytest.mark.parametrize("spill", ["S1", "S2", "S3", "S4"])
def test_home_port_once_and_sea_paths(real_sites, spill, drawn):
    at = respond(spill)
    routes = json.loads(config.site_files(spill)["routing"]["routes"].read_text(encoding="utf-8"))["features"]
    for feature in routes:
        vessel, props = feature["properties"]["vessel_id"], feature["properties"]
        assert feature["geometry"]["coordinates"][0] == feature["geometry"]["coordinates"][-1]  # the file returns home
        assert drawn["markers"].count(f"{vessel} base") == 1
        stops = [t for t in drawn["markers"] if t.startswith(f"{vessel} · stop")]
        assert len(stops) == len(props["assigned_target_ids"])  # the return to port is no extra stop
        lines = [n for n, dash, tip in drawn["lines"] if tip.startswith(f"{vessel}:")]
        assert lines == [len(props["sea_path"])]  # drawn along the sea path, not straight between stops
    assert "following sea paths around land" in page_text(at)


@needs_real
@pytest.mark.parametrize("spill", ["S1", "S2", "S3", "S4"])
def test_unserved_patch_is_flagged_with_its_volume(real_sites, spill, drawn):
    at = respond(spill)
    target, volume = UNSERVED[spill]
    notice = " ".join(b for b in bodies(at, "gog-notice") if b.lstrip().startswith('<div class="gog-notice"'))
    assert f"Not served: {target} ({volume} m³)" in notice and "less than 0.5 m3 left" in notice
    assert any(t.startswith(f"{target} · {volume} m³ · not served") for t in drawn["markers"])
    legend = next(b for b in bodies(at, "gog-legend") if b.lstrip().startswith('<div class="gog-legend"'))
    assert "Oil patch not served" in legend


@needs_real
def test_patch_tooltips_say_when_the_vessel_meets_them(real_sites, drawn):
    respond("S1")
    assert any(t.startswith("T01 · 145.3 m³ · met at +7.4 h by RAK-OSRV-SAQR") for t in drawn["markers"])


@needs_real
def test_map_fits_the_routes_and_patches_not_the_oil_layer(real_sites, drawn):
    respond("S2")
    assert drawn["fit"] and set(drawn["fit"]) <= {"Point", "LineString"}
    assert drawn["fit"].count("Point") == 5 and drawn["fit"].count("LineString") == 2  # 5 patches, 2 routes


# --- Comparison, baseline, assumptions, warnings (real files) --------------------------------------------


@needs_real
def test_comparison_table_from_comparison_json(real_sites):
    rows = comparison_rows(respond("S2"))
    assert rows["Distance sailed (km)"] == ("194.8", "58.2")
    assert rows["Longest sailing route (h), the response time above"] == ("5.03", "2.24")
    assert rows["Last vessel back, including cleaning (h)"] == ("7.18", "8.55")
    assert rows["Patches served"] == ("4", "4")
    assert rows["Oil recovered, share of the targeted oil"] == ("100%", "99%")


@needs_real
def test_shares_are_captioned_as_targeted_oil(real_sites):
    at = respond("S3")
    assert "Shares are of the oil in the targeted patches (198 m³)" in captions(at)
    assert "they are not shares of the oil spilled" in captions(at)


@needs_real
def test_per_vessel_comparison(real_sites):
    at = respond("S4")
    table = html_table(at, "gog-compare-vessels")
    assert table[0] == ["Vessel", "Optimised", "Optimised (km)", "Baseline", "Baseline (km)"]
    rows = {r[0]: dict(zip(table[0], r)) for r in table[1:]}
    assert rows["RAK-OSRV-SAQR"]["Baseline"] == "T02 → T04 → T01 → T05 → T03"
    assert rows["RAK-OSRV-SAQR"]["Baseline (km)"] == "36.5" and rows["RAK-OSRV-SAQR"]["Optimised (km)"] == "25.4"
    assert rows["RAK-FRV-FALCON"]["Optimised"] == "T05 → T04 → T03" and rows["RAK-FRV-FALCON"]["Baseline"] == "—"


@needs_real
def test_baseline_routes_toggle(real_sites, drawn):
    at = respond("S4")
    assert not any(dash for _n, dash, _t in drawn["lines"])
    drawn["lines"].clear()
    next(t for t in at.toggle if t.label == "Show the nearest-target baseline routes").set_value(True)
    at.run()
    baseline = [(n, tip) for n, dash, tip in drawn["lines"] if dash]
    assert baseline and baseline[0][1].startswith("Baseline RAK-OSRV-SAQR: T02 → T04 → T01 → T05 → T03")
    legend = next(b for b in bodies(at, "gog-legend") if b.lstrip().startswith('<div class="gog-legend"'))
    assert "Nearest-target baseline" in legend


@needs_real
def test_plan_assumptions_and_validation_warnings_as_written(real_sites):
    at = respond("S1")
    assumptions = " ".join(m.value for e in at.expander if e.label == "Plan assumptions" for m in e.markdown)
    assert "cleanup rate 30 m3/h (assumed)" in assumptions
    warnings = " ".join(m.value for e in at.expander if e.label.startswith("Warnings from") for m in e.markdown)
    assert "RAK-FRV-FALCON: as emulsion (water uptake from meta.json) about 111 m3, 185% of the tank" in warnings
    assert "1 patch(es) wider than 1.5 km" in warnings and "unserved targets: T06 (0.4 m3)" in warnings
    assert "['" not in warnings  # no Python list syntax
    assert "every particle appears once per step" not in warnings  # OK checks are not shown


@needs_real
def test_vessel_table_headers_and_idle_vessels(real_sites):
    at = respond("S3")
    frame = next(f.value for f in at.dataframe if "Visiting order" in f.value.columns)
    assert list(frame.columns) == ["Vessel", "Visiting order", "Stops", "Distance (km)", "Sailing (h)", "Speed (m/s)",
                                   "Capacity (m³)", "Oil (m³)"]  # short enough for its column (measured at 1150 px)
    assert "Not deployed: RAK-FRV-FALCON, RAK-OSRV-SAQR." in captions(at)


@needs_real
def test_overview_keeps_the_release_footprint_label(real_sites):
    at = respond("S2")
    tile = bodies(go(at, "views/overview.py"), "Spread at 24")[0]
    assert "Release footprint, simulated" in tile and "Slick detected" not in tile


# --- Parsing rules (fixtures) ------------------------------------------------------------------------------


def test_routing_extensions_are_read(sites):
    sites("S1")
    files = config.site_files("S1")["routing"]
    routes = json.loads(files["routes"].read_text(encoding="utf-8"))
    routes["features"][0]["properties"]["sea_path"] = [[56.048, 25.981], [55.9, 25.9], [56.048, 25.981]]
    files["routes"].write_text(json.dumps(routes), encoding="utf-8")
    summary = json.loads(files["summary"].read_text(encoding="utf-8"))
    summary.update(unserved_target_ids=["T09"], idle_vessel_ids=["V-idle"])
    files["summary"].write_text(json.dumps(summary), encoding="utf-8")
    data = load_routing(files)
    assert data.route_paths == {"V-S1": [(25.981, 56.048), (25.9, 55.9), (25.981, 56.048)]}
    assert data.unserved_target_ids == ["T09"] and data.idle_vessel_ids == ["V-idle"] and not data.warnings
    assert data.scenario_id.endswith("@dispatch6h")


def test_bad_sea_path_is_ignored_with_a_warning(sites):
    sites("S1")
    files = config.site_files("S1")["routing"]
    routes = json.loads(files["routes"].read_text(encoding="utf-8"))
    routes["features"][0]["properties"]["sea_path"] = [[56.048, 95.0]]  # latitude out of range
    files["routes"].write_text(json.dumps(routes), encoding="utf-8")
    data = load_routing(files)
    assert data.route_paths == {} and any("sea_path ignored" in w for w in data.warnings) and data.routes


def test_comparison_keeps_numbers_and_assignments_only(tmp_path):
    path = tmp_path / "comparison.json"
    path.write_text(json.dumps({"scenario_id": "x", "fleet": "f", "metrics": {"optimized_distance_km": 10.0,
                                "baseline_distance_km": "far", "same_targets_covered": None},
                                "optimized": {"assignments": {"V1": ["T1"]}}, "baseline": {"assignments": "bad"},
                                "drift": {"dispatch_hours": 6, "dispatch_time": "2026-10-23T18:00:00Z"}}), encoding="utf-8")
    content, warnings = load_comparison(path)
    assert content["metrics"] == {"optimized_distance_km": 10.0} and content["assignments"] == {"optimized": {"V1": ["T1"]}}
    assert content["dispatch_hours"] == 6 and content["dispatch_time"] == "2026-10-23T18:00:00Z"
    assert len(warnings) == 2  # the text metric and the bad baseline assignments
    assert load_comparison(tmp_path / "missing.json") == (None, [])


def test_site_without_comparison_shows_no_comparison_section(sites):
    sites("S1")
    at = respond("S1")
    assert FORECAST_CHIP in heading(at)
    assert not has_comparison(at)
    assert "Optimised plan vs nearest-target baseline" not in page_text(at)
    assert not [t for t in at.toggle if t.label.startswith("Show the nearest")]


def test_markers_still_come_from_the_site_folders(sites):
    sites("S1", "S2")
    assert [s.spill_id for s in load_site_spills().sites] == ["S1", "S2"]


def test_only_the_viewer_relevant_warnings_are_shown(sites):
    validation = {"counts": {"OK": 1, "WARN": 4, "FAIL": 0}, "checks": [
        {"group": "A drift", "level": "OK", "text": "every particle appears once per step"},
        {"group": "D routes (optimized)", "level": "WARN", "text": "unserved targets: ['T05', 'T06'] (0.6 m3)"},
        {"group": "D routes (optimized)", "level": "WARN", "text": "V1: as emulsion (water uptake) about 111 m3, 185% of the tank"},
        {"group": "B targets", "level": "WARN", "text": "patch size where it is met: 1 patch(es) wider than 1.5 km"},
        {"group": "C timing", "level": "WARN", "text": "solver took 2 rounds to settle"},
    ]}
    sites("S1", validation=validation)
    at = respond("S1")
    warnings = [m.value for e in at.expander if e.label.startswith("Warnings from") for m in e.markdown]
    assert warnings == ["- D routes (optimized): unserved targets: T05, T06 (0.6 m3)\n"
                        "- D routes (optimized): V1: as emulsion (water uptake) about 111 m3, 185% of the tank\n"
                        "- B targets: patch size where it is met: 1 patch(es) wider than 1.5 km"]



# --- Final polish: comparison order and objective, narrow tables, plain lists ----------------------------


@needs_real
def test_comparison_starts_with_the_finish_time_and_states_the_objective(real_sites):
    at = respond("S2")
    labels = [row[0] for row in html_table(at, "gog-compare")[1:]]
    assert labels == ["Last vessel back, including cleaning (h)", "Patches served", "Oil recovered (m³)",
                      "Oil recovered, share of the targeted oil", "Longest sailing route (h), the response time above",
                      "Distance sailed (km)"]
    text = captions(at)
    assert "The optimiser does not aim for the shortest total distance." in text
    assert "recover the most oil" in text and "cleaning included, as early as possible" in text
    assert "one hour earlier is worth 100 km of extra sailing" in text and "only then to sail the fewest kilometres" in text


def test_objective_caption_matches_the_optimiser_settings():
    """The caption quotes the routing team's weights; it must change if they do."""
    import sys
    sys.path.insert(0, str(REPO_ROOT))
    from optimization.config import DEFAULT_CONFIG
    assert DEFAULT_CONFIG.response_hour_cost_km == 100
    assert DEFAULT_CONFIG.drop_penalty_km > 24 * DEFAULT_CONFIG.response_hour_cost_km  # oil first, then time
    source = (REPO_ROOT / "optimization" / "routing_model.py").read_text(encoding="utf-8")
    assert "SetGlobalSpanCostCoefficient" in source and "SetArcCostEvaluatorOfAllVehicles" in source
    assert "AddDisjunction" in source


@needs_real
def test_comparison_tables_wrap_and_the_wide_one_says_it_scrolls(real_sites):
    at = respond("S4")
    compare = next(b for b in bodies(at, "gog-compare") if "gog-table-wrap gog-compare\"" in b)
    vessels = next(b for b in bodies(at, "gog-compare-vessels") if "gog-table-wrap gog-compare-vessels" in b)
    assert "gog-scroll-hint" not in compare  # fits at 390 px (measured): no hint
    assert vessels.startswith('<p class="gog-scroll-hint">Scroll sideways to see all columns') and "gog-num" in vessels
    css = (config.DASHBOARD_DIR / "assets" / "styles.css").read_text(encoding="utf-8")
    assert ".gog-table-wrap { overflow-x: auto;" in css and ".gog-scroll-hint { display: none;" in css


def test_validation_lists_become_plain_text():
    assert scenario._plain_lists("unserved targets: ['T06'] (0.4 m3)") == "unserved targets: T06 (0.4 m3)"
    assert scenario._plain_lists("unserved: ['T05', 'T06']") == "unserved: T05, T06"
    for unchanged in ("90 % of a patch's oil", "'one skimming position' is an assumption", "at [25.8, 55.6]"):
        assert scenario._plain_lists(unchanged) == unchanged
