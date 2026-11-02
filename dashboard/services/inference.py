"""Run the U-Net on the selected radar image, in a subprocess (Streamlit never imports torch).

``run_detection`` calls ``python -m detection.predict_cli`` with ``GOG_DETECTION_PYTHON``
(default: this interpreter), which writes ``<image_id>_{image,mask,overlay}.png`` into
``outputs/detection/``, the names ``detection_loader`` already reads. A small manifest
``<image_id>_run.json`` records which image (path + mtime) and checkpoint (path + mtime)
produced them; while both are unchanged, a re-run returns the stored result instantly.

No Streamlit here, so everything is easy to unit-test. Messages are viewer-safe;
``detail`` holds the technical output for an expander.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import config

CHECKPOINT_ENV = "GOG_CHECKPOINT"
PYTHON_ENV = "GOG_DETECTION_PYTHON"
CLI_MODULE = "detection.predict_cli"
RESULT_PREFIX = "GOG_RESULT "  # keep in sync with detection/predict_cli.py
EXIT_NO_TORCH = 3
KINDS = ("image", "mask", "overlay")
DETAIL_LINES = 40

RunState = Literal["done", "cached", "checkpoint_missing", "image_missing", "failed", "timeout"]


@dataclass(frozen=True)
class DetectionRun:
    state: RunState
    message: str
    image_id: str | None = None
    detail: str | None = None  # technical output (stderr tail), shown collapsed
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


def manifest_path(image_id: str, out_dir: Path | None = None) -> Path:
    return (out_dir or config.DETECTION_DIR) / f"{image_id}_run.json"


def _fingerprint(image_path: Path, checkpoint: Path) -> dict[str, Any]:
    return {"image": str(image_path.resolve()), "image_mtime": image_path.stat().st_mtime,
            "checkpoint": str(checkpoint.resolve()), "checkpoint_mtime": checkpoint.stat().st_mtime}


def cached_run(image_path: Path, image_id: str, checkpoint: Path | None = None,
               out_dir: Path | None = None) -> DetectionRun | None:
    """The stored result if this exact image and checkpoint produced it and all files exist."""
    checkpoint = checkpoint or checkpoint_path()
    manifest = manifest_path(image_id, out_dir)
    try:
        stored = json.loads(manifest.read_text(encoding="utf-8"))
        if stored.get("fingerprint") != _fingerprint(image_path, checkpoint):
            return None
    except (OSError, ValueError):
        return None
    if not all(p.is_file() for p in output_files(image_id, out_dir).values()):
        return None
    return DetectionRun("cached", "Detection result reused (same image and model).", image_id,
                        info=stored.get("info", {}))


def _command(python: str, checkpoint: Path, image_path: Path, out_dir: Path, image_id: str) -> list[str]:
    return [python, "-m", CLI_MODULE, "--checkpoint", str(checkpoint), "--image", str(image_path),
            "--out", str(out_dir), "--image-id", image_id]


def _tail(text: str) -> str:
    return "\n".join((text or "").strip().splitlines()[-DETAIL_LINES:])


def run_detection(image_path: Path, image_id: str, *, checkpoint: Path | None = None, python: str | None = None,
                  out_dir: Path | None = None, timeout_s: float = config.DETECTION_TIMEOUT_S) -> DetectionRun:
    """Predict the oil mask for one image (or reuse a matching stored result). Never raises."""
    image_path, checkpoint = Path(image_path), Path(checkpoint or checkpoint_path())
    out = out_dir or config.DETECTION_DIR
    if not image_path.is_file():
        return DetectionRun("image_missing", "The selected radar image is no longer available.", image_id)
    if not checkpoint.is_file():
        return DetectionRun("checkpoint_missing", "No trained detection model was found on this machine.",
                            image_id, detail=f"Checkpoint not found: {checkpoint}\n"
                                             f"Place best.pth there or set {CHECKPOINT_ENV}.")
    cached = cached_run(image_path, image_id, checkpoint, out)
    if cached:
        return cached

    command = _command(python or detection_python(), checkpoint, image_path, out, image_id)
    try:
        result = subprocess.run(command, cwd=config.REPO_ROOT, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return DetectionRun("timeout", f"Detection did not finish within {timeout_s:g} s.", image_id,
                            detail=" ".join(command))
    except OSError as exc:  # interpreter missing or not executable
        return DetectionRun("failed", "The detection model could not be started.", image_id,
                            detail=f"{' '.join(command)}\n{exc}")

    detail = _tail(result.stderr) or _tail(result.stdout)
    if result.returncode != 0:
        message = ("PyTorch is not installed for the detection model. "
                   f"Set {PYTHON_ENV} to a Python that has it." if result.returncode == EXIT_NO_TORCH
                   else f"Detection failed (exit code {result.returncode}).")
        return DetectionRun("failed", message, image_id, detail=detail)

    lines = [line for line in result.stdout.splitlines() if line.startswith(RESULT_PREFIX)]
    try:
        info = json.loads(lines[-1][len(RESULT_PREFIX):])
    except (IndexError, ValueError):
        return DetectionRun("failed", "Detection finished but reported no result.", image_id, detail=detail)
    if not all(p.is_file() for p in output_files(image_id, out).values()):
        return DetectionRun("failed", "Detection finished but its output files are missing.", image_id, detail=detail)

    info = {k: info[k] for k in ("threshold", "image_size", "epoch", "oil_fraction") if k in info}
    info["checkpoint"] = checkpoint.name
    manifest = {"fingerprint": _fingerprint(image_path, checkpoint), "info": info}
    manifest_path(image_id, out).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return DetectionRun("done", "Detection finished.", image_id, info=info)
