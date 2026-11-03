"""Predict page against real OpenDrift output: particle status, the "Real forecast, simulated release"
label, binding the forecast to its release point, the time selector and the run details.

The drift files are written into the test outputs folder in the format of drift/export_outputs.py
(one MultiPoint per hour and status, one envelope Polygon per hour, meta.json with "model",
"assumptions", ...). Nothing here reads the real outputs/.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from dashboard_testkit import APP, page_text
from streamlit.testing.v1 import AppTest

import config
from components import maps
from components.data import Stage, _stage, combined_status
from components.labels import STAGE_STATUS
from services import mock_data, scenario, selection
from services.drift_loader import afloat, is_model_run, load_drift
from services.files import iter_positions
from services.models import SpillSite
from services.schema import GeoCoordinate

REAL_MODEL = "OpenDrift 1.14.11 OpenOil"
RELEASE = (25.85, 55.65)
START = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
HOURS = range(25)
N = 10  # particles
GONE = {12: {"stranded": 3, "evaporated": 1}, 24: {"stranded": 4}}  # particles no longer afloat
FORECAST_CHIP = "Real forecast, simulated release"
SIMULATED_CHIP = "Simulated scenario"
NOT_AFLOAT = "No longer afloat (stranded, evaporated, ...)"


def iso(hours: float) -> str:
    return (START + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def drift_files(model: str = REAL_MODEL, synthetic: bool = True, gone: dict | None = None) -> tuple[dict, dict]:
    gone = GONE if gone is None else gone
    features = []
    for h in HOURS:
        lat, lon = RELEASE[0] + 0.001 * h, RELEASE[1] + 0.004 * h
        points = [[round(lon + 0.002 * i, 5), round(lat + 0.001 * (i % 3), 5)] for i in range(N)]
        common = {"hours": h, "timestamp": iso(h), "synthetic": synthetic}
        start = 0
        for status, n in [("active", N - sum(gone.get(h, {}).values())), *gone.get(h, {}).items()]:
            features.append({"type": "Feature", "geometry": {"type": "MultiPoint", "coordinates": points[start:start + n]},
                             "properties": {**common, "kind": "particles", "status": status,
                                            "particle_ids": list(range(start, start + n)), "oil_volume_m3": 1.0 * n}})
            start += n
        ring = [[lon, lat], [lon + 0.02, lat], [lon + 0.02, lat + 0.01], [lon, lat]]
        features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
                         "properties": {**common, "kind": "envelope", "status": "active"}})
    meta = {
        "simulation_id": "openoil-25.85N-55.65E-20261023T1200Z", "synthetic": synthetic,
        "note": "SYNTHETIC scenario: the release point and time are agreed test inputs, not a detection result.",
        "initial_location": {"latitude": RELEASE[0], "longitude": RELEASE[1]},
        "positions": [{"timestamp": iso(h), "coordinate": {"latitude": RELEASE[0] + 0.001 * h,
                                                           "longitude": RELEASE[1] + 0.004 * h}} for h in HOURS],
        "duration_hours": 24.0, "start_time": iso(0), "model": model, "oil_type": "GENERIC MEDIUM CRUDE",
        "n_particles": N, "release_volume_m3": 300.0,
        "wind_source": "ERA5 hourly 10 m wind (Copernicus Climate Change Service)",
        "current_source": "Copernicus Marine GLOBAL_ANALYSISFORECAST_PHY_001_024",
        "wind_speed_m_per_s": 3.587, "wind_from_deg": 241.7, "current_speed_m_per_s": 0.21, "current_to_deg": 126.6,
        "assumptions": {"release": "instantaneous, at the surface, inside a circle of radius 500 m",
                        "vertical_mixing": False, "sea_water_temperature_c": 28.0, "sea_water_salinity_psu": 40.0,
                        "horizontal_diffusivity_m2_per_s": 10.0, "random_seed": 42},
        "summary_by_hour": [{"hours": float(h), "active": N} for h in HOURS],
    }
    return {"type": "FeatureCollection", "features": features}, meta


@pytest.fixture
def write_drift():
    """Write drift.geojson + meta.json into the test outputs folder; removed afterwards."""
    config.DRIFT_DIR.mkdir(parents=True, exist_ok=True)

    def write(**kwargs) -> None:
        collection, meta = drift_files(**kwargs)
        config.DRIFT_FILES["drift"].write_text(json.dumps(collection), encoding="utf-8")
        config.DRIFT_FILES["meta"].write_text(json.dumps(meta), encoding="utf-8")

    yield write
    for path in config.DRIFT_DIR.glob("*"):
        path.unlink()


def site(spill_id: str, lat: float, lon: float) -> SpillSite:
    return SpillSite(spill_id, f"{spill_id} (simulated)", GeoCoordinate(lat, lon), True)


# --- Particle status and the model-run flag --------------------------------------------------------


@pytest.mark.parametrize("status, expected", [
    ("active", True), ("Active", True), (None, True),  # no status: files that only write oil afloat
    ("stranded", False), ("evaporated", False), ("dispersed", False), ("missing_data", False),
])
def test_only_active_particles_are_afloat(status, expected):
    props = {"hours": 6} if status is None else {"hours": 6, "status": status}
    assert afloat({"type": "Feature", "geometry": {"type": "MultiPoint", "coordinates": []}, "properties": props}) \
        is expected


@pytest.mark.parametrize("model, expected", [
    ("OpenDrift 1.14.11 OpenOil", True),
    ("OpenDrift OpenOil", True),
    ("OpenDrift OpenOil (simulated, illustrative)", False),  # the demo scenario
    ("OpenDrift (Simulated)", False),
    ("Hand-drawn drift", False),
    (None, False), (42, False),
])
def test_model_run_comes_from_meta_model(model, expected):
    assert is_model_run({"model": model} if model is not None else {}) is expected


def test_demo_scenario_is_never_a_model_run():
    assert mock_data.drift().model_run is False


def test_loader_flags_the_real_run(write_drift):
    write_drift()
    data = load_drift()
    assert data.model_run and data.synthetic and not data.warnings and data.hours == list(HOURS)


# --- Status and wording ---------------------------------------------------------------------------


def test_forecast_wording_is_exact():
    assert STAGE_STATUS["forecast"][1] == FORECAST_CHIP
    assert STAGE_STATUS["simulated"][1] == SIMULATED_CHIP


@pytest.mark.parametrize("model, synthetic, status", [
    (REAL_MODEL, True, "forecast"),                                     # real run, synthetic release
    (REAL_MODEL, False, "live"),                                        # real run, real release
    ("OpenDrift OpenOil (simulated, illustrative)", True, "simulated"),  # hand-made sample file
])
def test_drift_stage_status(write_drift, model, synthetic, status):
    write_drift(model=model, synthetic=synthetic)
    assert _stage("predict", load_drift()).status == status


def test_demo_drift_stays_simulated():
    assert _stage("predict", mock_data.drift()).status == "simulated"


def test_forecast_counts_as_simulated_in_the_headline_numbers():
    stages = {"predict": Stage("predict", object(), "forecast", False), "detect": Stage("detect", None, "empty", False)}
    assert combined_status(stages) == "simulated"


# --- Binding the forecast to its release point ------------------------------------------------------


def all_positions(drift) -> list:
    return [p for h in drift.hours for f in drift.steps[h] for p in iter_positions(f["geometry"]["coordinates"])]


def test_forecast_is_shown_unmoved_at_its_release_point(write_drift):
    write_drift()
    real = load_drift()
    shown = scenario.selected_drift(site("GOG-SIM-01", *RELEASE), demo=False)
    assert shown.model_run and not shown.is_mock and shown.anchored_to == "GOG-SIM-01"
    assert all_positions(shown) == all_positions(real)  # not moved at all
    assert _stage("predict", shown).status == "forecast"


def test_another_spill_gets_the_demo_scenario_not_the_moved_forecast(write_drift):
    write_drift()
    shown = scenario.selected_drift(site("GOG-SIM-02", 26.02, 55.58), demo=False)
    assert shown.is_mock and not shown.model_run and shown.anchored_to == "GOG-SIM-02"
    assert scenario.drift_origin(shown) == pytest.approx((26.02, 55.58), abs=1e-5)
    assert shown.trajectory.simulation_id == mock_data.drift().trajectory.simulation_id
    assert _stage("predict", shown).status == "simulated"


@pytest.mark.parametrize("north_km, applies", [(0.0, True), (0.9, True), (1.2, False), (20.0, False)])
def test_release_match_distance(write_drift, north_km, applies):
    write_drift()
    lat = RELEASE[0] + north_km / 110.574
    assert scenario.forecast_applies(load_drift(), site("X", lat, RELEASE[1])) is applies


def test_without_a_real_forecast_other_drift_files_are_moved_as_before(write_drift):
    write_drift(model="OpenDrift OpenOil (simulated, illustrative)")
    shown = scenario.selected_drift(site("GOG-SIM-02", 26.02, 55.58), demo=False)
    assert not shown.is_mock and not shown.model_run  # the outputs/ files, moved
    assert scenario.drift_origin(shown) == pytest.approx((26.02, 55.58), abs=1e-5)


def test_demo_mode_ignores_the_real_forecast(write_drift):
    write_drift()
    assert scenario.real_forecast(demo=True) is None
    assert scenario.selected_drift(site("GOG-SIM-01", *RELEASE), demo=True).is_mock


# --- The page -------------------------------------------------------------------------------------------


def predict_page(demo: bool = False, spill: str | None = None) -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=120)
    at.session_state["demo_mode"] = demo
    if spill:
        at.session_state[selection.SPILL_KEY] = spill
        at.session_state[selection.DETECT_SIMULATED_KEY] = True  # Detect done, so Predict is ready
    at.run()
    at.switch_page("views/drift.py")
    at.run()
    if spill:
        next(b for b in at.button if b.key == "flow_run_predict").click()
        at.run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def heading(at: AppTest) -> str:
    return next(h.proto.body for h in at.get("html") if 'class="gog-heading"' in h.proto.body)


def html_with(at: AppTest, text: str) -> list[str]:
    return [h.proto.body for h in at.get("html") if text in h.proto.body and not h.proto.body.lstrip().startswith("/*")]


def tiles(at: AppTest) -> str:
    return html_with(at, "Particles afloat")[0]


def legend(at: AppTest) -> str:
    return next(b for b in html_with(at, "gog-legend") if b.lstrip().startswith('<div class="gog-legend"'))


@pytest.fixture
def drawn(monkeypatch):
    """Every maps.add_features call on the page: (colour, number of particles drawn)."""
    calls = []
    real = maps.add_features

    def record(target, features, color, **kwargs):
        points = sum(len(list(iter_positions(f["geometry"]["coordinates"])))
                     for f in features if f["geometry"]["type"] in maps.POINT_TYPES)
        calls.append((color, points, {f["properties"].get("status") for f in features}))
        return real(target, features, color, **kwargs)

    monkeypatch.setattr(maps, "add_features", record)
    return calls


def test_real_forecast_page_label_and_time_selector(write_drift):
    write_drift()
    at = predict_page()
    assert FORECAST_CHIP in heading(at) and SIMULATED_CHIP not in heading(at)
    assert "gog-step-predict-forecast" in page_text(at)  # timeline dot
    slider = at.select_slider[0]
    assert slider.label == "Forecast time" and len(slider.options) == 25
    assert slider.value == 6  # the default forecast step
    assert [b.label for b in at.button if (b.key or "").startswith("drift_jump_")] == ["Now", "+6 h", "+12 h", "+24 h"]
    assert not any(e.label == "Forecast time" for e in at.get("segmented_control"))  # the crowded control is gone


@pytest.mark.parametrize("key, hours", [("drift_jump_0", 0), ("drift_jump_12", 12), ("drift_jump_24", 24)])
def test_jump_buttons_select_the_key_times(write_drift, key, hours):
    write_drift()
    at = predict_page()
    next(b for b in at.button if b.key == key).click()
    at.run()
    assert at.select_slider[0].value == hours
    assert iso(hours)[8:10] in tiles(at)  # "Valid at" follows the selected step


def test_slider_reaches_every_hour(write_drift):
    write_drift()
    at = predict_page()
    at.select_slider[0].set_value(17).run()
    assert at.select_slider[0].value == 17 and "+17 h" in page_text(at)


def test_stranded_and_evaporated_particles_are_not_drawn_as_oil(write_drift, drawn):
    write_drift()
    at = predict_page()
    next(b for b in at.button if b.key == "drift_jump_12").click()
    drawn.clear()
    at.run()
    assert "Particles afloat" in tiles(at) and ">6<" in tiles(at) and "4 no longer afloat" in tiles(at)
    assert "#8fa9b8" in [color for color, _n, _s in drawn]


def test_no_longer_afloat_layer_and_legend(write_drift, drawn):
    write_drift()
    at = predict_page()
    next(b for b in at.button if b.key == "drift_jump_12").click()
    drawn.clear()
    at.run()
    oil = [c for c in drawn if c[0] != "#8fa9b8"]
    gone = [c for c in drawn if c[0] == "#8fa9b8"]
    assert gone == [("#8fa9b8", 4, {"stranded", "evaporated"})]
    assert all(statuses <= {"active"} for _color, _n, statuses in oil)  # oil layers hold active particles only
    assert sum(n for _c, n, _s in oil if _c == config.oil_color_for_hour(12)) == 6
    assert NOT_AFLOAT in legend(at)


def test_no_grey_layer_when_everything_is_afloat(write_drift, drawn):
    write_drift(gone={})
    at = predict_page()
    assert "#8fa9b8" not in [c[0] for c in drawn] and NOT_AFLOAT not in legend(at)
    assert "no longer afloat" not in tiles(at)


def test_trail_and_legend_use_only_the_key_times(write_drift):
    write_drift()
    at = predict_page()
    next(b for b in at.button if b.key == "drift_jump_24").click()
    at.run()
    entries = legend(at)
    for label in ("Now", "+6 h", "+12 h", "+24 h"):
        assert f"</span>{label}</span>" in entries
    assert "+7 h" not in entries and "+23 h" not in entries


def test_run_details_come_from_meta_json(write_drift):
    write_drift()
    at = predict_page()
    expander = next(e for e in at.expander if e.label == "Run details")
    details = " ".join(h.proto.body for h in expander.get("html"))
    for text in ("Oil type", "GENERIC MEDIUM CRUDE", "Forecast length", "24 h", "Particles", ">10<",
                 "Wind data", "ERA5 hourly 10 m wind", "Current data", "Copernicus Marine", "Drift model", REAL_MODEL,
                 "Release point", "25.850° N, 55.650° E", "Release time", "23 Oct 12:00 UTC",
                 "Oil released (m³)", "300.0", "Water temperature (°C, assumed)", "28.0", "Vertical mixing", ">Off<"):
        assert text in details, text
    assert "random_seed" not in details and "summary_by_hour" not in details  # only the listed fields
    assert "not a detection result" in " ".join(c.value for c in expander.caption)


def test_selected_spill_at_the_release_point_gets_the_real_forecast(write_drift):
    write_drift()
    at = predict_page(spill="GOG-SIM-01")
    assert FORECAST_CHIP in heading(at)
    note = html_with(at, "Real OpenDrift forecast, made for this release point")
    assert note and "test inputs, not a detection" in note[0]
    provenance = html_with(at, 'class="gog-prov"')[0]
    assert "OpenDrift run" in provenance and "Release point and time" in provenance
    assert at.select_slider[0].options and len(at.select_slider[0].options) == 25


def test_another_selected_spill_falls_back_to_the_demo_with_a_note(write_drift):
    write_drift()
    at = predict_page(spill="GOG-SIM-02")
    assert SIMULATED_CHIP in heading(at) and FORECAST_CHIP not in heading(at)
    note = " ".join(html_with(at, "doesn&#x27;t apply to this spill"))
    assert "The real forecast was made for a release at 25.850° N, 55.650° E" in note
    assert "demo drift scenario" in note
    details = " ".join(h.proto.body for e in at.expander if e.label == "Run details" for h in e.get("html"))
    assert REAL_MODEL not in details and "simulated, illustrative" in details


def test_demo_mode_keeps_simulated_scenario(write_drift):
    write_drift()
    at = predict_page(demo=True)
    assert SIMULATED_CHIP in heading(at) and FORECAST_CHIP not in heading(at)
    assert not [b for b in at.button if (b.key or "").startswith("drift_jump_")]  # 4 steps: the slider is enough
