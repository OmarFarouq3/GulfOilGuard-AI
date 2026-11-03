"""Load detection module outputs from ``outputs/detection/`` and validate them against shared/schemas.py.

Files (all optional individually):
- ``image.png``, ``mask.png``, ``overlay.png``: the default scene
- ``<image_id>_image.png``, ``<image_id>_mask.png``, ``<image_id>_overlay.png``: extra scenes
- ``metrics.json``: scores ``dice``, ``iou``, ``precision``, ``recall`` in [0, 1] (not in
  shared/schemas.py; same keys as ``SegmentationMetrics`` in detection/evaluate.py), either at
  the top level or nested under ``"metrics"`` as ``detection/evaluate.py --output-dir`` writes it
- ``summary.json`` (used when metrics.json has no scores): ``detection/report.py`` output, with
  the global (micro) scores nested under ``"micro"``
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


# Where the evaluation scripts nest their scores: evaluate.py -> "metrics", report.py -> "micro".
NESTED_SCORE_KEYS = ("metrics", "micro")


def _score_source(raw: dict, data: DetectionData, name: str) -> dict:
    """The object holding dice / iou / ...: the top level, else the first nested score object."""
    if any(key in raw for key in config.DETECTION_METRICS):
        return raw
    for key in NESTED_SCORE_KEYS:
        if key in raw:
            if isinstance(raw[key], dict):
                return raw[key]
            data.warnings.append(f"`{name}`: `{key}` should be an object of scores.")
    return {}


def _evaluation_info(raw: dict) -> dict[str, Any]:
    """Details next to the scores, without the scores themselves or local paths."""
    info = {k: v for k, v in raw.items() if k not in (*config.DETECTION_METRICS, "per_class", *NESTED_SCORE_KEYS)}
    if isinstance(info.get("checkpoint"), str):
        info["checkpoint"] = Path(info["checkpoint"]).name  # evaluate.py stores an absolute path
    if "pairs" in info and "n_images" not in info:
        info["n_images"] = info.pop("pairs")  # evaluate.py's name for the number of images
    return info


def parse_metrics(raw: dict | None, data: DetectionData, name: str = "metrics.json") -> None:
    """Fill metric fields; every score must be a number in [0, 1]."""
    if raw is None:
        return
    data.synthetic |= raw.get("synthetic") is True
    source = _score_source(raw, data, name)
    metrics = {}
    for key in config.DETECTION_METRICS:
        if key in source:
            try:
                metrics[key] = _score(source[key], key)
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

    data.metrics_info = _evaluation_info(raw) if data.metrics else {}


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


def _read_scene(image_id: str, files: dict[str, Path], data: DetectionData) -> DetectionScene | None:
    scene = DetectionScene(image_id=image_id)
    for kind, path in files.items():
        content, warning = read_image(path)
        if warning:
            data.warnings.append(warning)
        setattr(scene, kind, content)
    if scene.overlay is None and scene.image and scene.mask:
        scene.overlay = compose_overlay(scene.image, scene.mask)
    return scene if scene.image or scene.mask or scene.overlay else None


def _read_metrics(data: DetectionData) -> None:
    """metrics.json first; summary.json (report.py) only when metrics.json gives no scores."""
    for key in ("metrics", "summary"):
        path = config.DETECTION_FILES[key]
        raw, warning = read_json_object(path)
        if warning:
            data.warnings.append(warning)
        parse_metrics(raw, data, path.name)
        if data.metrics:
            return


def load_scene(image_id: str) -> DetectionData | None:
    """Only the ``<image_id>_*`` scene plus ``metrics.json`` (the model's evaluation scores).

    ``spill.geojson`` is left out: its outlines belong to other scenes.
    """
    data = DetectionData()
    files = _scene_files(config.DETECTION_DIR).get(image_id)
    scene = _read_scene(image_id, files, data) if files else None
    if scene is None:
        return None
    data.scenes.append(scene)
    _read_metrics(data)
    return data


def load_detection() -> DetectionData | None:
    """Return detection outputs, or None if no detection files exist at all."""
    data = DetectionData()

    for image_id, files in _scene_files(config.DETECTION_DIR).items():
        scene = _read_scene(image_id, files, data)
        if scene:
            data.scenes.append(scene)
    data.scenes.sort(key=lambda s: (s.image_id != DEFAULT_SCENE, s.image_id))

    _read_metrics(data)

    collection, warning = read_geojson(config.DETECTION_FILES["spill"])
    if warning:
        data.warnings.append(warning)
    parse_spill(collection, data)

    if not data.has_content and not data.warnings:
        return None
    return data
