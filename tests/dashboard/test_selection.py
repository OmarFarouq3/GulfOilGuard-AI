"""services.selection: state helpers (with a dict as session state) and map-click parsing."""

from __future__ import annotations

import random

import pytest

from services import inference, mock_data, selection
from services.models import SpillSite
from services.schema import GeoCoordinate

SITES = mock_data.spills().sites
STEP_KEYS = (selection.DETECT_RUN_KEY, selection.DETECT_SIMULATED_KEY, selection.PREDICT_DONE_KEY,
             selection.RESPOND_DONE_KEY)


def click(tooltip=None, lat=0.0, lng=0.0, count=1) -> dict:
    """What st_folium returns for an object click, limited to selection.MAP_CLICK_OBJECTS."""
    return {"last_object_clicked": {"lat": lat, "lng": lng}, "last_object_clicked_count": count,
            "last_object_clicked_tooltip": tooltip}


def fill_downstream(session: dict) -> None:
    session[selection.DETECT_RUN_KEY] = inference.DetectionRun("done", "ok", "x")
    session[selection.PREDICT_DONE_KEY] = True
    session[selection.RESPOND_DONE_KEY] = True
    session[selection.DOWNSTREAM_PREFIX + "future_result"] = 1


# --- State --------------------------------------------------------------------------------


def test_select_spill_stores_spill_and_one_image(session, image_dir):
    selection.select_spill("GOG-SIM-01", rng=random.Random(3))
    chosen = selection.current()
    assert chosen.spill_id == "GOG-SIM-01"
    assert chosen.image_path.parent == image_dir and chosen.image_path.is_file()
    assert chosen.image_id == selection.image_picker.image_id(chosen.image_path)


def test_rerun_does_not_change_the_image(session, image_dir):
    selection.select_spill("GOG-SIM-01")
    first = selection.current()
    for seed in range(20):  # the page selects the same spill again on later reruns
        selection.select_spill("GOG-SIM-01", rng=random.Random(seed))
        selection.handle_map_click(click("GOG-SIM-01"), SITES)
        assert selection.current() == first


def test_select_spill_without_images_keeps_the_spill(session, tmp_path, monkeypatch):
    monkeypatch.setenv("GOG_IMAGE_DIR", str(tmp_path / "missing"))
    selection.select_spill("GOG-SIM-02")
    assert selection.current() == selection.Selection("GOG-SIM-02", None, None)


def test_new_spill_gets_a_different_image(session, image_dir):
    selection.select_spill("GOG-SIM-01")
    first = selection.current().image_path
    selection.select_spill("GOG-SIM-02")
    assert selection.current().image_path != first


@pytest.mark.parametrize("change", [
    lambda: selection.select_spill("GOG-SIM-03"),
    lambda: selection.reroll_image(),
    lambda: selection.clear_selection(),
])
def test_selection_changes_clear_downstream(session, image_dir, change):
    selection.select_spill("GOG-SIM-01")
    fill_downstream(session)
    change()
    assert not [k for k in session if str(k).startswith(selection.DOWNSTREAM_PREFIX)]


def test_reroll_picks_a_different_image_for_the_same_spill(session, image_dir):
    selection.select_spill("GOG-SIM-01")
    before = selection.current()
    for _ in range(10):
        selection.reroll_image()
        after = selection.current()
        assert after.spill_id == before.spill_id and after.image_path != before.image_path
        before = after


def test_reroll_without_selection_does_nothing(session, image_dir):
    selection.reroll_image()
    assert selection.current() == selection.Selection()


IDS = [s.spill_id for s in SITES]
SOURCE = (False, "demo", "demo")


def finish_predict() -> None:
    selection.select_spill("GOG-SIM-01")
    selection.sync(IDS, SOURCE)
    selection.accept_simulated_detection()
    selection.complete_predict()


