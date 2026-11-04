"""Run detection writes to runs/dashboard/detection/ (config.LIVE_DETECTION_DIR), never into outputs/.

outputs/detection/ holds the saved scenes: a click must not change them, nor what the next session
shows from them. Goes through the real services.inference.run_detection; only the subprocess is
replaced (test_inference.FakeRun writes what detection/predict_cli writes, into --out).
"""

from __future__ import annotations

import config
import pytest
from dashboard_testkit import make_image, page_text
from test_flow_apptest import DETECT, button, checked, images, new_app, open_page, select  # noqa: F401
from test_inference import FakeRun

from services import image_picker, inference


def snapshot(directory) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(directory.glob("*")) if p.is_file()}


@pytest.fixture
def saved_scene():
    """One saved scene in outputs/detection/, as the detection module leaves it."""
    config.DETECTION_DIR.mkdir(parents=True, exist_ok=True)
    for kind in ("image", "mask"):
        make_image(config.DETECTION_DIR / f"saved-scene_{kind}.png", seed=7)
    yield config.DETECTION_DIR
    for directory in (config.DETECTION_DIR, config.LIVE_DETECTION_DIR):
        for path in directory.glob("*"):
            path.unlink()


@pytest.fixture
def model(tmp_path, monkeypatch):
    """A checkpoint file to find and a stand-in for the CLI subprocess."""
    checkpoint = tmp_path / "model.pth"
    checkpoint.write_bytes(b"not a real checkpoint")
    monkeypatch.setenv("GOG_CHECKPOINT", str(checkpoint))
    fake = FakeRun()
    monkeypatch.setattr(inference.subprocess, "run", fake)
    return fake


def test_live_runs_go_to_runs_dashboard_not_outputs():
    assert config.LIVE_DETECTION_DIR.parent == config.RUNS_DIR
    assert config.OUTPUTS_DIR not in config.LIVE_DETECTION_DIR.parents
    assert inference.output_files("x")["mask"].parent == config.LIVE_DETECTION_DIR
    assert inference.manifest_path("x").parent == config.LIVE_DETECTION_DIR


def test_runs_folder_defaults_to_the_git_ignored_runs_dir(monkeypatch):
    monkeypatch.delenv("GULFOILGUARD_RUNS")
    assert config._resolve_runs_dir() == config.REPO_ROOT / "runs" / "dashboard"
    ignored = (config.REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "runs/" in ignored


def test_a_click_never_changes_the_saved_outputs(images, saved_scene, model):
    before = snapshot(saved_scene)
    at = new_app()
    select(at, "GOG-SIM-01", images[0])
    open_page(at, DETECT)
    button(at, "flow_run_detection").click()
    text = page_text(checked(at.run()))
    live_id = image_picker.image_id(images[0])

    assert model.calls, "the (stubbed) model subprocess ran"
    command = model.calls[0][0]
    assert command[command.index("--out") + 1] == str(config.LIVE_DETECTION_DIR)
    assert "Detection finished." in text and "Detected oil (white)" in text  # the live result is shown
    assert inference.outputs_exist(live_id)  # ...from runs/dashboard/detection/
    assert snapshot(saved_scene) == before  # outputs/detection/ is byte-identical, nothing added

    fresh = new_app()  # the next visitor, no spill selected: only the saved scene
    fresh_text = page_text(open_page(fresh, DETECT))
    assert live_id not in fresh_text and "Radar image" in fresh_text
