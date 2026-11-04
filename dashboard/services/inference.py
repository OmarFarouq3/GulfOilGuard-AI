"""Run the U-Net on the selected radar image, in a subprocess (Streamlit never imports torch).

``run_detection`` calls ``python -m detection.predict_cli`` with the detection interpreter
(services/settings.py: GOG_DETECTION_PYTHON, .env, .venv-detect/, else this interpreter), which writes
``<image_id>_{image,mask,overlay}.png`` into ``config.LIVE_DETECTION_DIR`` (``runs/dashboard/detection/``,
git-ignored), the names ``detection_loader`` reads. Live runs never write into ``outputs/``: that folder
holds the modules' saved results, which a click must not change. A small manifest
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
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from PIL import Image

import config
from services import schema  # noqa: F401  (puts the repo root on sys.path for shared/)
from services import settings
from shared.detection_cli import EXIT_FAILED, EXIT_NO_TORCH, KINDS, MODULE, RESULT_PREFIX, atomic_replace

CHECKPOINT_ENV = settings.CHECKPOINT_KEY
PYTHON_ENV = settings.PYTHON_KEY
DETAIL_LINES = 40

RunState = Literal["done", "cached", "checkpoint_missing", "image_missing", "image_unreadable", "setup_needed",
                   "failed", "timeout"]


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
    """GOG_CHECKPOINT, else .env, else checkpoints/unet_best.pth if present, else the built-in default."""
    return settings.resolve_checkpoint().path


def detection_python() -> str:
    """GOG_DETECTION_PYTHON, else .env, else .venv-detect/ if present, else this interpreter."""
    return str(settings.resolve_python().path)


def output_files(image_id: str, out_dir: Path | None = None) -> dict[str, Path]:
    out = out_dir or config.LIVE_DETECTION_DIR
    return {kind: out / f"{image_id}_{kind}.png" for kind in KINDS}


def outputs_exist(image_id: str, out_dir: Path | None = None) -> bool:
    try:
        return all(p.is_file() for p in output_files(image_id, out_dir).values())
    except OSError:
        return False


def manifest_path(image_id: str, out_dir: Path | None = None) -> Path:
    return (out_dir or config.LIVE_DETECTION_DIR) / f"{image_id}_run.json"


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


def _checked(resolved: settings.Resolved, last_state: str | None = None) -> tuple[str, str]:
    """(viewer text naming files only, technical detail with full paths for ?dev=1)."""
    short = settings.describe(resolved.checked, last_state=last_state)
    full = settings.describe(resolved.checked, full=True, last_state=last_state, separator="\n")
    return short, f"Checked, in order:\n{full}"


def _checkpoint_missing_message(checkpoint: settings.Resolved) -> tuple[str, str]:
    short, detail = _checked(checkpoint)
    return (f"No trained detection model was found. Checked, in order: {short}. Put the model at "
            f"{settings.STANDARD_CHECKPOINT.as_posix()} or set {CHECKPOINT_ENV}.", detail)


IMAGE_UNREADABLE = ("This image could not be read, so the model could not run on it. Pick another image on Overview, "
                    "or continue with the simulated detection.")
CHECKPOINT_UNLOADABLE = (f"The model file could not be loaded. Check that {CHECKPOINT_ENV} points at a trained U-Net "
                         "checkpoint (.pth).")


def image_readable(path: Path) -> bool:
    """The image opens and decodes (what the model needs first); checked before starting the subprocess."""
    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            img.load()
        return True
    except Exception:  # PIL raises many exception types for bad images
        return False


def _interpreter_message(python: settings.Resolved) -> tuple[str, str]:
    """The detection interpreter is missing or won't start: name the setting and what was checked."""
    short, detail = _checked(python, last_state="could not be started" if python.path.exists() else None)
    return (f"The detection model could not be started: its Python is missing or would not run. Checked, in order: "
            f"{short}. Create {settings.DETECT_VENV}/ with PyTorch or set {PYTHON_ENV} to a Python that has it, or "
            "continue with the simulated detection.", detail)


