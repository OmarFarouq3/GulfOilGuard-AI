"""The click -> image -> Detect / Predict / Respond flow, through the real app with AppTest.

The folium map cannot be clicked in AppTest, so a click's outcome is simulated by writing the
selection keys to session_state (what selection.select_spill stores). Detection is stubbed by
replacing services.inference.run_detection, which AppTest's script run shares with this test.
"""

from __future__ import annotations

import numpy as np
import pytest
from dashboard_testkit import APP, make_image_dir, page_text
from PIL import Image
from streamlit.testing.v1 import AppTest

from components.labels import slick_tooltip
from components.nav import STEP_HELP
from services import image_picker, inference, selection
from services.scenario import SIMULATED_OUTLINE

OVERVIEW, DETECT, PREDICT, RESPOND = "views/overview.py", "views/detection.py", "views/drift.py", "views/cleanup.py"
LOCKED = "This step is locked"
SIMULATED_CHIP = "Simulated scenario"
TRACEBACK = "Traceback (most recent call last): secret/path/boom.py"


def checked(at: AppTest) -> AppTest:
    assert not at.exception, [e.message for e in at.exception]
    return at


def open_page(at: AppTest, page: str) -> AppTest:
    at.switch_page(page)
    return checked(at.run())


def new_app(demo: bool = False, dev: bool = False) -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=120)
    at.session_state["demo_mode"] = demo
    if dev:
        at.query_params["dev"] = "1"
    return at


def select(at: AppTest, spill_id: str, image) -> None:
    """The state a map click leaves behind (selection.select_spill), followed by the click's rerun.

    The rerun also matters for AppTest: a switch_page before the first run is ignored.
    """
    at.session_state[selection.SPILL_KEY] = spill_id
    at.session_state[selection.IMAGE_PATH_KEY] = str(image) if image else None
    at.session_state[selection.IMAGE_ID_KEY] = image_picker.image_id(image) if image else None
    checked(at.run())


def keys(at: AppTest) -> set[str]:
    return {k for k in (selection.DETECT_RUN_KEY, selection.DETECT_SIMULATED_KEY, selection.PREDICT_DONE_KEY,
                        selection.RESPOND_DONE_KEY) if k in at.session_state}


def button(at: AppTest, key: str):
    matches = [b for b in at.button if b.key == key]
    assert matches, f"button {key!r} not on the page"
    return matches[0]


def has_button(at: AppTest, key: str) -> bool:
    return any(b.key == key for b in at.button)


def html_bodies(at: AppTest, css_class: str) -> list[str]:
    """Bodies of the st.html elements that carry ``css_class`` (one specific card, not the page)."""
    return [h.proto.body for h in at.get("html") if f'class="{css_class}' in h.proto.body
            or f" {css_class}" in h.proto.body.split(">", 1)[0]]


def expanders(at: AppTest) -> list[str]:
    return [e.label for e in at.expander]


@pytest.fixture
def images(tmp_path, monkeypatch):
    directory = make_image_dir(tmp_path / "images")
    monkeypatch.setenv("GOG_IMAGE_DIR", str(directory))
    monkeypatch.setenv("GOG_CHECKPOINT", str(tmp_path / "no-model.pth"))  # never the real model here
    return sorted(directory.glob("*.png"))


@pytest.fixture
def stub_detection(monkeypatch):
    """Replace the subprocess run with one that writes the result files the loader expects."""
    calls = []

    def fake(image_path, image_id, **kwargs):
        calls.append(image_id)
        for kind, path in inference.output_files(image_id).items():
            path.parent.mkdir(parents=True, exist_ok=True)
            pixels = np.full((12, 16), 255 if kind == "mask" else 90, dtype=np.uint8)
            Image.fromarray(pixels).save(path)
        return inference.DetectionRun("done", "Detection finished.", image_id,
                                      info={"threshold": 0.5, "oil_fraction": 1.0, "checkpoint": "stub.pth"})

    monkeypatch.setattr(inference, "run_detection", fake)
    yield calls
    for path in inference.config.DETECTION_DIR.glob("*"):
        path.unlink()


@pytest.fixture
def failing_detection(monkeypatch):
    monkeypatch.setattr(inference, "run_detection", lambda *a, **k: inference.DetectionRun(
        "failed", "Detection failed (exit code 4).", "x", detail=TRACEBACK))


def run_all_steps(at: AppTest) -> None:
    open_page(at, DETECT)
    button(at, "flow_run_detection").click()
    checked(at.run())
    open_page(at, PREDICT)
    button(at, "flow_run_predict").click()
    checked(at.run())
    open_page(at, RESPOND)
    button(at, "flow_run_respond").click()
    checked(at.run())


# --- Overview -------------------------------------------------------------------------------


