"""Real end-to-end detection: a real dataset image through the real U-Net, via the subprocess adapter.

Resolves the checkpoint, the interpreter and the image folder exactly like the dashboard does
(services/settings.py: environment > .env > standard layout) against the real repo root and the
environment as it was before the test setup cleared it (dashboard_testkit.REAL_ENV). With the
standard layout (checkpoints/unet_best.pth, .venv-detect/, assets/images) no variables are needed.
Skipped automatically unless a checkpoint, at least one image and an interpreter with torch exist.
"""

from __future__ import annotations

import subprocess

import numpy as np
import pytest
from dashboard_testkit import REAL_ENV, REPO_ROOT
from PIL import Image

from services import image_picker, inference, settings

CHECKPOINT = settings.resolve_checkpoint(root=REPO_ROOT, environ=REAL_ENV)
PYTHON = settings.resolve_python(root=REPO_ROOT, environ=REAL_ENV)
IMAGES = settings.resolve_image_dir(root=REPO_ROOT, environ=REAL_ENV)


def _skip_reason() -> str | None:
    if not CHECKPOINT.path.is_file():
        return f"no checkpoint ({settings.describe(CHECKPOINT.checked, root=REPO_ROOT)})"
    if not image_picker.list_images(IMAGES.path):
        return f"no images in {IMAGES.path}"
    probe = subprocess.run([str(PYTHON.path), "-c", "import torch"], capture_output=True, timeout=120)
    if probe.returncode != 0:
        return f"no torch in {PYTHON.path} ({PYTHON.source}); create .venv-detect/ or set GOG_DETECTION_PYTHON"
    return None


REASON = _skip_reason()


@pytest.mark.skipif(REASON is not None, reason=REASON or "")
def test_real_image_through_the_real_model(tmp_path):
    image = image_picker.pick_random_image(IMAGES.path)
    image_id = image_picker.image_id(image, root=IMAGES.path)
    result = inference.run_detection(image, image_id, checkpoint=CHECKPOINT.path, python=str(PYTHON.path),
                                     out_dir=tmp_path)
    assert result.state == "done", f"{result.message}\n{result.detail}"

    files = inference.output_files(image_id, tmp_path)
    with Image.open(image) as source, Image.open(files["mask"]) as mask:
        assert mask.size == source.size
        assert set(np.unique(np.asarray(mask))) <= {0, 255}
    assert 0.0 <= result.info["oil_fraction"] <= 1.0

    again = inference.run_detection(image, image_id, checkpoint=CHECKPOINT.path, python=str(PYTHON.path),
                                    out_dir=tmp_path)
    assert again.state == "cached"