def _setup_message(python: settings.Resolved | None = None) -> str:
    python = python or settings.resolve_python()
    short, _detail = _checked(python, last_state="no PyTorch")
    return (f"The detection model needs a Python with PyTorch. Checked, in order: {short}. Create "
            f"{settings.DETECT_VENV}/ with PyTorch or set {PYTHON_ENV} (and {CHECKPOINT_ENV} if the model file "
            "is elsewhere), or continue with the simulated detection.")


def run_detection(image_path: Path, image_id: str, *, checkpoint: Path | None = None, python: str | None = None,
                  out_dir: Path | None = None, timeout_s: float = config.DETECTION_TIMEOUT_S,
                  fresh: bool = False) -> DetectionRun:
    """Predict the oil mask for one image. ``fresh`` bypasses saved results. Never raises.

    ``checkpoint`` / ``python`` override the lookup in services/settings.py (tests, scripts).
    """
    try:
        resolved_checkpoint = (settings.given(checkpoint, "checkpoint passed in") if checkpoint
                               else settings.resolve_checkpoint())
        resolved_python = settings.given(python, "interpreter passed in") if python else settings.resolve_python()
        return _run_detection(Path(image_path), image_id, resolved_checkpoint, resolved_python,
                              out_dir or config.LIVE_DETECTION_DIR, timeout_s, fresh)
    except Exception:  # last resort: a status, never an error page
        return DetectionRun("failed", "Detection could not be completed.", image_id, detail=traceback.format_exc())


def _run_detection(image_path: Path, image_id: str, resolved_checkpoint: settings.Resolved,
                   resolved_python: settings.Resolved, out: Path, timeout_s: float, fresh: bool) -> DetectionRun:
    checkpoint = resolved_checkpoint.path
    if not image_path.is_file():
        return DetectionRun("image_missing", "The selected radar image is no longer available.", image_id)
    if not image_readable(image_path):
        return DetectionRun("image_unreadable", IMAGE_UNREADABLE, image_id)
    if not checkpoint.is_file():
        message, detail = _checkpoint_missing_message(resolved_checkpoint)
        return DetectionRun("checkpoint_missing", message, image_id, detail=detail)
    cached = None if fresh else cached_run(image_path, image_id, checkpoint, out)
    if cached:
        return cached

    out.mkdir(parents=True, exist_ok=True)
    command = _command(str(resolved_python.path), checkpoint, image_path, out, image_id)
    try:
        result = subprocess.run(command, cwd=config.REPO_ROOT, capture_output=True, timeout=timeout_s,
                                text=True, encoding="utf-8", errors="replace",
                                env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    except subprocess.TimeoutExpired:
        return DetectionRun("timeout", f"Detection did not finish within {timeout_s:g} s.", image_id,
                            detail=" ".join(command))
    except OSError as exc:  # interpreter missing or not executable
        message, checked = _interpreter_message(resolved_python)
        return DetectionRun("setup_needed", message, image_id, detail=f"{checked}\n\n{' '.join(command)}\n{exc}")

    detail = _tail(result.stderr) or _tail(result.stdout)
    if result.returncode == EXIT_NO_TORCH:
        checked = _checked(resolved_python, last_state="no PyTorch")[1]
        return DetectionRun("setup_needed", _setup_message(resolved_python), image_id,
                            detail=f"{checked}\n\n{detail}".strip())
    if result.returncode == EXIT_FAILED:
        # The CLI's exit codes don't separate a bad checkpoint from a bad image (both EXIT_FAILED). The
        # image was decoded above, so the checkpoint is what failed to load (or a rarer runtime error).
        return DetectionRun("failed", CHECKPOINT_UNLOADABLE, image_id, detail=f"exit code {result.returncode}\n{detail}")
    if result.returncode != 0:
        return DetectionRun("failed", "Detection could not be completed.", image_id,
                            detail=f"exit code {result.returncode}\n{detail}")

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
