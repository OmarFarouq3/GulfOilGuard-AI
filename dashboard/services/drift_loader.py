"""Load drift module outputs from ``outputs/drift/`` and validate them against shared/schemas.py.

- ``drift.geojson``: features with a numeric ``hours`` property (hours since release: 0, 6,
  12, 24; not in schema). Points/MultiPoints are particles, Polygons are envelopes (not in
  schema). Optional ``timestamp`` must be timezone-aware UTC (as ``TimedPosition.timestamp``).
- ``meta.json`` (optional): ``DriftOutput`` fields ``simulation_id``, ``initial_location``
  ({latitude, longitude}), ``positions`` ([{timestamp, coordinate}]), ``duration_hours``;
  ``start_time`` (UTC); model inputs (not in schema): ``wind_speed_m_per_s``, ``wind_from_deg``,
  ``current_speed_m_per_s``, ``current_to_deg``, ``wind_source``, ``current_source``,
  ``model``, ``oil_type``, ``n_particles``.
"""

from __future__ import annotations

from typing import Any

import config
from services import schema
from services.files import as_float, read_geojson, read_json_object, validate_geojson
from services.models import DriftData

# Tolerance when cross-checking `hours` against timestamps (hours).
HOURS_TOLERANCE = 0.05
NONNEGATIVE_FIELDS = ("wind_speed_m_per_s", "current_speed_m_per_s", "n_particles")
DIRECTION_FIELDS = ("wind_from_deg", "current_to_deg")


def parse_features(collection: dict | None, data: DriftData, name: str = "drift.geojson") -> None:
    """Group features by `hours`, validating hours and UTC timestamps."""
    if collection is None:
        return
    skipped = 0
    for i, feature in enumerate(collection["features"]):
        props = feature["properties"]
        data.synthetic |= props.get("synthetic") is True
        hours = as_float(props.get("hours"))
        if hours is None or hours < 0:
            skipped += 1
            continue
        if "timestamp" in props:
            try:
                schema.utc(props["timestamp"])
            except schema.SchemaError as exc:
                data.warnings.append(f"`{name}` feature {i}: {exc}; skipped.")
                continue
        key = int(hours) if hours.is_integer() else hours
        data.steps.setdefault(key, []).append(feature)
    if skipped:
        data.warnings.append(f"`{name}`: {skipped} features have no valid nonnegative `hours`; skipped.")


def parse_meta(meta: dict | None, data: DriftData, name: str = "meta.json") -> None:
    """Validate DriftOutput fields, start_time and model inputs; cross-check hours vs timestamps."""
    if meta is None:
        return
    data.synthetic |= meta.get("synthetic") is True
    clean = dict(meta)
    try:
        data.trajectory = schema.drift_output(meta)
    except schema.SchemaError as exc:
        data.warnings.append(f"`{name}`: {exc}.")
    for key in NONNEGATIVE_FIELDS:
        try:
            schema.number(meta.get(key), key)
        except schema.SchemaError as exc:
            data.warnings.append(f"`{name}`: {exc}.")
            clean.pop(key, None)
    for key in DIRECTION_FIELDS:
        try:
            schema.number(meta.get(key), key, maximum=360)
        except schema.SchemaError as exc:
            data.warnings.append(f"`{name}`: {exc}.")
            clean.pop(key, None)
    if "start_time" in meta:
        try:
            schema.utc(meta["start_time"], "start_time")
        except schema.SchemaError as exc:
            data.warnings.append(f"`{name}`: {exc}.")
            clean.pop("start_time")
    data.meta = clean
    _check_hours(data, name)


def _check_hours(data: DriftData, name: str) -> None:
    """If a release time is known, each feature's `hours` must match its timestamp."""
    start = None
    if data.trajectory and data.trajectory.positions:
        start = data.trajectory.positions[0].timestamp
    elif data.meta and "start_time" in data.meta:
        start = schema.utc(data.meta["start_time"])
    if start is None:
        return
    for hours, features in data.steps.items():
        for feature in features:
            stamp = feature["properties"].get("timestamp")
            if stamp and abs((schema.utc(stamp) - start).total_seconds() / 3600 - hours) > HOURS_TOLERANCE:
                data.warnings.append(f"`drift.geojson`: hours={hours} does not match timestamp {stamp}.")
                return


def build_drift(collection: Any, meta: Any) -> DriftData:
    """Validate already-parsed drift objects (used for demo data)."""
    data = DriftData()
    valid, warning = validate_geojson(collection, "drift")
    data.warnings += [warning] if warning else []
    parse_features(valid, data)
    parse_meta(meta, data)
    return data


def load_drift() -> DriftData | None:
    """Return drift outputs grouped by forecast hour, or None if no drift files exist."""
    data = DriftData()

    collection, warning = read_geojson(config.DRIFT_FILES["drift"])
    if warning:
        data.warnings.append(warning)
    parse_features(collection, data)

    meta, warning = read_json_object(config.DRIFT_FILES["meta"])
    if warning:
        data.warnings.append(warning)
    parse_meta(meta, data)

    if not data.has_content and data.meta is None and not data.warnings:
        return None
    return data
