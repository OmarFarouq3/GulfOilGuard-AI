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

from services import image_picker, inference, selection

OVERVIEW, DETECT, PREDICT, RESPOND = "views/overview.py", "views/detection.py", "views/drift.py", "views/cleanup.py"
LOCKED = "This step is locked"
SIMULATED_CHIP = "Simulated scenario"


def checked(at: AppTest) -> AppTest:
    assert not at.exception, [e.message for e in at.exception]
    return at


def open_page(at: AppTest, page: str) -> AppTest:
    at.switch_page(page)
    return checked(at.run())


def new_app(demo: bool = False) -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=120)
    at.session_state["demo_mode"] = demo
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


# --- Overview -------------------------------------------------------------------------------


@pytest.mark.parametrize("folder", ["missing", "empty"])
def test_overview_without_images_shows_empty_state(tmp_path, monkeypatch, folder):
    directory = tmp_path / folder
    if folder == "empty":
        directory.mkdir()
    monkeypatch.setenv("GOG_IMAGE_DIR", str(directory))
    at = checked(new_app().run())
    assert "No incident selected yet" in page_text(at)
    select(at, "GOG-SIM-01", None)
    text = page_text(checked(at.run()))
    assert "No radar images found" in text and folder in text and "GOG_IMAGE_DIR" in text
    assert "Continue to Detect" not in text  # the flow stops at the empty state
    assert "This step is locked" not in page_text(open_page(at, DETECT))  # Detect offers the simulated route
    assert button(at, "flow_detect_simulated")


def test_overview_shows_the_assigned_image_with_caption_and_is_stable(images):
    at = new_app()
    select(at, "GOG-SIM-02", images[1])
    text = page_text(checked(at.run()))
    assert "not geolocated to this spill" in text and images[1].name in text
    assert "North of Ras Al Khaimah (simulated)" in text and SIMULATED_CHIP in text
    for _ in range(3):  # reruns never draw a new image
        checked(at.run())
        assert at.session_state[selection.IMAGE_PATH_KEY] == str(images[1])


# --- The three steps --------------------------------------------------------------------------


@pytest.mark.parametrize("demo", [False, True], ids=["demo-off", "demo-on"])
def test_detect_predict_respond_unlock_in_order(images, stub_detection, demo):
    at = new_app(demo)
    select(at, "GOG-SIM-04", images[0])
    checked(at.run())

    assert LOCKED in page_text(open_page(at, PREDICT))
    assert LOCKED in page_text(open_page(at, RESPOND))

    text = page_text(open_page(at, DETECT))
    assert "Selected radar image" in text and LOCKED not in text
    button(at, "flow_run_detection").click()
    text = page_text(checked(at.run()))
    assert stub_detection == [image_picker.image_id(images[0])]
    assert "U-Net prediction" in text and "Simulated slick outline" in text and SIMULATED_CHIP in text

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

    assert selection.step_states.__name__  # all three done: overview shows the progress
    assert page_text(open_page(at, OVERVIEW)).count("gog-progress-done") == 3


def test_missing_checkpoint_falls_back_to_simulated_and_unlocks_predict(images):
    at = new_app()
    select(at, "GOG-SIM-01", images[0])
    open_page(at, DETECT)
    button(at, "flow_run_detection").click()
    text = page_text(checked(at.run()))
    assert "No trained detection model" in text and "demo scene" in text and "Traceback" not in text
    assert LOCKED not in page_text(open_page(at, PREDICT))


def test_failed_detection_keeps_predict_locked_and_offers_simulated(images, monkeypatch):
    monkeypatch.setattr(inference, "run_detection", lambda *a, **k: inference.DetectionRun(
        "failed", "Detection failed (exit code 4).", "x", detail="Traceback (most recent call last): boom"))
    at = new_app()
    select(at, "GOG-SIM-01", images[0])
    open_page(at, DETECT)
    button(at, "flow_run_detection").click()
    checked(at.run())
    assert at.expander, "technical details belong in an expander"
    assert "Detection failed (exit code 4)." in page_text(at)
    assert LOCKED in page_text(open_page(at, PREDICT))
    open_page(at, DETECT)
    button(at, "flow_detect_simulated").click()
    checked(at.run())
    assert LOCKED not in page_text(open_page(at, PREDICT))


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
