"""Load detection module outputs from ``outputs/detection/``.

Files (all optional individually):
- ``image.png``, ``mask.png``, ``overlay.png``: the default scene
- ``<scene>_image.png``, ``<scene>_mask.png``, ``<scene>_overlay.png``: extra scenes
- ``metrics.json``: ``{"dice", "iou", "precision", "recall", "per_class"?, ...}``
- ``spill.geojson``: oil polygons in WGS84 lon/lat
"""

from __future__ import annotations

from pathlib import Path

import config
from services.files import as_float, read_geojson, read_image, read_json_object
from services.imaging import compose_overlay
from services.models import DetectionData, DetectionScene

IMAGE_KINDS = ("image", "mask", "overlay")


def _scene_files(directory: Path) -> dict[str, dict[str, Path]]:
    """Group PNGs into scenes: ``image.png`` -> default, ``abc_mask.png`` -> scene ``abc``."""
    scenes: dict[str, dict[str, Path]] = {}
    if not directory.is_dir():
        return scenes
    for path in sorted(directory.glob("*.png")):
        stem = path.stem
        for kind in IMAGE_KINDS:
            if stem == kind:
                scenes.setdefault("default", {})[kind] = path
            elif stem.endswith(f"_{kind}"):
                scenes.setdefault(stem[: -len(kind) - 1], {})[kind] = path
    return scenes


def _parse_metrics(raw: dict, data: DetectionData) -> None:
    """Fill metric fields from metrics.json, warning about non-numeric values."""
    metrics = {}
    for key in config.DETECTION_METRICS:
        if key in raw:
            value = as_float(raw[key])
            if value is None:
                data.warnings.append(f"`metrics.json`: `{key}` is not a number ({raw[key]!r}).")
            else:
                metrics[key] = value
    data.metrics = metrics or None

    per_class = raw.get("per_class")
    if isinstance(per_class, dict):
        parsed = {
            str(name): {k: v for k in config.DETECTION_METRICS if (v := as_float(values.get(k))) is not None}
            for name, values in per_class.items()
            if isinstance(values, dict)
        }
        data.per_class = {k: v for k, v in parsed.items() if v} or None
    elif per_class is not None:
        data.warnings.append("`metrics.json`: `per_class` should be an object of {class: {metric: value}}.")

    data.metrics_info = {
        k: v for k, v in raw.items() if k not in (*config.DETECTION_METRICS, "per_class")
    }


def load_detection() -> DetectionData | None:
    """Return detection outputs, or None if no detection files exist at all."""
    data = DetectionData()

    for scene_id, files in _scene_files(config.DETECTION_DIR).items():
        scene = DetectionScene(scene_id=scene_id)
        for kind, path in files.items():
            content, warning = read_image(path)
            if warning:
                data.warnings.append(warning)
            setattr(scene, kind, content)
        if scene.overlay is None and scene.image and scene.mask:
            scene.overlay = compose_overlay(scene.image, scene.mask)
        if scene.image or scene.mask or scene.overlay:
            data.scenes.append(scene)
    data.scenes.sort(key=lambda s: (s.scene_id != "default", s.scene_id))

    raw_metrics, warning = read_json_object(config.DETECTION_FILES["metrics"])
    if warning:
        data.warnings.append(warning)
    if raw_metrics is not None:
        _parse_metrics(raw_metrics, data)

    data.spill, warning = read_geojson(config.DETECTION_FILES["spill"])
    if warning:
        data.warnings.append(warning)

    if not data.has_content and not data.warnings:
        return None
    return data
