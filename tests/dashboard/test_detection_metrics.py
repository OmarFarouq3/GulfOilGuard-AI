"""Detection scores and the Detect status: metrics.json in both shapes, summary.json, bad files, mixed vs simulated.

Formats checked against the writers: detection/evaluate.py (``"metrics"`` nested, ``"pairs"``,
absolute ``"checkpoint"``, file metrics.json) and detection/report.py (``"micro"`` nested,
file summary.json).
"""

from __future__ import annotations

import json
from typing import get_args

import pytest

import config
from components.data import Stage, Status, _stage, combined_status
from components.labels import STAGE_STATUS
from services.detection_loader import load_detection, parse_metrics
from services.models import DetectionData, DetectionScene

SCORES = {"dice": 0.87, "iou": 0.77, "precision": 0.85, "recall": 0.89}
EVALUATE_PY = {"checkpoint": "C:/Users/someone/models/oil_unet/best.pth", "epoch": 12, "pairs": 1615,
               "threshold": 0.5, "image_size": 256, "aggregation": "global pixel counts (micro)",
               "metrics": SCORES, "counts": {"true_positive": 10},
               "limitations": "Validation split used for selection."}
REPORT_PY = {"threshold": 0.5, "n_images": 1615, "n_with_oil": 900, "n_empty_reference": 715,
             "micro": {"dice": 0.86, "iou": 0.75, "precision": 0.84, "recall": 0.88},
             "macro_images_with_oil": {"dice": 0.7, "iou": 0.6, "precision": 0.7, "recall": 0.8},
             "threshold_sweep": {"0.50": SCORES}}


def parsed(raw) -> DetectionData:
    data = DetectionData()
    parse_metrics(raw, data)
    return data


# --- Shapes -----------------------------------------------------------------------------------------


def test_top_level_scores():
    data = parsed({**SCORES, "model": "U-Net", "split": "val"})
    assert data.metrics == SCORES and data.metrics_info == {"model": "U-Net", "split": "val"} and not data.warnings


def test_evaluate_py_shape():
    data = parsed(EVALUATE_PY)
    assert data.metrics == SCORES and not data.warnings
    info = data.metrics_info
    assert info["checkpoint"] == "best.pth"  # no local path
    assert info["n_images"] == 1615 and "pairs" not in info and "metrics" not in info
    assert info["limitations"] == "Validation split used for selection."


def test_report_py_summary_shape_uses_micro_scores():
    data = parsed(REPORT_PY)
    assert data.metrics == REPORT_PY["micro"] and data.metrics_info["n_images"] == 1615 and not data.warnings


def test_top_level_wins_over_nested():
    assert parsed({**SCORES, "metrics": {"dice": 0.1}}).metrics == SCORES


@pytest.mark.parametrize("raw, warned", [
    ({"metrics": [0.8, 0.7]}, True),            # nested scores not an object
    ({"metrics": "high"}, True),
    ({"micro": None}, True),
    ({"dice": "0.8"}, True),                    # not a number
    ({"dice": 1.7, "iou": -0.1}, True),         # outside [0, 1]
    ({"metrics": {"dice": float("nan")}}, True),
    ({"model": "U-Net"}, False),                # no scores at all
    ({}, False),
])
def test_malformed_scores_give_no_metrics_and_no_crash(raw, warned):
    data = parsed(raw)
    assert data.metrics is None and data.metrics_info == {}
    assert bool(data.warnings) == warned


# --- Files in outputs/detection/ ---------------------------------------------------------------------


@pytest.fixture
def detection_dir():
    config.DETECTION_DIR.mkdir(parents=True, exist_ok=True)
    yield config.DETECTION_DIR
    for path in config.DETECTION_DIR.glob("*"):
        path.unlink()


def write(directory, name, content):
    text = content if isinstance(content, str) else json.dumps(content)
    (directory / name).write_text(text, encoding="utf-8")


def test_files_metrics_json_in_evaluate_format(detection_dir):
    write(detection_dir, "metrics.json", EVALUATE_PY)
    data = load_detection()
    assert data.metrics == SCORES and data.metrics_info["checkpoint"] == "best.pth"


def test_files_summary_json_is_the_fallback(detection_dir):
    write(detection_dir, "summary.json", REPORT_PY)
    assert load_detection().metrics == REPORT_PY["micro"]


def test_files_metrics_json_wins_over_summary_json(detection_dir):
    write(detection_dir, "metrics.json", EVALUATE_PY)
    write(detection_dir, "summary.json", REPORT_PY)
    assert load_detection().metrics == SCORES


