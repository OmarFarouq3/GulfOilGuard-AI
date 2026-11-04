"""The Overview's spill list: the same choice as a marker click, without the map (which needs internet).

One source of truth: services.selection.SPILL_KEY. Choosing in the list sets exactly what a marker click
sets, and a marker click shows in the list. Every page then shows the chosen site's own release point,
run id and figures, compared here with the real files in outputs/sites/<id>/.
"""

from __future__ import annotations

import json

import pytest
from dashboard_testkit import page_text
from test_no_team_names import REAL, needs_real, real_outputs, tree_text  # noqa: F401  (fixture)
from test_sites import go, new_app

from components import incident, ui
from services import selection

SITES = ("S1", "S2", "S3", "S4")
DOWNSTREAM = (selection.DETECT_RUN_KEY, selection.DETECT_SIMULATED_KEY, selection.PREDICT_DONE_KEY,
              selection.RESPOND_DONE_KEY)

pytestmark = needs_real


def files(site: str) -> dict:
    base = REAL / "sites" / site
    meta = json.loads((base / "drift" / "meta.json").read_text(encoding="utf-8"))
    summary = json.loads((base / "routing" / "summary.json").read_text(encoding="utf-8"))
    routes = json.loads((base / "routing" / "routes.geojson").read_text(encoding="utf-8"))["features"]
    loc = meta["initial_location"]
    return {"meta": meta, "where": ui.coordinates(loc["latitude"], loc["longitude"]),
            "scenario": summary["scenario_id"], "vessels": [r["properties"]["vessel_id"] for r in routes],
            "finish": max(r["properties"]["finish_hours"] for r in routes)}


def site_list(at):
    return at.selectbox(key=incident.SITE_SELECT_KEY)


def choose(at, value: str):
    site_list(at).set_value(value).run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def overview() -> object:
    at = new_app()  # Overview, no spill selected
    assert site_list(at).value == incident.NO_INCIDENT
    return at


def walk_to_respond(at):
    """Detect (simulated: no radar images in the test layout) -> Predict -> Respond, by their buttons."""
    go(at, "views/detection.py", "flow_detect_simulated")
    predict = page_text(go(at, "views/drift.py", "flow_run_predict"))
    respond = page_text(go(at, "views/cleanup.py", "flow_run_respond"))
    return predict, respond


def test_the_list_offers_every_marker_and_no_incident(real_outputs):
    at = overview()
    options = site_list(at).options
    assert options[0] == incident.NO_INCIDENT_LABEL
    for site in SITES:
        assert f"Site {site} · precomputed run from a hypothetical release at {files(site)['where']}" in options
    assert len(options) == 1 + len(SITES)
    assert site_list(at).label == "Spill site"  # a labelled control


@pytest.mark.parametrize("site", SITES)
def test_choosing_a_site_sets_what_a_marker_click_sets(real_outputs, site):
    at = choose(overview(), site)
    by_list = {k: at.session_state[k] for k in (selection.SPILL_KEY, selection.IMAGE_PATH_KEY, selection.IMAGE_ID_KEY)
               if k in at.session_state}
    click = new_app()  # a marker click: services.selection.select_spill, as handle_map_click calls it
    click.session_state[selection.SPILL_KEY] = site
    click.run()
    assert by_list == {selection.SPILL_KEY: site}  # no radar images in the test layout, so no image either
    assert site_list(click).value == site  # ...and the click shows in the list
    assert not [k for k in DOWNSTREAM if k in at.session_state]


@pytest.mark.parametrize("site", SITES)
def test_every_page_shows_the_chosen_sites_own_files(real_outputs, site):
    want = files(site)
    at = choose(overview(), site)
    text = page_text(at)
    assert want["meta"]["simulation_id"] in text and want["where"] in text  # side panel
    predict, respond = walk_to_respond(at)
    assert want["meta"]["simulation_id"] in predict and want["where"] in predict
    assert want["scenario"] in respond and all(v in respond for v in want["vessels"])
    assert f">{want['finish']:.1f}<" in respond  # response time tile: the largest finish_hours
    others = [s for s in SITES if s != site]
    assert not any(files(o)["meta"]["simulation_id"] in predict + respond for o in others)


def test_a_to_b_to_a_leaves_no_trace_of_the_first_run(real_outputs):
    at = choose(overview(), "S1")
    walk_to_respond(at)
    assert at.session_state[selection.RESPOND_DONE_KEY]
    go(at, "views/overview.py")
    choose(at, "S2")
    assert not [k for k in DOWNSTREAM if k in at.session_state]
    choose(at, "S1")
    assert not [k for k in DOWNSTREAM if k in at.session_state]  # S1's earlier steps are not restored
    predict = page_text(go(at, "views/drift.py"))
    assert "This step is locked" in predict and files("S2")["meta"]["simulation_id"] not in predict


def test_no_incident_clears_the_selection(real_outputs):
    at = choose(overview(), "S3")
    choose(at, incident.NO_INCIDENT)
    assert selection.SPILL_KEY not in at.session_state
    for page in ("views/detection.py", "views/drift.py", "views/cleanup.py"):
        assert "No incident selected" in page_text(go(at, page))


def test_a_marker_click_after_a_list_choice_wins_and_shows_in_the_list(real_outputs):
    at = choose(overview(), "S1")
    selection_click = "S4"
    at.session_state[selection.SPILL_KEY] = selection_click  # what handle_map_click -> select_spill leaves
    at.run()
    assert site_list(at).value == selection_click


def test_page_switches_keep_the_choice(real_outputs):
    at = choose(overview(), "S2")
    for page in ("views/detection.py", "views/drift.py", "views/cleanup.py", "views/overview.py"):
        go(at, page)
        assert at.session_state[selection.SPILL_KEY] == "S2"
    assert site_list(at).value == "S2"


def test_demo_mode_lists_the_illustrative_demo_spills(real_outputs):
    at = new_app(demo=True)
    options = site_list(at).options
    assert options[0] == incident.NO_INCIDENT_LABEL
    assert all("illustrative demo scenario" in o for o in options[1:]) and len(options) > 1
    choose(at, "GOG-SIM-02")
    assert at.session_state[selection.SPILL_KEY] == "GOG-SIM-02"


def test_the_map_keeps_its_place_and_explains_itself_offline(real_outputs):
    at = overview()
    note = [h.proto.body for h in at.get("html") if h.proto.body.startswith('<div class="gog-map-offline"')]
    assert note == [f'<div class="gog-map-offline" aria-hidden="true">{incident.MAP_OFFLINE}</div>']
    from dashboard_testkit import DASHBOARD_DIR
    css = (DASHBOARD_DIR / "assets" / "styles.css").read_text(encoding="utf-8")
    assert ".st-key-gog-overview-map { position: relative; min-height: 480px; }" in css


def test_a_fresh_session_starts_with_no_incident(real_outputs):
    choose(overview(), "S1")
    fresh = new_app()  # a reload or a second tab is a new session
    assert site_list(fresh).value == incident.NO_INCIDENT and selection.SPILL_KEY not in fresh.session_state
    assert "No incident selected yet" in tree_text(fresh)