@pytest.mark.parametrize("folder", ["missing", "empty"])
def test_overview_without_images_shows_the_empty_state_card(tmp_path, monkeypatch, folder):
    directory = tmp_path / folder
    if folder == "empty":
        directory.mkdir()
    monkeypatch.setenv("GOG_IMAGE_DIR", str(directory))
    at = checked(new_app().run())
    assert "No incident selected yet" in page_text(at)
    assert not html_bodies(at, "gog-images-missing")  # only once a spill is selected
    select(at, "GOG-SIM-01", None)
    cards = html_bodies(at, "gog-images-missing")
    assert len(cards) == 1
    card = cards[0]
    assert "No radar images found" in card and str(directory) in card and "GOG_IMAGE_DIR" in card
    assert ".png" in card and ".jpg" in card
    assert not [p for p in at.get("page_link") if p.proto.label == "Continue to Detect"]
    open_page(at, DETECT)
    assert LOCKED not in page_text(at) and has_button(at, "flow_detect_simulated")


def test_overview_shows_the_assigned_image_with_caption(images):
    at = new_app()
    select(at, "GOG-SIM-02", images[1])
    captions = [str(i.proto) for i in at.get("image")]
    assert any("not geolocated to this spill" in c and images[1].name in c for c in captions)
    assert "North of Ras Al Khaimah (simulated)" in page_text(at)


def test_overview_legend_names_simulated_sites(images):
    at = checked(new_app().run())
    legend = " ".join(html_bodies(at, "gog-legend"))
    assert "Simulated spill site" in legend and "Reported spill" not in legend


def test_overview_numbers_are_labelled_simulated_with_results(images, stub_detection):
    """Fix A1: demo off, a selected spill run through all steps -> the headline numbers carry the label."""
    at = new_app(demo=False)
    select(at, "GOG-SIM-01", images[0])
    run_all_steps(at)
    open_page(at, OVERVIEW)
    status = html_bodies(at, "gog-kpi-status")
    assert len(status) == 1 and SIMULATED_CHIP in status[0]
    hero = html_bodies(at, "gog-hero")
    assert hero and "gog-chip-sim" in hero[0]


def test_overview_numbers_unlabelled_when_there_are_no_results(images):
    at = checked(new_app(demo=False).run())  # no selection, no outputs files: nothing simulated shown
    assert not html_bodies(at, "gog-kpi-status")


# --- The three steps --------------------------------------------------------------------------


@pytest.mark.parametrize("demo", [False, True], ids=["demo-off", "demo-on"])
def test_detect_predict_respond_unlock_in_order(images, stub_detection, demo):
    at = new_app(demo)
    select(at, "GOG-SIM-04", images[0])

    assert LOCKED in page_text(open_page(at, PREDICT))
    assert LOCKED in page_text(open_page(at, RESPOND))

    text = page_text(open_page(at, DETECT))
    assert "Selected radar image" in text and LOCKED not in text
    button(at, "flow_run_detection").click()
    text = page_text(checked(at.run()))
    assert stub_detection == [image_picker.image_id(images[0])]
    assert "U-Net prediction" in text and "Simulated slick outline" in text and SIMULATED_CHIP in text
    assert SIMULATED_OUTLINE in text  # the outline's tooltip, not "Scene: <image_id>"

    assert LOCKED in page_text(open_page(at, RESPOND))  # still locked: Predict not done
    text = page_text(open_page(at, PREDICT))
    assert LOCKED not in text
    button(at, "flow_run_predict").click()
    text = page_text(checked(at.run()))
    assert "Simulated drift scenario, positioned at the selected spill" in text and SIMULATED_CHIP in text

    text = page_text(open_page(at, RESPOND))
    assert LOCKED not in text
    button(at, "flow_run_respond").click()
    text = page_text(checked(at.run()))
    assert "Simulated response plan" in text and SIMULATED_CHIP in text and at.dataframe

    assert page_text(open_page(at, OVERVIEW)).count("gog-progress-done") == 3


def test_simulated_outline_tooltip_never_names_the_scene():
    assert "image_id" not in slick_tooltip(outline_simulated=True)
    assert "outline" in slick_tooltip(outline_simulated=True)
    assert "image_id" in slick_tooltip(outline_simulated=False)


def test_missing_checkpoint_falls_back_to_simulated_and_unlocks_predict(images):
    at = new_app()
    select(at, "GOG-SIM-01", images[0])
    open_page(at, DETECT)
    button(at, "flow_run_detection").click()
    text = page_text(checked(at.run()))
    assert "No trained detection model" in text and "GOG_CHECKPOINT" in text and "demo scene" in text
    assert "no-model.pth" not in text  # the path is a technical detail (?dev=1 only)
    assert LOCKED not in page_text(open_page(at, PREDICT))


def test_failed_detection_hides_technical_details_without_dev(images, failing_detection):
    """Fix 10: the traceback is not anywhere in the page tree (not even in a collapsed expander)."""
    at = new_app(dev=False)
    select(at, "GOG-SIM-01", images[0])
    open_page(at, DETECT)
    button(at, "flow_run_detection").click()
    text = page_text(checked(at.run()))
    assert "Detection failed (exit code 4)." in text
    assert "Traceback" not in text and "secret/path" not in text
    assert "Technical details" not in expanders(at)
    assert LOCKED in page_text(open_page(at, PREDICT))
    open_page(at, DETECT)
    button(at, "flow_detect_simulated").click()
    checked(at.run())
    assert LOCKED not in page_text(open_page(at, PREDICT))