@pytest.mark.parametrize("content", ["{not json", "[1, 2, 3]", '"text"', json.dumps({"metrics": [1]})])
def test_files_malformed_metrics_json_falls_back_without_crash(detection_dir, content):
    write(detection_dir, "metrics.json", content)
    data = load_detection()
    assert data is not None and data.metrics is None and data.warnings  # explained under Diagnostics
    write(detection_dir, "summary.json", REPORT_PY)
    assert load_detection().metrics == REPORT_PY["micro"]


# --- Detect status: mixed vs simulated ---------------------------------------------------------------


def model_detection(**overrides) -> DetectionData:
    data = DetectionData(scenes=[DetectionScene("img-1", b"png")], synthetic=True, mask_source="model",
                         outline_simulated=True)
    for key, value in overrides.items():
        setattr(data, key, value)
    return data


def test_real_mask_with_simulated_location_is_mixed():
    assert _stage("detect", model_detection()).status == "mixed"


@pytest.mark.parametrize("overrides", [
    {"mask_source": "simulated"},               # demo scene
    {"is_mock": True},
    {"metrics_info": {"synthetic": True}},      # illustrative scores next to the real mask
])
def test_anything_else_synthetic_stays_simulated(overrides):
    assert _stage("detect", model_detection(**overrides)).status == "simulated"


def test_every_status_has_wording():
    assert set(STAGE_STATUS) == set(get_args(Status))
    assert STAGE_STATUS["mixed"][1] == "Real detection, simulated location"
    assert STAGE_STATUS["simulated"][1] == "Simulated scenario"


def test_mixed_counts_as_simulated_for_the_headline_numbers():
    stages = {"detect": Stage("detect", object(), "mixed", False), "predict": Stage("predict", None, "empty", False)}
    assert combined_status(stages) == "simulated"


# --- summary.json in outputs/report/ (report.py's default folder) ------------------------------------


@pytest.fixture
def report_dir():
    config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    yield config.REPORT_DIR
    for path in config.REPORT_DIR.glob("*"):
        path.unlink()


def test_files_summary_json_in_the_report_folder_is_used(detection_dir, report_dir):
    write(report_dir, "summary.json", REPORT_PY)
    assert load_detection().metrics == REPORT_PY["micro"]


def test_files_metrics_json_wins_over_the_report_summary(detection_dir, report_dir):
    write(detection_dir, "metrics.json", {**SCORES, "split": "val"})
    write(report_dir, "summary.json", REPORT_PY)
    data = load_detection()
    assert data.metrics == SCORES and data.metrics_info["split"] == "val"


def test_files_detection_summary_wins_over_the_report_summary(detection_dir, report_dir):
    write(detection_dir, "summary.json", {**REPORT_PY, "micro": SCORES})
    write(report_dir, "summary.json", REPORT_PY)
    assert load_detection().metrics == SCORES


def test_galleries_skip_unreadable_files_with_a_warning(report_dir):
    from dashboard_testkit import make_image

    from services.detection_loader import load_galleries
    assert load_galleries() == ([], [])
    make_image(report_dir / "gallery_best.png")
    (report_dir / "gallery_median.png").write_bytes(b"not a png")
    make_image(report_dir / "gallery_worst.png", seed=1)
    shown, warnings = load_galleries()
    assert [caption for caption, _png in shown] == ["Best", "Worst"]
    assert len(warnings) == 1 and "gallery_median.png" in warnings[0]


# --- Details allowlist and path hiding (detection test pass item 1) -----------------------------------


def test_only_allowlisted_details_reach_the_viewer():
    raw = {**SCORES, "model": "U-Net", "split": "val", "n_images": 1615, "threshold": 0.5, "epoch": 12,
           "aggregation": "micro", "created": "2026-11-03", "limitations": "Val chose the checkpoint.",
           "checkpoint": "C:/Users/someone/models/best.pth", "data_dir": "C:/Users/someone/sar_data",
           "notes": "secret", "per_epoch": [0.1], "image_size": 256, "n_with_oil": 900, "counts": {"tp": 1},
           "checkpoint_sha256": "a" * 64, "synthetic": False}
    data = parsed(raw)
    assert data.metrics_info == {"model": "U-Net", "split": "val", "n_images": 1615, "threshold": 0.5, "epoch": 12,
                                 "aggregation": "micro", "created": "2026-11-03",
                                 "limitations": "Val chose the checkpoint.", "checkpoint": "best.pth"}
    assert data.warnings == []  # unknown keys are no viewer-facing issue ...
    assert data.notes == ["`metrics.json`: not shown to viewers: `data_dir`, `notes`, `per_epoch`."]  # ... names only
    assert "sar_data" not in str(data.notes) and "secret" not in str(data.notes)


