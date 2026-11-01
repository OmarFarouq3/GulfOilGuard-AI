"""Tolerant file readers shared by all loaders.

Every reader returns ``(value, warning)``:
- missing file   -> ``(None, None)``
- malformed file -> ``(None, "readable warning")``
- valid file     -> ``(value, None)``

Results are cached with ``st.cache_data`` using the file's modification time as part
of the key, so a new or overwritten output shows up on the next rerun without
restarting Streamlit.
"""

from __future__ import annotations

import io
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st
from PIL import Image

import config

GEOMETRY_TYPES = {"Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"}


def mtime(path: Path) -> float | None:
    """Return the file's modification time, or None if it does not exist."""
    try:
        return path.stat().st_mtime if path.is_file() else None
    except OSError:
        return None


def format_mtime(path: Path) -> str | None:
    """Return a human-readable last-modified time, or None if missing."""
    value = mtime(path)
    return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S") if value else None


def display_path(path: Path) -> str:
    """Show paths relative to the repo root (or the outputs folder's parent) when possible."""
    for base in (config.REPO_ROOT, config.OUTPUTS_DIR.parent):
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            continue
    return str(path)


# --- JSON ----------------------------------------------------------------------


@st.cache_data(show_spinner=False)
def _read_json_cached(path_str: str, _mtime: float) -> tuple[Any, str | None]:
    path = Path(path_str)
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as exc:
        return None, f"`{display_path(path)}` is not valid JSON (line {exc.lineno}: {exc.msg})."
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"Could not read `{display_path(path)}`: {exc}"


def read_json(path: Path) -> tuple[Any, str | None]:
    """Read a JSON file tolerantly (see module docstring)."""
    stamp = mtime(path)
    if stamp is None:
        return None, None
    return _read_json_cached(str(path), stamp)


def read_json_object(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Read a JSON file that must contain an object (dict)."""
    value, warning = read_json(path)
    if value is not None and not isinstance(value, dict):
        return None, f"`{display_path(path)}` should contain a JSON object, found {type(value).__name__}."
    return value, warning


# --- GeoJSON ---------------------------------------------------------------------


def iter_positions(coords: Any):
    """Yield every [lon, lat] position from nested GeoJSON coordinates."""
    if isinstance(coords, (list, tuple)) and coords and isinstance(coords[0], (int, float)):
        yield coords
    elif isinstance(coords, (list, tuple)):
        for item in coords:
            yield from iter_positions(item)


def _geometry_problem(geometry: Any) -> str | None:
    """Return why a geometry is unusable, or None if it is fine."""
    if not isinstance(geometry, dict):
        return "missing geometry"
    if geometry.get("type") not in GEOMETRY_TYPES:
        return f"unsupported geometry type {geometry.get('type')!r}"
    positions = list(iter_positions(geometry.get("coordinates")))
    if not positions:
        return "empty coordinates"
    for pos in positions:
        if len(pos) < 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in pos[:2]):
            return "non-numeric coordinates"
        lon, lat = pos[0], pos[1]
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            return f"coordinate out of range ({lon}, {lat}); GeoJSON order is [longitude, latitude]"
    return None


@st.cache_data(show_spinner=False)
def _read_geojson_cached(path_str: str, _mtime: float) -> tuple[dict | None, str | None]:
    path = Path(path_str)
    data, warning = _read_json_cached(path_str, _mtime)
    if warning:
        return None, warning
    name = display_path(path)
    if isinstance(data, dict) and data.get("type") == "Feature":
        data = {"type": "FeatureCollection", "features": [data]}
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        return None, f"`{name}` should be a GeoJSON FeatureCollection."
    features = data.get("features")
    if not isinstance(features, list):
        return None, f"`{name}` has no `features` list."

    valid, problems = [], []
    for i, feature in enumerate(features):
        if not isinstance(feature, dict):
            problems.append(f"feature {i}: not an object")
            continue
        problem = _geometry_problem(feature.get("geometry"))
        if problem:
            problems.append(f"feature {i}: {problem}")
            continue
        if not isinstance(feature.get("properties"), dict):
            feature = {**feature, "properties": {}}
        valid.append(feature)

    warning = None
    if problems:
        shown = "; ".join(problems[:3]) + (" ..." if len(problems) > 3 else "")
        warning = f"`{name}`: skipped {len(problems)} of {len(features)} features ({shown})."
    if not valid:
        return None, warning or f"`{name}` contains no features."
    return {"type": "FeatureCollection", "features": valid}, warning


def read_geojson(path: Path) -> tuple[dict | None, str | None]:
    """Read a GeoJSON FeatureCollection, dropping invalid features with a warning.

    A file may be returned together with a warning when only some features are bad.
    A file with no usable features returns None (plus a warning).
    """
    stamp = mtime(path)
    if stamp is None:
        return None, None
    return _read_geojson_cached(str(path), stamp)


# --- Images ----------------------------------------------------------------------


@st.cache_data(show_spinner=False)
def _read_image_cached(path_str: str, _mtime: float) -> tuple[bytes | None, str | None]:
    path = Path(path_str)
    try:
        raw = path.read_bytes()
        with Image.open(io.BytesIO(raw)) as img:
            img.verify()
        return raw, None
    except Exception as exc:  # PIL raises many exception types for bad images
        return None, f"`{display_path(path)}` is not a readable image ({type(exc).__name__})."


def read_image(path: Path) -> tuple[bytes | None, str | None]:
    """Read and verify an image file, returning its raw bytes."""
    stamp = mtime(path)
    if stamp is None:
        return None, None
    return _read_image_cached(str(path), stamp)


def as_float(value: Any) -> float | None:
    """Convert a JSON value to a finite float, or None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
