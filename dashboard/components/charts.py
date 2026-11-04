"""Display names and one-line meanings of the segmentation scores (the per-image "Score for this image" tiles)."""

from __future__ import annotations

METRIC_LABELS = {"dice": "Dice", "iou": "IoU", "precision": "Precision", "recall": "Recall"}
METRIC_HINTS = {
    "dice": "Overlap between detected and true oil",
    "iou": "Shared area over combined area",
    "precision": "Flagged pixels that really are oil",
    "recall": "Real oil pixels that were found",
}