def test_failed_detection_shows_technical_details_with_dev(images, failing_detection):
    at = new_app(dev=True)
    select(at, "GOG-SIM-01", images[0])
    open_page(at, DETECT)
    button(at, "flow_run_detection").click()
    checked(at.run())
    details = [e for e in at.expander if e.label == "Technical details"]
    assert len(details) == 1
    assert [c.value for c in details[0].code] == [TRACEBACK]


def test_setup_needed_names_both_variables_and_offers_simulated(images, monkeypatch):
    """Fix 19: no torch in the dashboard's Python -> a setup message, plus the simulated route."""
    monkeypatch.setattr(inference, "run_detection", lambda *a, **k: inference.DetectionRun(
        "setup_needed", inference._setup_message(), "x", detail=TRACEBACK))
    at = new_app()
    select(at, "GOG-SIM-01", images[0])
    open_page(at, DETECT)
    button(at, "flow_run_detection").click()
    text = page_text(checked(at.run()))
    assert "GOG_DETECTION_PYTHON" in text and "GOG_CHECKPOINT" in text and "Traceback" not in text
    assert has_button(at, "flow_detect_simulated")


# --- Selection changes reset the flow -----------------------------------------------------------


def finish_detection_and_predict(at: AppTest) -> None:
    open_page(at, DETECT)
    button(at, "flow_run_detection").click()
    checked(at.run())
    open_page(at, PREDICT)
    button(at, "flow_run_predict").click()
    checked(at.run())
    assert selection.PREDICT_DONE_KEY in keys(at)


def test_new_spill_resets_downstream(images, stub_detection):
    at = new_app()
    select(at, "GOG-SIM-01", images[0])
    finish_detection_and_predict(at)
    select(at, "GOG-SIM-03", images[0])  # another map click
    assert LOCKED in page_text(open_page(at, PREDICT))
    assert not keys(at)


def test_reroll_resets_downstream(images, stub_detection):
    at = new_app()
    select(at, "GOG-SIM-01", images[0])
    finish_detection_and_predict(at)
    open_page(at, OVERVIEW)
    button(at, "sel_reroll_image").click()
    checked(at.run())
    assert at.session_state[selection.IMAGE_PATH_KEY] != str(images[0])
    assert not keys(at)
    assert LOCKED in page_text(open_page(at, PREDICT))


def test_unknown_spill_is_cleared_everywhere(images, stub_detection):
    """Fix 4: a spill id that is no longer offered clears the selection before anything renders."""
    at = new_app()
    select(at, "GOG-SIM-01", images[0])
    finish_detection_and_predict(at)
    at.session_state[selection.SPILL_KEY] = "GONE-01"
    text = page_text(open_page(at, PREDICT))
    assert selection.SPILL_KEY not in at.session_state and not keys(at)
    assert "No incident selected" in text
    assert not any(help_text in text for help_text in STEP_HELP.values())  # timeline shows no old progress


def test_demo_toggle_resets_the_flow(images, stub_detection):
    """Fix 5: the options-panel toggle (real widget + callback) drops the steps done on other data."""
    at = new_app(demo=False)
    select(at, "GOG-SIM-01", images[0])
    finish_detection_and_predict(at)
    at.toggle(key="_demo_toggle").set_value(True)
    checked(at.run())
    assert at.session_state["demo_mode"] is True
    assert at.session_state[selection.SPILL_KEY] == "GOG-SIM-01"  # still offered in demo mode
    assert not keys(at)
    assert LOCKED in page_text(open_page(at, PREDICT))


def test_detection_files_removed_on_disk_reopen_the_step(images, stub_detection):
    """Fix 6: a "done" model detection is re-verified against disk on every render."""
    at = new_app()
    select(at, "GOG-SIM-01", images[0])
    finish_detection_and_predict(at)
    image_id = image_picker.image_id(images[0])
    inference.output_files(image_id)["mask"].unlink()
    open_page(at, DETECT)
    assert has_button(at, "flow_run_detection")
    assert selection.DETECT_RUN_KEY not in at.session_state
    assert LOCKED in page_text(open_page(at, PREDICT))


def test_clear_selection_returns_pages_to_the_latest_results(images):
    at = new_app(demo=True)
    select(at, "GOG-SIM-01", images[0])
    open_page(at, OVERVIEW)
    button(at, "sel_clear").click()
    checked(at.run())
    assert selection.SPILL_KEY not in at.session_state
    text = page_text(open_page(at, PREDICT))
    assert "No incident selected" in text and SIMULATED_CHIP in text  # demo results are shown again


@pytest.mark.parametrize("demo", [False, True], ids=["demo-off", "demo-on"])
def test_every_page_renders_without_selection(images, demo):
    at = checked(new_app(demo).run())
    for page in (DETECT, PREDICT, RESPOND, OVERVIEW):
        text = page_text(open_page(at, page))
        if page != OVERVIEW:
            assert "No incident selected" in text
