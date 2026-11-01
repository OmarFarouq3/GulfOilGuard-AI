"""Load detection module outputs from ``outputs/detection/`` and validate them against shared/schemas.py.

Files (all optional individually):
- ``image.png``, ``mask.png``, ``overlay.png``: the default scene
- ``<image_id>_image.png``, ``<image_id>_mask.png``, ``<image_id>_overlay.png``: extra scenes
- ``metrics.json``: ``{"dice", "iou", "precision", "recall", "per_class"?, ...}`` in [0, 1]
  (not in shared/schemas.py; same keys as ``SegmentationMetrics`` in detection/evaluate.py)
- ``spill.geojson``: oil polygons in WGS84 lon/lat. Each feature is one ``DetectionOutput``:
  ``image_id`` (required), ``confidence`` in [0, 1] (optional); ``area_km2`` is an extension.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import config
from services import schema
from services.files import read_geojson, read_image, read_json_object, validate_geojson
from services.imaging import compose_overlay
from services.models import DetectionData, DetectionScene

IMAGE_KINDS = ("image", "mask", "overlay")
DEFAULT_SCENE = "default"


def _scene_files(directory: Path) -> dict[str, dict[str, Path]]:
    """Group PNGs into scenes: ``image.png`` -> default, ``abc_mask.png`` -> image_id ``abc``."""
    scenes: dict[str, dict[str, Path]] = {}
    if not directory.is_dir():
        return scenes
    for path in sorted(directory.glob("*.png")):
        stem = path.stem
        for kind in IMAGE_KINDS:
            if stem == kind:
                scenes.setdefault(DEFAULT_SCENE, {})[kind] = path
            elif stem.endswith(f"_{kind}"):
                scenes.setdefault(stem[: -len(kind) - 1], {})[kind] = path
    return scenes


def mask_path(image_id: str) -> Path:
    """Where the mask for ``image_id`` lives (DetectionOutput.mask_path)."""
    named = config.DETECTION_DIR / f"{image_id}_mask.png"
    return named if named.exists() else config.DETECTION_FILES["mask"]


def _score(value: Any, name: str) -> float:
    return schema.number(value, name, required=True, maximum=1.0)


def parse_metrics(raw: dict | None, data: DetectionData, name: str = "metrics.json") -> None:
    """Fill metric fields; every score must be a number in [0, 1]."""
    if raw is None:
        return
    data.synthetic |= raw.get("synthetic") is True
    metrics = {}
    for key in config.DETECTION_METRICS:
        if key in raw:
            try:
                metrics[key] = _score(raw[key], key)
            except schema.SchemaError as exc:
                data.warnings.append(f"`{name}`: {exc}.")
    data.metrics = metrics or None

    per_class = raw.get("per_class")
    if isinstance(per_class, dict):
        parsed: dict[str, dict[str, float]] = {}
        for cls, values in per_class.items():
            if not isinstance(values, dict):
                data.warnings.append(f"`{name}`: per_class[{cls!r}] must be an object.")
                continue
            try:
                parsed[str(cls)] = {k: _score(values[k], f"per_class.{cls}.{k}")
                                    for k in config.DETECTION_METRICS if k in values}
            except schema.SchemaError as exc:
                data.warnings.append(f"`{name}`: {exc}.")
        data.per_class = {k: v for k, v in parsed.items() if v} or None
    elif per_class is not None:
        data.warnings.append(f"`{name}`: `per_class` should be an object of {{class: {{metric: value}}}}.")

    data.metrics_info = {k: v for k, v in raw.items() if k not in (*config.DETECTION_METRICS, "per_class")}


def parse_spill(collection: dict | None, data: DetectionData, name: str = "spill.geojson") -> None:
    """Validate each slick as a DetectionOutput; only valid slicks are drawn."""
    if collection is None:
        return
    valid = []
    for i, feature in enumerate(collection["features"]):
        geometry, props = feature["geometry"], feature["properties"]
        data.synthetic |= props.get("synthetic") is True
        if geometry["type"] not in ("Polygon", "MultiPolygon"):
            data.warnings.append(f"`{name}` feature {i}: {geometry['type']} is not a Polygon; skipped.")
            continue
        ring = geometry["coordinates"][0] if geometry["type"] == "Polygon" else geometry["coordinates"][0][0]
        try:
            schema.number(props.get("area_km2"), "area_km2")
            image_id = schema.text(props.get("image_id"), "image_id")
            detection = schema.detection_output(props, ring, mask_path(image_id))
        except schema.SchemaError as exc:
            data.warnings.append(f"`{name}` feature {i}: {exc}; skipped.")
            continue
        data.detections.append(detection)
        valid.append(feature)
    data.spill = {"type": "FeatureCollection", "features": valid} if valid else None


def build_detection(scenes: list[DetectionScene], metrics: Any, spill: Any) -> DetectionData:
    """Validate already-parsed detection objects (used for demo data)."""
    data = DetectionData(scenes=scenes)
    parse_metrics(metrics, data)
    collection, warning = validate_geojson(spill, "spill")
    data.warnings += [warning] if warning else []
    parse_spill(collection, data)
    return data


def load_detection() -> DetectionData | None:
    """Return detection outputs, or None if no detection files exist at all."""
    data = DetectionData()

    for image_id, files in _scene_files(config.DETECTION_DIR).items():
        scene = DetectionScene(image_id=image_id)
        for kind, path in files.items():
            content, warning = read_image(path)
            if warning:
                data.warnings.append(warning)
            setattr(scene, kind, content)
        if scene.overlay is None and scene.image and scene.mask:
            scene.overlay = compose_overlay(scene.image, scene.mask)
        if scene.image or scene.mask or scene.overlay:
            data.scenes.append(scene)
    data.scenes.sort(key=lambda s: (s.image_id != DEFAULT_SCENE, s.image_id))

    raw_metrics, warning = read_json_object(config.DETECTION_FILES["metrics"])
    if warning:
        data.warnings.append(warning)
    parse_metrics(raw_metrics, data)

    collection, warning = read_geojson(config.DETECTION_FILES["spill"])
    if warning:
        data.warnings.append(warning)
    parse_spill(collection, data)

    if not data.has_content and not data.warnings:
        return None
    return data