def test_sync_drops_results_of_another_selection(session, image_dir):
    """Covers selections written to session_state directly (e.g. AppTest, future code)."""
    finish_predict()
    selection.sync(IDS, SOURCE)
    assert selection.predict_done()  # same selection and source: kept
    session[selection.SPILL_KEY] = "GOG-SIM-04"
    selection.sync(IDS, SOURCE)
    assert not [k for k in STEP_KEYS if k in session]


def test_sync_clears_a_selection_that_is_no_longer_offered(session, image_dir):
    """Fix 4: one place validates the stored id; active() then agrees with the pages."""
    finish_predict()
    selection.sync(["GOG-SIM-02", "GOG-SIM-03"], SOURCE)  # GOG-SIM-01 vanished from the list
    assert not selection.active() and selection.current() == selection.Selection()
    assert not [k for k in session if str(k).startswith(selection.DOWNSTREAM_PREFIX)]
    assert selection.step_states() == {"detect": "locked", "predict": "locked", "respond": "locked"}


@pytest.mark.parametrize("new_source", [(True, "demo", "demo"), (False, "outputs", "demo"), (False, "demo", "outputs")])
def test_sync_resets_the_flow_when_the_data_source_changes(session, image_dir, new_source):
    """Fix 5: demo toggle or a new drift / routing origin never keeps steps "done" over other data."""
    finish_predict()
    selection.sync(IDS, new_source)
    assert selection.active()  # the spill itself is still fine
    assert not selection.detection_done() and not selection.predict_done()


def test_sync_undoes_a_model_detection_whose_files_are_gone(session, image_dir, tmp_path, monkeypatch):
    """Fix 6: "done" is re-verified against disk on every run."""
    monkeypatch.setattr(inference.config, "DETECTION_DIR", tmp_path / "det")
    selection.select_spill("GOG-SIM-01")
    selection.sync(IDS, SOURCE)
    for path in inference.output_files("img-1").values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")
    selection.record_detection(inference.DetectionRun("done", "ok", "img-1"))
    selection.complete_predict()
    selection.sync(IDS, SOURCE)
    assert selection.detection_done() and selection.predict_done()
    inference.output_files("img-1")["mask"].unlink()
    selection.sync(IDS, SOURCE)
    assert selection.detection_run() is None and not selection.predict_done()
    assert selection.step_states()["detect"] == "ready"


def test_sync_keeps_a_simulated_detection_without_files(session, image_dir):
    finish_predict()
    selection.sync(IDS, SOURCE)
    assert selection.detection_done() and selection.predict_done()


def test_steps_unlock_in_order(session, image_dir):
    assert selection.step_states() == {"detect": "locked", "predict": "locked", "respond": "locked"}
    selection.select_spill("GOG-SIM-01")
    selection.complete_predict()  # not allowed yet
    selection.complete_respond()
    assert selection.step_states() == {"detect": "ready", "predict": "locked", "respond": "locked"}
    selection.record_detection(inference.DetectionRun("failed", "no", "x"))
    assert selection.step_states()["predict"] == "locked"
    selection.record_detection(inference.DetectionRun("done", "ok", "x"))
    assert selection.step_states() == {"detect": "done", "predict": "ready", "respond": "locked"}
    selection.complete_predict()
    selection.complete_respond()
    assert selection.step_states() == {"detect": "done", "predict": "done", "respond": "done"}
    selection.record_detection(inference.DetectionRun("cached", "ok", "x"))  # new detection resets later steps
    assert selection.step_states() == {"detect": "done", "predict": "ready", "respond": "locked"}


def test_missing_checkpoint_falls_back_to_simulated_detection(session, image_dir):
    selection.select_spill("GOG-SIM-01")
    selection.record_detection(inference.DetectionRun("checkpoint_missing", "none", "x"))
    assert selection.detection_done() and selection.simulated_detection_accepted()


# --- Map clicks ---------------------------------------------------------------------------


def at(site: SpillSite, dlat: float = 0.0, dlon: float = 0.0, **kwargs) -> dict:
    return click(lat=site.location.latitude + dlat, lng=site.location.longitude + dlon, **kwargs)


