"""E1: the Detect page shows a scene written by detection/evaluate.py (``<scene>_image.png`` +
``<scene>_mask.png``) with its mask and scores, and says plainly when the mask is not available yet.

Small synthetic PNGs are written into the test outputs folder; nothing reads the real outputs/.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image
from test_overview_framing import VAL_METRICS, section
from test_sites import bodies, go, new_app

import config

MASK_MISSING = "The detected oil mask for this scene is not available yet"
NO_SCENE = "The radar image and detected oil mask are not available yet."


@pytest.fixture
def detection_files():
    """Write files into outputs/detection of the test folder; everything is removed afterwards."""
    config.DETECTION_DIR.mkdir(parents=True, exist_ok=True)

    def write(*, image: bool = True, mask: bool = True, metrics: bool = True, scene: str = "palsar_0"):
        if image:
            Image.fromarray(np.full((16, 16, 3), 90, dtype=np.uint8)).save(config.DETECTION_DIR / f"{scene}_image.png")
        if mask:
            array = np.zeros((16, 16), dtype=np.uint8)
            array[4:10, 4:10] = 255  # evaluate.py writes 0 / 255
            Image.fromarray(array).save(config.DETECTION_DIR / f"{scene}_mask.png")
        if metrics:
            config.DETECTION_FILES["metrics"].write_text(json.dumps(VAL_METRICS), encoding="utf-8")

    yield write
    for path in config.DETECTION_DIR.glob("*"):
        path.unlink()


def captions(at) -> list[str]:
    return [img.caption for element in at.get("image") for img in element.proto.imgs]


def detect(at):
    return go(at, "views/detection.py")


def test_evaluate_py_output_shows_image_mask_overlay_and_scores(detection_files):
    detection_files()
    at = detect(new_app())
    assert captions(at) == ["Radar image", "Detected oil (white)", "Overlay"]  # overlay built from image + mask
    assert "0.87" in " ".join(bodies(at, "gog-stat"))  # Dice from metrics.json
    text = " ".join(bodies(at, ""))
    assert MASK_MISSING not in text and NO_SCENE not in text


def test_a_scene_without_its_mask_says_the_mask_is_not_available_yet(detection_files):
    detection_files(mask=False)
    at = detect(new_app())
    assert captions(at) == ["Radar image"]
    assert any(MASK_MISSING in b for b in bodies(at, "gog-notice"))
    assert "0.87" in " ".join(bodies(at, "gog-stat"))  # the scores are still shown, labelled as the model's


def test_scores_without_any_scene_say_the_mask_is_not_available_yet(detection_files):
    detection_files(image=False, mask=False)
    at = detect(new_app())
    assert captions(at) == []
    assert NO_SCENE in " ".join(bodies(at, ""))
    assert "Overall model accuracy" in section(at, "Overall model accuracy")
