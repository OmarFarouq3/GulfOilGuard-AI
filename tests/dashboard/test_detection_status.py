"""Detect status (mixed vs simulated), the report galleries, and what the detection loader no longer reads.

The model's overall evaluation scores (metrics.json / summary.json) were removed from the Detect page,
so load_detection ignores those files: they neither fill the page nor raise a "couldn't be displayed"
banner. services/report_loader.py still reads their split and checkpoint hash (test_report_loader.py).
The path-hiding tests that lived here now cover all text read from files (test_no_team_names.py).
"""

from __future__ import annotations

import json
from typing import get_args

import pytest

import config
from components.data import Stage, Status, _stage, combined_status
from components.labels import STAGE_STATUS
from services.detection_loader import load_detection
from services.models import DetectionData, DetectionScene

SCORES = {"dice": 0.87, "iou": 0.77, "precision": 0.85, "recall": 0.89}
EVALUATE_PY = {"checkpoint": "C:/Users/someone/models/oil_unet/best.pth", "epoch": 12, "pairs": 1615,
               "threshold": 0.5, "metrics": SCORES, "split": "val"}


@pytest.fixture
def detection_dir():
    config.DETECTION_DIR.mkdir(parents=True, exist_ok=True)
    yield config.DETECTION_DIR
    for path in config.DETECTION_DIR.glob("*"):
        path.unlink()


@pytest.fixture
def report_dir():
    config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    yield config.REPORT_DIR
    for path in config.REPORT_DIR.glob("*"):
        path.unlink()


def write(directory, name, content):
    text = content if isinstance(content, str) else json.dumps(content)
    (directory / name).write_text(text, encoding="utf-8")


# --- The overall scores are not read any more --------------------------------------------------------


@pytest.mark.parametrize("name", ["metrics.json", "summary.json"])
def test_score_files_alone_give_no_detection_result(detection_dir, name):
    write(detection_dir, name, EVALUATE_PY)
    assert load_detection() is None  # nothing for the Detect page: no scene, no slick


@pytest.mark.parametrize("content", ["{not json", '{"dice": 1.7}', "[1, 2]"])
def test_a_broken_metrics_json_raises_no_detect_warning(detection_dir, content):
    """The banner "Part of this result couldn't be displayed" is about shown content only."""
    from dashboard_testkit import make_image
    write(detection_dir, "metrics.json", content)
    make_image(detection_dir / "scene_image.png")
    data = load_detection()
    assert data is not None and data.warnings == [] and not _stage("detect", data).has_issue


def test_detection_data_has_no_score_fields():
    assert not {"metrics", "per_class", "metrics_info"} & set(DetectionData.__dataclass_fields__)


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


# --- report.py galleries ----------------------------------------------------------------------------


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
