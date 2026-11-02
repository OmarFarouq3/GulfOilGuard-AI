"""Run the U-Net on the selected radar image, in a subprocess (Streamlit never imports torch).

``run_detection`` calls ``python -m detection.predict_cli`` with ``GOG_DETECTION_PYTHON``
(default: this interpreter), which writes ``<image_id>_{image,mask,overlay}.png`` into
``outputs/detection/``, the names ``detection_loader`` already reads. A small manifest
``<image_id>_run.json`` records which image (path + mtime) and checkpoint (path + mtime)
produced them; while both are unchanged, a re-run returns the stored result instantly.
The CLI contract (module, result line, exit codes) lives in shared/detection_cli.py.

No Streamlit here, so everything is easy to unit-test. ``run_detection`` never raises:
every problem becomes a status with a viewer-safe ``message``; ``detail`` holds the
technical output (traceback, paths), which the page shows only with ``?dev=1``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import config
from services import schema  # noqa: F401  (puts the repo root on sys.path for shared/)
from shared.detection_cli import EXIT_NO_TORCH, KINDS, MODULE, RESULT_PREFIX, atomic_replace

CHECKPOINT_ENV = "GOG_CHECKPOINT"
PYTHON_ENV = "GOG_DETECTION_PYTHON"
DETAIL_LINES = 40

RunState = Literal["done", "cached", "checkpoint_missing", "image_missing", "setup_needed", "failed", "timeout"]


@dataclass(frozen=True)
class DetectionRun:
    state: RunState
    message: str
    image_id: str | None = None
    detail: str | None = None  # technical output (stderr tail, paths): shown only with ?dev=1
    info: dict[str, Any] = field(default_factory=dict)  # threshold, image_size, epoch, oil_fraction, checkpoint

    @property
    def ok(self) -> bool:
        return self.state in ("done", "cached")


def checkpoint_path() -> Path:
    env_value = os.environ.get(CHECKPOINT_ENV)
    return Path(env_value).expanduser() if env_value else config.DETECTION_CHECKPOINT


def detection_python() -> str:
    return os.environ.get(PYTHON_ENV) or sys.executable


def output_files(image_id: str, out_dir: Path | None = None) -> dict[str, Path]:
    out = out_dir or config.DETECTION_DIR
    return {kind: out / f"{image_id}_{kind}.png" for kind in KINDS}


def outputs_exist(image_id: str, out_dir: Path | None = None) -> bool:
    try:
        return all(p.is_file() for p in output_files(image_id, out_dir).values())
    except OSError:
        return False


def manifest_path(image_id: str, out_dir: Path | None = None) -> Path:
    return (out_dir or config.DETECTION_DIR) / f"{image_id}_run.json"


def _fingerprint(image_path: Path, checkpoint: Path) -> dict[str, Any]:
    return {"image": str(image_path.resolve()), "image_mtime": image_path.stat().st_mtime,
            "checkpoint": str(checkpoint.resolve()), "checkpoint_mtime": checkpoint.stat().st_mtime}


def _write_text_atomic(target: Path, text: str) -> None:
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        atomic_replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def cached_run(image_path: Path, image_id: str, checkpoint: Path | None = None,
               out_dir: Path | None = None) -> DetectionRun | None:
    """The stored result if this exact image and checkpoint produced it and all files exist.

    Anything unreadable or unexpected (missing files, a manifest that is not a JSON object)
    is a cache miss, never an error.
    """
    checkpoint = checkpoint or checkpoint_path()
    try:
        stored = json.loads(manifest_path(image_id, out_dir).read_text(encoding="utf-8"))
        if not isinstance(stored, dict) or stored.get("fingerprint") != _fingerprint(image_path, checkpoint):
            return None
    except (OSError, ValueError):
        return None
    if not outputs_exist(image_id, out_dir):
        return None
    info = stored.get("info")
    return DetectionRun("cached", "Detection result reused (same image and model).", image_id,
                        info=info if isinstance(info, dict) else {})


def _command(python: str, checkpoint: Path, image_path: Path, out_dir: Path, image_id: str) -> list[str]:
    return [python, "-m", MODULE, "--checkpoint", str(checkpoint), "--image", str(image_path),
            "--out", str(out_dir), "--image-id", image_id]


def _tail(text: str) -> str:
    return "\n".join((text or "").strip().splitlines()[-DETAIL_LINES:])


def _setup_message() -> str:
    if os.environ.get(PYTHON_ENV):
        return (f"The Python set in {PYTHON_ENV} has no PyTorch. Point it at an interpreter with PyTorch, "
                "or continue with the simulated detection.")
    return (f"The dashboard's Python has no PyTorch, so the model can't run here. Set {PYTHON_ENV} to a "
            f"Python with PyTorch and {CHECKPOINT_ENV} to the model file, or continue with the simulated detection.")


def run_detection(image_path: Path, image_id: str, *, checkpoint: Path | None = None, python: str | None = None,
                  out_dir: Path | None = None, timeout_s: float = config.DETECTION_TIMEOUT_S) -> DetectionRun:
    """Predict the oil mask for one image (or reuse a matching stored result). Never raises."""
    try:
        return _run_detection(Path(image_path), image_id, Path(checkpoint or checkpoint_path()), python,
                              out_dir or config.DETECTION_DIR, timeout_s)
    except Exception:  # last resort: a status, never an error page
        return DetectionRun("failed", "Detection could not be completed.", image_id, detail=traceback.format_exc())


def _run_detection(image_path: Path, image_id: str, checkpoint: Path, python: str | None, out: Path,
                   timeout_s: float) -> DetectionRun:
    if not image_path.is_file():
        return DetectionRun("image_missing", "The selected radar image is no longer available.", image_id)
    if not checkpoint.is_file():
        return DetectionRun("checkpoint_missing",
                            f"No trained detection model was found. Set {CHECKPOINT_ENV} to the model file to run it.",
                            image_id, detail=f"Checkpoint not found: {checkpoint}")
    cached = cached_run(image_path, image_id, checkpoint, out)
    if cached:
        return cached

    command = _command(python or detection_python(), checkpoint, image_path, out, image_id)
    try:
        result = subprocess.run(command, cwd=config.REPO_ROOT, capture_output=True, timeout=timeout_s,
                                text=True, encoding="utf-8", errors="replace",
                                env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    except subprocess.TimeoutExpired:
        return DetectionRun("timeout", f"Detection did not finish within {timeout_s:g} s.", image_id,
                            detail=" ".join(command))
    except OSError as exc:  # interpreter missing or not executable
        return DetectionRun("failed", "The detection model could not be started.", image_id,
                            detail=f"{' '.join(command)}\n{exc}")

    detail = _tail(result.stderr) or _tail(result.stdout)
    if result.returncode == EXIT_NO_TORCH:
        return DetectionRun("setup_needed", _setup_message(), image_id, detail=detail)
    if result.returncode != 0:
        return DetectionRun("failed", f"Detection failed (exit code {result.returncode}).", image_id, detail=detail)

    lines = [line for line in (result.stdout or "").splitlines() if line.startswith(RESULT_PREFIX)]
    try:
        info = json.loads(lines[-1][len(RESULT_PREFIX):])
        if not isinstance(info, dict):
            raise ValueError("result is not an object")
    except (IndexError, ValueError):
        return DetectionRun("failed", "Detection finished but reported no result.", image_id, detail=detail)
    if not outputs_exist(image_id, out):
        return DetectionRun("failed", "Detection finished but its output files are missing.", image_id, detail=detail)

    info = {k: info[k] for k in ("threshold", "image_size", "epoch", "oil_fraction") if k in info}
    info["checkpoint"] = checkpoint.name
    try:
        manifest = {"fingerprint": _fingerprint(image_path, checkpoint), "info": info}
        _write_text_atomic(manifest_path(image_id, out), json.dumps(manifest, indent=2))
    except OSError:
        return DetectionRun("failed", "Detection finished but its result could not be saved.", image_id,
                            detail=traceback.format_exc())
    return DetectionRun("done", "Detection finished.", image_id, info=info)
