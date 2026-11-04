"""A slow, timed-out or failed detection run always says what is happening; the panel is never blank.

Run detection starts the model in a worker thread (services.inference.start_detection). While it runs,
Detect says "still running" next to the selected image, across reruns and page changes. A run that
fails or times out shows the saved result for the image when there is one ("couldn't run this time"),
else an explicit "couldn't run" message with the retry and simulated options.
"""

from __future__ import annotations

import html
import json
import threading

import config
import pytest
from dashboard_testkit import DASHBOARD_DIR, make_image, page_text
from test_flow_apptest import (DETECT, MIXED_CHIP, PREDICT, button, checked, has_button, heading, html_bodies,  # noqa: F401
                               images, new_app, open_page, select)
from test_inference import FakeRun

from components import flow
from services import image_picker, inference, selection

RUNNING = "Detection is still running on this image"
COULDNT = "Detection couldn't run"
PANELS = ("Radar image", "Detected oil (white)", "Overlay")


@pytest.fixture(autouse=True)
def clean_folders(monkeypatch):
    monkeypatch.setattr(flow, "QUICK_WAIT_S", 0.2)  # the stubs below finish at once or never
    yield
    for directory in (config.DETECTION_DIR, config.LIVE_DETECTION_DIR):
        for path in directory.glob("*"):
            path.unlink()