def test_parse_tooltip_match_wins():
    assert selection.parse_map_click(click(" GOG-SIM-02 ", lat=0, lng=0), SITES) == "GOG-SIM-02"


def test_parse_tooltip_of_another_object_never_selects_a_spill():
    assert selection.parse_map_click(at(SITES[0], tooltip="Skimmer 1"), SITES) is None


def test_parse_nearest_marker_fallback_within_threshold():
    # 0.02° lat ~ 2.2 km from GOG-SIM-01: inside CLICK_RADIUS_KM, and every other site is farther.
    assert selection.parse_map_click(at(SITES[0], dlat=0.02), SITES) == SITES[0].spill_id
    assert selection.parse_map_click(at(SITES[0], dlat=0.02, tooltip=""), SITES) == SITES[0].spill_id


def test_parse_miss_outside_threshold():
    assert selection.parse_map_click(at(SITES[0], dlat=0.2), SITES) is None
    radius_deg = selection.CLICK_RADIUS_KM / 111.0
    assert selection.parse_map_click(at(SITES[0], dlat=radius_deg * 1.05), SITES) is None
    assert selection.parse_map_click(at(SITES[0], dlat=radius_deg * 0.95), SITES) == SITES[0].spill_id


def test_parse_nearest_of_two_close_sites():
    a = SpillSite("A", "A", GeoCoordinate(25.0, 55.0), True)
    b = SpillSite("B", "B", GeoCoordinate(25.0, 55.03), True)
    assert selection.parse_map_click(click(lat=25.0, lng=55.02), [a, b]) == "B"


@pytest.mark.parametrize("payload", [
    None, "click", 42, [], {}, {"last_object_clicked": None}, {"last_object_clicked": "25,55"},
    {"last_object_clicked": {"lat": "x", "lng": 55}}, {"last_object_clicked": {"lat": 25.85}},
    {"last_object_clicked": {"lat": float("nan"), "lng": 55.65}}, {"last_object_clicked_tooltip": 7},
])
def test_parse_malformed_payloads(payload):
    assert selection.parse_map_click(payload, SITES) is None


def test_parse_with_no_sites():
    assert selection.parse_map_click(at(SITES[0]), []) is None


def test_same_click_is_processed_once(session, image_dir):
    first = at(SITES[0], tooltip=SITES[0].spill_id, count=1)
    assert selection.handle_map_click(first, SITES) == SITES[0].spill_id
    image = selection.current().image_path
    for _ in range(5):  # st_folium re-sends the last click on every rerun
        assert selection.handle_map_click(dict(first), SITES) is None
    selection.clear_selection()
    assert selection.handle_map_click(dict(first), SITES) is None  # stale click after clearing
    assert selection.current().spill_id is None
    assert selection.handle_map_click(at(SITES[0], tooltip=SITES[0].spill_id, count=2), SITES) == SITES[0].spill_id
    assert selection.current().image_path is not None and image is not None


def test_fresh_map_resets_click_memory(session, image_dir):
    first = at(SITES[1], tooltip=SITES[1].spill_id, count=1)
    assert selection.handle_map_click(first, SITES) == SITES[1].spill_id
    selection.clear_selection()
    # the map remounts (markers changed) and returns its defaults, then the same first click again
    assert selection.handle_map_click({"last_object_clicked": None, "last_object_clicked_count": None,
                                       "last_object_clicked_tooltip": None}, SITES) is None
    assert selection.handle_map_click(first, SITES) == SITES[1].spill_id


def test_clicking_the_selected_spill_again_keeps_its_image(session, image_dir):
    selection.handle_map_click(at(SITES[0], tooltip=SITES[0].spill_id, count=1), SITES)
    image = selection.current().image_path
    assert selection.handle_map_click(at(SITES[0], tooltip=SITES[0].spill_id, count=2), SITES) is None
    assert selection.current().image_path == image