def test_synthetic_flag_is_kept_for_the_status_but_is_no_detail():
    assert parsed({**SCORES, "synthetic": True}).metrics_info == {"synthetic": True}


@pytest.mark.parametrize("value, shown", [
    ("C:/Users/someone/models/best.pth", "best.pth"),
    ("C:\\Users\\someone\\best.pth", "best.pth"),
    ("/home/someone/runs/unet/best.pth", "best.pth"),
    ("\\\\server\\share\\best.pth", "best.pth"),
    ("runs/unet_refined_sar/best.pth", "best.pth"),
    ("U-Net (unet_refined_sar)", "U-Net (unet_refined_sar)"),
    ("train/val split", "train/val split"),
])
def test_path_like_values_are_reduced_to_file_names(value, shown):
    assert parsed({**SCORES, "model": value}).metrics_info["model"] == shown


@pytest.mark.parametrize("value", [
    "C:\\Users\\someone\\Documents\\UOS\\Hack for Earth Competition\\GulfOilGuard-AI\\checkpoints\\unet_best.pth",
    "C:/Users/someone/My Models/unet_best.pth",
    "\\\\server\\team share\\unet_best.pth",
])
def test_windows_paths_with_spaces_are_reduced_whole(value):
    """Regression: the real repo path has spaces; its middle words must not leak ("Hack for Earth")."""
    assert parsed({**SCORES, "checkpoint": value}).metrics_info["checkpoint"] == "unet_best.pth"
    assert parsed({**SCORES, "limitations": f"Scored with {value} only."}).metrics_info["limitations"] == \
        "Scored with unet_best.pth only."


def test_paths_inside_free_text_are_reduced_too():
    info = parsed({**SCORES, "limitations": "Masks from C:/Users/someone/data/masks were used."}).metrics_info
    assert info["limitations"] == "Masks from masks were used." and "someone" not in info["limitations"]


# --- One fully valid source, never a mix (detection test pass item 4) -----------------------------------

BAD_METRICS = {"dice": 1.5, "iou": -0.2, "precision": 0.85, "recall": 0.89, "model": "from metrics.json", "split": "val"}
FULL_SUMMARY = {**REPORT_PY, "micro": {"dice": 0.81, "iou": 0.72, "precision": 0.83, "recall": 0.84}}


def test_fully_valid_detection_summary_beats_partly_invalid_metrics(detection_dir):
    write(detection_dir, "metrics.json", BAD_METRICS)
    write(detection_dir, "summary.json", FULL_SUMMARY)
    data = load_detection()
    assert data.metrics == FULL_SUMMARY["micro"]  # all four from summary.json, none from metrics.json
    assert "model" not in data.metrics_info and data.metrics_info["n_images"] == 1615
    assert any("dice" in w for w in data.warnings)  # the broken file is still reported under Diagnostics


def test_fully_valid_report_summary_beats_partly_invalid_metrics(detection_dir, report_dir):
    write(detection_dir, "metrics.json", BAD_METRICS)
    write(report_dir, "summary.json", FULL_SUMMARY)
    assert load_detection().metrics == FULL_SUMMARY["micro"]


def test_incomplete_but_valid_metrics_lose_to_a_complete_summary(detection_dir, report_dir):
    write(detection_dir, "metrics.json", {"dice": 0.9, "iou": 0.8})  # valid, but only two scores
    write(report_dir, "summary.json", FULL_SUMMARY)
    assert load_detection().metrics == FULL_SUMMARY["micro"]


def test_without_a_fully_valid_source_the_first_partial_one_is_shown(detection_dir, report_dir):
    write(detection_dir, "metrics.json", BAD_METRICS)
    write(report_dir, "summary.json", {**REPORT_PY, "micro": {"dice": 2.0, "iou": 0.5, "precision": 0.5,
                                                               "recall": 0.5}})
    data = load_detection()
    assert data.metrics == {"precision": 0.85, "recall": 0.89}  # "—" for dice and iou, nothing from summary.json
    assert data.metrics_info["model"] == "from metrics.json"
    assert any("dice" in w for w in data.warnings)


def test_fully_valid_metrics_json_still_wins(detection_dir, report_dir):
    write(detection_dir, "metrics.json", {**SCORES, "split": "val"})
    write(report_dir, "summary.json", FULL_SUMMARY)
    data = load_detection()
    assert data.metrics == SCORES and data.warnings == []
