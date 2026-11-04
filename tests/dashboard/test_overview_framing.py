"""E3: the Overview only presents Detect and Predict as one incident when the detected slick has a location.

Without outputs/detection/spill.geojson the radar scene has no location, and the forecast starts
from a synthetic release point: the page must say so instead of "Follow one incident". All files
are written into the test outputs folder; nothing reads the real outputs/.
"""

from __future__ import annotations

import json

import pytest
from test_sites import bodies, go, heading, new_app, sites  # noqa: F401  (fixture)

import config
from services import mock_data

NOT_ONE = "Not one incident yet: the radar scene on Detect has no location (no georeferenced slick)"
LINKED = "Follow one incident through the three stages of the response."


def section(at, title: str) -> str:
    return next(b for b in bodies(at, "gog-section") if f"<h3>{title}</h3>" in b)


@pytest.fixture
def spill_file():
    """A valid outputs/detection/spill.geojson (the demo slick outline, labelled synthetic); removed afterwards."""
    config.DETECTION_DIR.mkdir(parents=True, exist_ok=True)
    config.DETECTION_FILES["spill"].write_text(json.dumps(mock_data.spill_outline()), encoding="utf-8")
    yield
    config.DETECTION_FILES["spill"].unlink(missing_ok=True)


def test_without_spill_geojson_the_overview_says_it_is_not_one_incident():
    at = new_app()
    flow = section(at, "Response flow")
    assert NOT_ONE in flow and "starts from a synthetic release point" in flow and LINKED not in flow
    assert "Incident response flow" not in " ".join(bodies(at, "gog-section"))
    choose = section(at, "Choose an incident")
    assert "start from a synthetic release point there" in choose and "not taken at that point" in choose
    cards = " ".join(bodies(at, "gog-stage-num"))
    assert "where oil released at a synthetic point goes over 24 hours" in cards


def test_the_selected_sites_release_point_is_named(sites):
    sites("S1", "S2")
    flow = section(new_app("S2"), "Response flow")
    assert "starts from a synthetic release point at 25.700° N, 55.400° E, not from that scene" in flow


def test_the_single_forecast_release_point_is_named():
    from test_drift_page import drift_files
    collection, meta = drift_files()
    config.DRIFT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        config.DRIFT_FILES["drift"].write_text(json.dumps(collection), encoding="utf-8")
        config.DRIFT_FILES["meta"].write_text(json.dumps(meta), encoding="utf-8")
        flow = section(new_app(), "Response flow")
        assert "synthetic release point at 25.850° N, 55.650° E" in flow
    finally:
        for path in config.DRIFT_DIR.glob("*"):
            path.unlink()


def test_with_spill_geojson_the_linked_framing_stays(spill_file):
    at = new_app()
    assert LINKED in section(at, "Incident response flow")
    assert NOT_ONE not in " ".join(bodies(at, "gog-section"))
    assert "forecasts where the oil goes over 24 hours" in " ".join(bodies(at, "gog-stage-num"))


def test_demo_scenario_keeps_the_linked_framing_and_its_label():
    at = new_app(demo=True)
    assert LINKED in section(at, "Incident response flow")
    hero = " ".join(bodies(at, "gog-hero"))
    assert "Simulated scenario" in hero


def test_predict_subtitle_follows_the_same_rule(sites, spill_file):
    sites("S1")
    at = go(new_app(), "views/drift.py")
    assert "drift simulation of the slick" in heading(at)
    config.DETECTION_FILES["spill"].unlink()
    at = go(new_app(), "views/drift.py")
    assert "drift simulation of oil released at the spill site" in heading(at)
    assert "of the slick" not in heading(at)
