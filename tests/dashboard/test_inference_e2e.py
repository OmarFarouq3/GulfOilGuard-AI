"""Real end-to-end detection: a real dataset image through the real U-Net, via the subprocess adapter.

Skipped automatically unless all of these exist: the checkpoint (GOG_CHECKPOINT, else
runs/unet_refined_sar/best.pth), at least one image in assets/images (or GOG_IMAGE_DIR), and an
interpreter with torch (GOG_DETECTION_PYTHON, else this one). Values come from the
environment as it was before the test setup cleared it (dashboard_testkit.REAL_ENV).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest
from dashboard_testkit import REAL_ENV
from PIL import Image

from services import image_picker, inference

CHECKPOINT = Path(REAL_ENV["GOG_CHECKPOINT"]) if REAL_ENV["GOG_CHECKPOINT"] else inference.config.DETECTION_CHECKPOINT
IMAGE_DIR = Path(REAL_ENV["GOG_IMAGE_DIR"]) if REAL_ENV["GOG_IMAGE_DIR"] else image_picker.IMAGE_DIR
PYTHON = REAL_ENV["GOG_DETECTION_PYTHON"] or inference.sys.executable


def _skip_reason() -> str | None:
    if not CHECKPOINT.is_file():
        return f"no checkpoint at {CHECKPOINT}"
    if not image_picker.list_images(IMAGE_DIR):
        return f"no images in {IMAGE_DIR}"
    probe = subprocess.run([PYTHON, "-c", "import torch"], capture_output=True, timeout=120)
    if probe.returncode != 0:
        return f"{PYTHON} has no torch (set GOG_DETECTION_PYTHON)"
    return None


REASON = _skip_reason()


@pytest.mark.skipif(REASON is not None, reason=REASON or "")
def test_real_image_through_the_real_model(tmp_path):
    image = image_picker.pick_random_image(IMAGE_DIR)
    image_id = image_picker.image_id(image, root=IMAGE_DIR)
    result = inference.run_detection(image, image_id, checkpoint=CHECKPOINT, python=PYTHON, out_dir=tmp_path)
    assert result.state == "done", f"{result.message}\n{result.detail}"

    files = inference.output_files(image_id, tmp_path)
    with Image.open(image) as source, Image.open(files["mask"]) as mask:
        assert mask.size == source.size
        assert set(np.unique(np.asarray(mask))) <= {0, 255}
    assert 0.0 <= result.info["oil_fraction"] <= 1.0

    again = inference.run_detection(image, image_id, checkpoint=CHECKPOINT, python=PYTHON, out_dir=tmp_path)
    assert again.state == "cached"
