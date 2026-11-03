"""services.inference with a stubbed subprocess, plus detection/predict_cli's file writer.

No torch needed: subprocess.run is replaced, so the CLI never runs here (see test_inference_e2e).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest
from dashboard_testkit import REPO_ROOT, make_image
from PIL import Image

from services import inference
from services.detection_loader import load_scene


@pytest.fixture
def files(tmp_path):
    image = make_image(tmp_path / "images" / "scene.png", size=(20, 10))
    checkpoint = tmp_path / "best.pth"
    checkpoint.write_bytes(b"not a real checkpoint")
    return image, checkpoint, tmp_path / "out"


class FakeRun:
    """Stands in for subprocess.run: writes what predict_cli writes and records each call."""

    def __init__(self, returncode=0, stdout=None, stderr="", write=True, raises=None):
        self.calls, self.returncode, self.stdout, self.stderr = [], returncode, stdout, stderr
        self.write, self.raises = write, raises

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if self.raises:
            raise self.raises
        args = dict(zip(command[3::2], command[4::2]))  # [python, -m, module, --flag, value, ...]
        if self.write and self.returncode == 0:
            out = args["--out"]
            os.makedirs(out, exist_ok=True)
            with Image.open(args["--image"]) as source:
                rgb = np.asarray(source.convert("RGB"))
            mask = np.where(rgb[..., 0] > 127, 255, 0).astype(np.uint8)
            for kind, pixels in (("image", rgb), ("mask", mask), ("overlay", rgb)):
                Image.fromarray(pixels).save(os.path.join(out, f"{args['--image-id']}_{kind}.png"))
        stdout = self.stdout if self.stdout is not None else (
            "torch noise\nGOG_RESULT " + json.dumps({"threshold": 0.5, "image_size": 256, "epoch": 3,
                                                    "oil_fraction": 0.25, "ignored": "x"}) + "\n")
        return subprocess.CompletedProcess(command, self.returncode, stdout=stdout, stderr=self.stderr)


def run(files, **kwargs):
    image, checkpoint, out = files
    return inference.run_detection(image, "scene-abc", checkpoint=checkpoint, out_dir=out, **kwargs)


def test_missing_checkpoint_is_a_status_not_an_exception(files, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(inference.subprocess, "run", fake)
    image, _checkpoint, out = files
    result = inference.run_detection(image, "scene-abc", checkpoint=out / "nope.pth", out_dir=out)
    assert result.state == "checkpoint_missing" and not result.ok
    assert "nope.pth" in result.detail and not fake.calls


def test_checkpoint_comes_from_env_else_standard_layout_else_default(tmp_path, monkeypatch):
    from services import settings
    assert inference.checkpoint_path() == settings.ROOT / "runs" / "unet_refined_sar" / "best.pth"
    standard = settings.ROOT / "checkpoints" / "unet_best.pth"
    standard.parent.mkdir(parents=True)
    standard.write_bytes(b"x")
    assert inference.checkpoint_path() == standard
    monkeypatch.setenv("GOG_CHECKPOINT", str(tmp_path / "x.pth"))
    assert inference.checkpoint_path() == tmp_path / "x.pth"


def test_missing_image_is_a_status(files, monkeypatch):
    _image, checkpoint, out = files
    monkeypatch.setattr(inference.subprocess, "run", FakeRun())
    assert inference.run_detection(out / "gone.png", "x", checkpoint=checkpoint, out_dir=out).state == "image_missing"


def test_success_writes_expected_files_and_caches(files, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(inference.subprocess, "run", fake)
    result = run(files)
    assert result.state == "done" and result.ok
    assert result.info == {"threshold": 0.5, "image_size": 256, "epoch": 3, "oil_fraction": 0.25,
                           "checkpoint": "best.pth"}
    out = files[2]
    assert sorted(p.name for p in out.iterdir()) == [
        "scene-abc_image.png", "scene-abc_mask.png", "scene-abc_overlay.png", "scene-abc_run.json"]
    command, kwargs = fake.calls[0]
    assert command[1:3] == ["-m", "detection.predict_cli"] and kwargs["cwd"] == REPO_ROOT and kwargs["timeout"]

    again = run(files)
    assert again.state == "cached" and again.ok and again.info == result.info
    assert len(fake.calls) == 1  # no second subprocess


@pytest.mark.parametrize("touch", ["image", "checkpoint"])
def test_cache_is_invalidated_by_mtime(files, monkeypatch, touch):
    fake = FakeRun()
    monkeypatch.setattr(inference.subprocess, "run", fake)
    run(files)
    target = files[0] if touch == "image" else files[1]
    later = time.time() + 60
    os.utime(target, (later, later))
    assert run(files).state == "done" and len(fake.calls) == 2


def test_cache_is_invalidated_by_another_checkpoint(files, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(inference.subprocess, "run", fake)
    run(files)
    other = files[1].with_name("other.pth")
    other.write_bytes(b"x")
    assert inference.run_detection(files[0], "scene-abc", checkpoint=other, out_dir=files[2]).state == "done"
    assert len(fake.calls) == 2


def test_cache_needs_all_output_files(files, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(inference.subprocess, "run", fake)
    run(files)
    (files[2] / "scene-abc_overlay.png").unlink()
    assert run(files).state == "done" and len(fake.calls) == 2


@pytest.mark.parametrize("fake, message", [
    (FakeRun(returncode=4, stderr="Traceback ...\nValueError: bad"), "exit code 4"),
    (FakeRun(stdout="no result line\n"), "no result"),
    (FakeRun(write=False), "missing"),
    (FakeRun(raises=OSError("not executable")), "could not be started"),
])
def test_failures_become_short_statuses(files, monkeypatch, fake, message):
    monkeypatch.setattr(inference.subprocess, "run", fake)
    result = run(files)
    assert result.state == "failed" and not result.ok
    assert message in result.message and "\n" not in result.message
    assert not inference.manifest_path("scene-abc", files[2]).exists()  # failures are never cached


def test_failure_detail_keeps_the_tail_of_stderr(files, monkeypatch):
    stderr = "\n".join(f"line {i}" for i in range(100))
    monkeypatch.setattr(inference.subprocess, "run", FakeRun(returncode=4, stderr=stderr))
    detail = run(files).detail.splitlines()
    assert len(detail) == inference.DETAIL_LINES and detail[-1] == "line 99"


def test_timeout_becomes_a_status(files, monkeypatch):
    monkeypatch.setattr(inference.subprocess, "run", FakeRun(raises=subprocess.TimeoutExpired("cmd", 2)))
    result = run(files, timeout_s=2)
    assert result.state == "timeout" and "2 s" in result.message


def test_loader_picks_up_the_written_scene(files, monkeypatch):
    monkeypatch.setattr(inference.subprocess, "run", FakeRun())
    image, checkpoint, _out = files
    out = inference.config.DETECTION_DIR  # load_scene reads the configured (test) outputs folder
    assert inference.run_detection(image, "loader-check", checkpoint=checkpoint).state == "done"
    try:
        data = load_scene("loader-check")
        assert data is not None and [s.image_id for s in data.scenes] == ["loader-check"]
        scene = data.scenes[0]
        assert scene.image and scene.mask and scene.overlay
        assert load_scene("some-other-image") is None
    finally:
        for path in out.glob("loader-check_*"):
            path.unlink()


def test_predict_cli_writes_mask_overlay_and_input(tmp_path):
    """The CLI's file writer (torch-free part): sizes match, mask is strictly 0/255."""
    from detection.predict_cli import write_outputs

    image = make_image(tmp_path / "in.jpg", size=(24, 18))
    mask = np.zeros((18, 24), dtype=np.uint8)
    mask[4:9, 5:15] = 200
    Image.fromarray(mask).save(tmp_path / "raw_mask.png")
    result = write_outputs(image, tmp_path / "raw_mask.png", tmp_path, "img-1")
    written = {k: Image.open(v) for k, v in result["files"].items()}
    assert {k: im.size for k, im in written.items()} == {"image": (24, 18), "mask": (24, 18), "overlay": (24, 18)}
    assert set(np.unique(np.asarray(written["mask"]))) <= {0, 200, 255}
    assert result["oil_fraction"] == pytest.approx(50 / (24 * 18))