def write_scene(directory, image_id: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for kind in ("image", "mask", "overlay"):
        make_image(directory / f"{image_id}_{kind}.png", seed=3)


def stub(monkeypatch, result=None, gate: threading.Event | None = None, raises: Exception | None = None):
    """Replace the model run: optionally wait for ``gate``, then return ``result(image_id)`` or raise."""
    def fake(image_path, image_id, **kwargs):
        if gate is not None:
            gate.wait(30)
        if raises:
            raise raises
        return result(image_id)
    monkeypatch.setattr(inference, "run_detection", fake)


def done(image_id):
    for kind, path in inference.output_files(image_id).items():
        make_image(path, seed=5)
    return inference.DetectionRun("done", "Detection finished.", image_id, info={"checkpoint": "stub.pth"})


def timeout(image_id):
    return inference.DetectionRun("timeout", "Detection did not finish within 300 s.", image_id, detail="cmd")


def failed(image_id):
    return inference.DetectionRun("failed", "Detection could not be completed.", image_id, detail="Traceback")


def start(at, image) -> str:
    select(at, "GOG-SIM-01", image)
    open_page(at, DETECT)
    button(at, "flow_run_detection").click()
    return page_text(checked(at.run()))


def notices(at) -> str:
    return html.unescape(" ".join(html_bodies(at, "gog-notice")))


def test_a_slow_run_says_it_is_still_running_then_shows_the_result(images, monkeypatch):
    gate = threading.Event()
    stub(monkeypatch, done, gate=gate)
    at = new_app()
    text = start(at, images[0])
    assert RUNNING in text and "It stops after 300 s" in text
    assert "Selected radar image" in text  # the panel shows the image being read, not nothing
    assert not has_button(at, "flow_run_detection") and has_button(at, "flow_detect_simulated")
    assert selection.DETECT_JOB_KEY in at.session_state

    open_page(at, PREDICT)  # leaving and coming back keeps the run and the message
    text = page_text(open_page(at, DETECT))
    assert RUNNING in text

    gate.set()
    at.session_state[selection.DETECT_JOB_KEY].future.result(timeout=10)
    text = page_text(checked(at.run()))
    assert RUNNING not in text and "Detection finished." in text
    assert all(panel in text for panel in PANELS)
    assert selection.DETECT_JOB_KEY not in at.session_state


def test_a_timeout_shows_the_saved_result_for_the_image(images, monkeypatch):
    image_id = image_picker.image_id(images[0])
    write_scene(config.DETECTION_DIR, image_id)  # the saved result in outputs/detection/
    before = {p.name: p.read_bytes() for p in config.DETECTION_DIR.glob("*")}
    stub(monkeypatch, timeout)
    at = new_app()
    text = start(at, images[0])
    message = notices(at)
    assert f"{COULDNT} this time." in message and "did not finish within 300 s" in message
    assert flow.SAVED_RESULT in message
    assert all(panel in text for panel in PANELS)  # the saved image, mask and overlay
    assert MIXED_CHIP in heading(at)  # a model mask on a real image, location simulated
    assert "the saved U-Net result for this image" in text  # provenance says where the mask is from
    assert has_button(at, "flow_retry_detection")
    assert at.session_state[selection.DETECT_RUN_KEY].saved_dir == config.DETECTION_DIR
    assert "Continue to Predict" in text  # Predict can go on from the saved result
    assert {p.name: p.read_bytes() for p in config.DETECTION_DIR.glob("*")} == before


def test_a_failure_without_a_saved_result_says_so_and_offers_the_options(images, monkeypatch):
    stub(monkeypatch, failed)
    at = new_app()
    text = start(at, images[0])
    message = notices(at)
    assert f"{COULDNT}. Detection could not be completed. {flow.NO_SAVED_RESULT}" in message
    assert "Traceback" not in text  # technical detail only with ?dev=1
    assert "Selected radar image" in text
    assert has_button(at, "flow_run_detection") and has_button(at, "flow_detect_simulated")
    assert "Continue to Predict" not in text


def test_a_crashed_worker_is_a_failure_message_not_a_blank_page(images, monkeypatch):
    stub(monkeypatch, raises=RuntimeError("boom"))
    at = new_app()
    text = start(at, images[0])
    assert f"{COULDNT}. Detection could not be completed." in notices(at)
    assert "boom" not in text and RUNNING not in text


def test_choosing_the_simulated_detection_while_running_drops_the_run(images, monkeypatch):
    gate = threading.Event()
    stub(monkeypatch, done, gate=gate)
    at = new_app()
    start(at, images[0])
    button(at, "flow_detect_simulated").click()
    text = page_text(checked(at.run()))
    gate.set()
    assert RUNNING not in text and selection.DETECT_JOB_KEY not in at.session_state
    assert "Continue to Predict" in text


# --- services.inference: the fallback order ------------------------------------------------------


@pytest.fixture
def model_files(tmp_path, monkeypatch):
    image = make_image(tmp_path / "scene.png")
    checkpoint = tmp_path / "best.pth"
    checkpoint.write_bytes(b"x")
    monkeypatch.setenv("GOG_CHECKPOINT", str(checkpoint))
    return image, checkpoint


def test_saved_result_prefers_the_last_live_run_then_outputs(model_files, monkeypatch):
    image, checkpoint = model_files
    assert inference.saved_result_dir(image, "scene") is None
    write_scene(config.DETECTION_DIR, "scene")
    assert inference.saved_result_dir(image, "scene") == config.DETECTION_DIR
    monkeypatch.setattr(inference.subprocess, "run", FakeRun())
    assert inference.run_detection(image, "scene", checkpoint=checkpoint).state == "done"  # a live run, cached
    assert inference.saved_result_dir(image, "scene") == config.LIVE_DETECTION_DIR
    checkpoint.write_bytes(b"another model")  # a live run with another model is not this model's result
    import os
    os.utime(checkpoint, (1, 1))
    assert inference.saved_result_dir(image, "scene") == config.DETECTION_DIR


@pytest.mark.parametrize("state, falls_back", [("timeout", True), ("failed", True), ("setup_needed", True),
                                               ("checkpoint_missing", False), ("image_unreadable", False),
                                               ("done", False)])
def test_only_runs_that_could_not_finish_fall_back(model_files, state, falls_back):
    image, _checkpoint = model_files
    write_scene(config.DETECTION_DIR, "scene")
    run = inference.with_saved_result(inference.DetectionRun(state, "m", "scene"), image)
    assert (run.saved_dir == config.DETECTION_DIR) is falls_back


def test_job_wait_returns_none_while_running_and_the_result_after(model_files, monkeypatch):
    image, _checkpoint = model_files
    gate = threading.Event()
    stub(monkeypatch, timeout, gate=gate)
    write_scene(config.DETECTION_DIR, "scene")
    job = inference.start_detection(image, "scene")
    assert job.wait(0.05) is None and job.elapsed_s() >= 0
    gate.set()
    result = job.wait(10)
    assert result.state == "timeout" and result.saved_dir == config.DETECTION_DIR


def test_a_slow_rerun_is_labelled_updating():
    """Streamlit's running indicator is hidden; the stylesheet says "Updating" while old elements are stale."""
    css = (DASHBOARD_DIR / "assets" / "styles.css").read_text(encoding="utf-8")
    assert '[data-testid="stStatusWidget"] { display: none !important; }' in css
    rule = css[css.index('.stApp:has([data-stale="true"])'):]
    assert 'content: "Updating\\2026"' in rule[:rule.index("}")]


def test_the_timeout_is_still_enforced_by_the_subprocess(model_files, monkeypatch):
    """The worker thread runs the same run_detection: its subprocess timeout becomes a 'timeout' status."""
    import subprocess
    image, checkpoint = model_files
    monkeypatch.setattr(inference.subprocess, "run", FakeRun(raises=subprocess.TimeoutExpired("cmd", 3)))
    job = inference.start_detection(image, "scene", checkpoint=checkpoint, timeout_s=3)
    result = job.wait(10)
    assert result.state == "timeout" and "3 s" in result.message
    assert json.dumps(result.message)  # viewer text only
