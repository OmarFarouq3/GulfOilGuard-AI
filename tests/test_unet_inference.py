"""Real U-Net inference: checkpoints/unet_best.pth on a real validation image, nothing mocked.

Loads the trained checkpoint, predicts the mask of assets/images/val/palsar_0.png, checks the mask
(size, binary 0/255, values in range) and computes Dice / IoU / precision / recall against the
labelled mask (detection/masks/val, the convention in detection/README.md). The scores must match
what outputs/report/per_image_metrics.csv recorded for the same image, and evaluate() over a small
labelled folder must give the same counts-based metrics.

Needs torch, the checkpoint and two validation images with their masks (palsar_0, sentinel_12). They are
git-ignored data, so on a machine without them the tests skip and say which file is missing
(tests/README.md says where each file comes from).
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

# A plain import, not pytest.importorskip: `unittest discover` imports this module too (it collects no
# test from it, these are pytest functions) and must not crash where torch is missing.
try:
    import torch  # noqa: F401
    from detection.evaluate import evaluate, load_model, predict
    from detection.metrics import metrics_from_counts
except ImportError as exc:
    torch, import_error = None, exc
else:
    import_error = None

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = ROOT / "checkpoints" / "unet_best.pth"
IMAGE = ROOT / "assets" / "images" / "val" / "palsar_0.png"
TRUTH = ROOT / "detection" / "masks" / "val" / "palsar_0.png"
REPORT = ROOT / "outputs" / "report" / "per_image_metrics.csv"

SECOND = "sentinel_12.png"  # the second image of the labelled-folder test
missing = [p.relative_to(ROOT).as_posix() for p in (CHECKPOINT, IMAGE, TRUTH, IMAGE.parent / SECOND, TRUTH.parent / SECOND)
           if not p.is_file()]
pytestmark = [
    pytest.mark.skipif(torch is None, reason=f"torch is not installed ({import_error}); pip install -r requirements.txt"),
    pytest.mark.skipif(bool(missing), reason=f"missing real data: {', '.join(missing)} (masks: detection/masks/val "
                                              "from the dataset's masks.zip)"),
]


def counts(predicted: np.ndarray, truth: np.ndarray) -> tuple[int, int, int, int]:
    """TP, FP, FN, TN of two boolean masks (written out here, not taken from detection.metrics)."""
    return (int((predicted & truth).sum()), int((predicted & ~truth).sum()),
            int((~predicted & truth).sum()), int((~predicted & ~truth).sum()))


@pytest.fixture(scope="module")
def prediction(tmp_path_factory) -> tuple[np.ndarray, np.ndarray]:
    out = tmp_path_factory.mktemp("unet")
    result = predict(CHECKPOINT, IMAGE, out, device="cpu")
    assert result.image_id == "palsar_0" and Path(result.mask_path).is_file()
    with Image.open(result.mask_path) as mask, Image.open(TRUTH) as truth:
        return np.asarray(mask), np.asarray(truth.convert("L"))


def test_checkpoint_loads_as_a_trained_unet():
    model, checkpoint = load_model(CHECKPOINT)
    assert not model.training
    assert {"config", "model_state_dict", "epoch"} <= set(checkpoint)
    assert checkpoint["config"]["out_channels"] == 1 and 0 < checkpoint["config"]["threshold"] < 1


def test_mask_has_the_image_size_and_is_binary(prediction):
    mask, _truth = prediction
    with Image.open(IMAGE) as source:
        assert mask.shape == (source.height, source.width)
    assert mask.dtype == np.uint8 and set(np.unique(mask)) <= {0, 255}
    oil = (mask == 255).mean()
    assert 0.0 < oil < 1.0  # this scene has oil and sea; an all-black or all-white mask means a broken model


def test_scores_against_the_labelled_mask_match_the_report(prediction):
    mask, truth = prediction
    tp, fp, fn, tn = counts(mask >= 128, truth >= 128)
    assert tp + fp + fn + tn == mask.size
    dice, iou = 2 * tp / (2 * tp + fp + fn), tp / (tp + fp + fn)
    precision, recall = tp / (tp + fp), tp / (tp + fn)
    for value in (dice, iou, precision, recall):
        assert 0.0 <= value <= 1.0
    assert iou == pytest.approx(dice / (2 - dice))  # Dice and IoU are tied: IoU = D / (2 - D)
    shared = metrics_from_counts((tp, fp, fn, tn))  # the project's formulas give the same numbers
    assert shared == pytest.approx({"dice": dice, "iou": iou, "precision": precision, "recall": recall})
    if REPORT.is_file():
        rows = {r["file"]: r for r in csv.DictReader(REPORT.open(encoding="utf-8"))}
        recorded = rows["palsar_0.png"]
        assert int(recorded["ref_oil_pixels"]) == tp + fn  # same labelled mask
        for key, value in (("dice", dice), ("iou", iou), ("precision", precision), ("recall", recall)):
            assert float(recorded[key]) == pytest.approx(value, abs=0.01), key


def test_evaluate_on_a_labelled_folder_computes_the_metrics(tmp_path):
    images, masks = tmp_path / "images", tmp_path / "masks"
    images.mkdir(), masks.mkdir()
    for name in ("palsar_0.png", SECOND):
        shutil.copy(IMAGE.parent / name, images / name)
        shutil.copy(TRUTH.parent / name, masks / name)
    metrics = evaluate(CHECKPOINT, images, masks, device="cpu", batch_size=2)
    assert set(metrics) == {"dice", "iou", "precision", "recall"}
    assert all(0.0 <= v <= 1.0 for v in metrics.values())
    assert metrics["dice"] > 0.5  # the trained model finds most of the oil in these two scenes
