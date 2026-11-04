"""E1 and the removed accuracy section: Detect shows the analysed scene (``<scene>_image.png`` +
``<scene>_mask.png`` as detection/evaluate.py writes them), says plainly when the mask is not available
yet, and never shows the model's fixed overall scores ("Overall model accuracy") in any state.

Small synthetic PNGs are written into the test outputs folder; nothing reads the real outputs/.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image
from test_sites import bodies, go, new_app

import config
from services import mock_data

MASK_MISSING = "The detected oil mask for this scene is not available yet"
NO_SCENE = "The radar image and detected oil mask are not available yet."
EMPTY = "No satellite scene analysed yet"
# Distinctive overall scores: none of these numbers may appear anywhere on the Detect page.
METRICS = {"model": "U-Net", "split": "val", "n_images": 1615, "threshold": 0.5,
           "dice": 0.1234, "iou": 0.4567, "precision": 0.3456, "recall": 0.6789}
SECTION_TEXT = ("Overall model accuracy", "Evaluation details", "Scores across", "Overall 0.", ">0.12<",
                ">0.46<", ">0.35<", ">0.68<", "1,615", "Accuracy scores", "Model performance")  # >x< : a tile value


@pytest.fixture
def detection_files():
    """Write files into outputs/detection of the test folder; everything is removed afterwards."""
    config.DETECTION_DIR.mkdir(parents=True, exist_ok=True)

    def write(*, image=True, mask=True, metrics: str | dict | None = METRICS, spill=False, scene="palsar_0"):
        if image:
            Image.fromarray(np.full((16, 16, 3), 90, dtype=np.uint8)).save(config.DETECTION_DIR / f"{scene}_image.png")
        if mask:
            array = np.zeros((16, 16), dtype=np.uint8)
            array[4:10, 4:10] = 255  # evaluate.py writes 0 / 255
            Image.fromarray(array).save(config.DETECTION_DIR / f"{scene}_mask.png")
        if metrics is not None:
            text = metrics if isinstance(metrics, str) else json.dumps(metrics)
            config.DETECTION_FILES["metrics"].write_text(text, encoding="utf-8")
        if spill:
            config.DETECTION_FILES["spill"].write_text(json.dumps(mock_data.spill_outline()), encoding="utf-8")

    yield write
    for path in config.DETECTION_DIR.glob("*"):
        path.unlink()


def captions(at) -> list[str]:
    return [img.caption for element in at.get("image") for img in element.proto.imgs]


def detect(at):
    at = go(at, "views/detection.py")
    assert not at.exception and not at.error, [e.message for e in at.exception]
    return at


def text(at) -> str:
    how = " ".join(m.value for e in at.expander for m in e.markdown)
    return " ".join(bodies(at, "")) + " " + " ".join(c.value for c in at.caption) + " " + how


def test_evaluate_py_output_shows_image_mask_and_overlay(detection_files):
    detection_files()
    at = detect(new_app())
    assert captions(at) == ["Radar image", "Detected oil (white)", "Overlay"]  # overlay built from image + mask
    page = text(at)
    assert MASK_MISSING not in page and NO_SCENE not in page


def test_a_scene_without_its_mask_says_the_mask_is_not_available_yet(detection_files):
    detection_files(mask=False)
    at = detect(new_app())
    assert captions(at) == ["Radar image"]
    notice = " ".join(bodies(at, "gog-notice"))
    assert MASK_MISSING in notice and "accuracy scores" not in notice  # no scores below to point at any more


def test_a_slick_without_any_scene_says_the_image_and_mask_are_not_available_yet(detection_files):
    detection_files(image=False, mask=False, spill=True)
    at = detect(new_app())
    assert captions(at) == [] and NO_SCENE in text(at)


def test_without_any_detection_file_the_empty_state_shows(detection_files):
    detection_files(image=False, mask=False, metrics=None)
    at = detect(new_app())
    assert EMPTY in text(at) and "Model performance" not in text(at)


@pytest.mark.parametrize("state", ["all files", "metrics only", "truncated metrics", "no mask", "no scene",
                                   "detection folder missing", "demo"])
def test_no_overall_accuracy_section_in_any_state(detection_files, state):
    if state == "all files":
        detection_files(spill=True)
    elif state == "metrics only":
        detection_files(image=False, mask=False)
    elif state == "truncated metrics":
        detection_files(metrics=json.dumps(METRICS)[:40])
    elif state == "no mask":
        detection_files(mask=False)
    elif state == "no scene":
        detection_files(image=False, mask=False, spill=True)
    elif state == "detection folder missing":
        config.DETECTION_DIR.rmdir()
    at = detect(new_app(demo=state == "demo"))
    page = text(at)
    shown = [t for t in SECTION_TEXT if t in page]
    assert not shown, shown
    if state == "truncated metrics":  # metrics.json is not shown, so a broken one is no viewer-facing issue
        assert not any("couldn" in b for b in bodies(at, "gog-notice"))