# --- Fix 19: no torch -> a setup message naming both variables ---------------------------------


def test_no_torch_without_override_explains_the_setup(files, monkeypatch):
    monkeypatch.delenv("GOG_DETECTION_PYTHON", raising=False)
    monkeypatch.setattr(inference.subprocess, "run", FakeRun(returncode=3, stderr="No module named 'torch'"))
    result = run(files)
    assert result.state == "setup_needed" and not result.ok
    assert "GOG_DETECTION_PYTHON" in result.message and "GOG_CHECKPOINT" in result.message
    assert "simulated detection" in result.message and "\n" not in result.message
    # what was checked, in order, ending with the interpreter that was used
    message = result.message
    order = ["GOG_DETECTION_PYTHON environment variable: not set", "GOG_DETECTION_PYTHON in .env: not set",
             "standard layout .venv-detect/", "the dashboard's own Python"]
    positions = [message.index(part) for part in order]
    assert positions == sorted(positions) and "no PyTorch" in message


def test_no_torch_with_override_names_the_override(files, monkeypatch):
    monkeypatch.setenv("GOG_DETECTION_PYTHON", "C:/somewhere/python.exe")
    monkeypatch.setattr(inference.subprocess, "run", FakeRun(returncode=3))
    result = run(files)
    assert result.state == "setup_needed"
    assert "GOG_DETECTION_PYTHON environment variable python.exe: no PyTorch" in result.message
    assert "C:/somewhere" not in result.message and "somewhere" in result.detail  # full path: ?dev=1 only
    assert ".env" not in result.message.split("Checked, in order:")[1].split(".")[0]  # stopped at the variable


