"""Load detection module outputs from ``outputs/detection/`` and validate them against shared/schemas.py.

The model's overall evaluation scores (metrics.json / summary.json) are not read here: the Detect
page shows results for the analysed scene only. services/report_loader.py still reads the
evaluation's split and checkpoint hash from those files (per-image scores, Diagnostics).

Files (all optional individually):
- ``image.png``, ``mask.png``, ``overlay.png``: the default scene
- ``<image_id>_image.png``, ``<image_id>_mask.png``, ``<image_id>_overlay.png``: extra scenes
- ``spill.geojson``: oil polygons in WGS84 lon/lat. Each feature is one ``DetectionOutput``:
  ``image_id`` (required), ``confidence`` in [0, 1] (optional); ``area_km2`` is an extension.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import config
from services import schema
from services.files import read_geojson, read_image, validate_geojson
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


def build_detection(scenes: list[DetectionScene], spill: Any) -> DetectionData:
    """Validate already-parsed detection objects (used for demo data)."""
    data = DetectionData(scenes=scenes)
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


GALLERIES = (("gallery_best", "Best"), ("gallery_median", "Median"), ("gallery_worst", "Worst"))


def load_galleries() -> tuple[list[tuple[str, bytes]], list[str]]:
    """report.py's best / median / worst galleries as (caption, png); unreadable ones are skipped."""
    shown, warnings = [], []
    for key, caption in GALLERIES:
        content, warning = read_image(config.REPORT_FILES[key])
        if warning:
            warnings.append(f"{warning} It is left out of the galleries.")
        elif content:
            shown.append((caption, content))
    return shown, warnings


def load_scene(image_id: str) -> DetectionData | None:
    """Only the ``<image_id>_*`` scene.

    ``spill.geojson`` is left out: its outlines belong to other scenes.
    """
    data = DetectionData()
    files = _scene_files(config.DETECTION_DIR).get(image_id)
    scene = _read_scene(image_id, files, data) if files else None
    if scene is None:
        return None
    data.scenes.append(scene)
    return data


def load_detection() -> DetectionData | None:
    """Return detection outputs, or None if no detection files exist at all."""
    data = DetectionData()

    for image_id, files in _scene_files(config.DETECTION_DIR).items():
        scene = _read_scene(image_id, files, data)
        if scene:
            data.scenes.append(scene)
    data.scenes.sort(key=lambda s: (s.image_id != DEFAULT_SCENE, s.image_id))

    collection, warning = read_geojson(config.DETECTION_FILES["spill"])
    if warning:
        data.warnings.append(warning)
    parse_spill(collection, data)

    if not data.has_content and not data.warnings:
        return None
    return data
