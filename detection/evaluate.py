"""Interfaces for segmentation metrics and prediction export."""

from pathlib import Path
from typing import TypedDict

from shared.schemas import DetectionOutput


class SegmentationMetrics(TypedDict):
    dice: float
    iou: float
    precision: float
    recall: float


def evaluate(checkpoint_path: Path, image_dir: Path, mask_dir: Path) -> SegmentationMetrics:
    """Evaluate a held-out split using an agreed oil-class encoding."""
    raise NotImplementedError("Implement Dice, IoU, precision, and recall evaluation.")


def predict(checkpoint_path: Path, image_path: Path, output_dir: Path) -> DetectionOutput:
    """Export a mask; leave geographic coordinates absent without georeferencing."""
    raise NotImplementedError("Implement mask prediction and optional georeferencing.")