# --- Fix 8: run_detection never raises -----------------------------------------------------------


@pytest.mark.parametrize("exc", [ValueError("odd"), RuntimeError("boom"), KeyError("k")])
def test_unexpected_errors_become_a_status(files, monkeypatch, exc):
    monkeypatch.setattr(inference.subprocess, "run", FakeRun(raises=exc))
    result = run(files)
    assert result.state == "failed" and result.message == "Detection could not be completed."
    assert type(exc).__name__ in result.detail  # traceback kept for ?dev=1


def test_fingerprint_failure_after_a_successful_run_is_a_status(files, monkeypatch):
    """The image vanishes while the model runs: the post-run fingerprint can't stat it."""
    fake = FakeRun()
    monkeypatch.setattr(inference.subprocess, "run", fake)

    def gone(image_path, checkpoint):
        raise FileNotFoundError("image deleted during the run")

    monkeypatch.setattr(inference, "_fingerprint", gone)
    result = run(files)
    assert len(fake.calls) == 1  # the model did run
    assert result.state == "failed" and "could not be saved" in result.message


def test_manifest_write_failure_is_a_status(files, monkeypatch):
    monkeypatch.setattr(inference.subprocess, "run", FakeRun())
    inference.manifest_path("scene-abc", files[2]).mkdir(parents=True)  # a folder where the file must go
    result = run(files)
    assert result.state == "failed" and "could not be saved" in result.message
    assert not [p for p in files[2].iterdir() if p.suffix == ".tmp"]  # temp file cleaned up


@pytest.mark.parametrize("content", ["[1, 2]", '"text"', "42", "null", '{"fingerprint": 5}', "{not json", ""])
def test_cached_run_treats_unexpected_manifests_as_a_miss(files, content):
    image, checkpoint, out = files
    out.mkdir(parents=True)
    for path in inference.output_files("scene-abc", out).values():
        path.write_bytes(b"png")
    inference.manifest_path("scene-abc", out).write_text(content, encoding="utf-8")
    assert inference.cached_run(image, "scene-abc", checkpoint, out) is None


def test_bad_manifest_leads_to_a_fresh_run(files, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(inference.subprocess, "run", fake)
    run(files)
    inference.manifest_path("scene-abc", files[2]).write_text("[1, 2]", encoding="utf-8")
    assert run(files).state == "done" and len(fake.calls) == 2


@pytest.mark.parametrize("stdout", ['GOG_RESULT [1, 2]\n', 'GOG_RESULT "x"\n'])
def test_result_line_that_is_not_an_object_is_a_status(files, monkeypatch, stdout):
    monkeypatch.setattr(inference.subprocess, "run", FakeRun(stdout=stdout))
    assert run(files).state == "failed"


# --- Fix 7: the manifest is written atomically ---------------------------------------------------


def test_manifest_is_replaced_atomically(files, monkeypatch):
    monkeypatch.setattr(inference.subprocess, "run", FakeRun())
    moves = []
    real = inference.atomic_replace

    def spy(source, target, **kwargs):
        moves.append((Path(source), Path(target)))
        assert Path(source).parent == Path(target).parent  # same folder: os.replace stays atomic
        real(source, target, **kwargs)

    monkeypatch.setattr(inference, "atomic_replace", spy)
    run(files)
    assert [t.name for _s, t in moves] == ["scene-abc_run.json"]
    assert json.loads((files[2] / "scene-abc_run.json").read_text(encoding="utf-8"))["info"]["checkpoint"] == "best.pth"


# --- Fix 9: subprocess output is decoded as UTF-8, never crashes on odd bytes ---------------------


def test_subprocess_is_decoded_as_utf8_with_replacement(files, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(inference.subprocess, "run", fake)
    run(files)
    _command, kwargs = fake.calls[0]
    assert kwargs["encoding"] == "utf-8" and kwargs["errors"] == "replace"
    assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"


def test_real_subprocess_with_undecodable_bytes_does_not_crash(files, monkeypatch, tmp_path):
    """A real child process writes bytes that are invalid UTF-8 (and undefined in cp1252)."""
    script = tmp_path / "bad_bytes.py"
    script.write_text(
        "import sys\n"
        "sys.stderr.buffer.write(b'bad \\x81\\x8d\\xff bytes\\n')\n"
        "sys.exit(4)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(inference, "_command", lambda python, *a: [python, str(script)])
    result = run(files)
    assert result.state == "failed" and "exit code 4" in result.message
    assert "bad" in result.detail and "�" in result.detail
