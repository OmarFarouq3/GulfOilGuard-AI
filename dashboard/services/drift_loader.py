"""Load drift module outputs from ``outputs/drift/``.

- ``drift.geojson``: features with a numeric ``hours`` property (0 = release, 6, 12, 24).
  Geometries may be Points/MultiPoints (particles) or Polygons (envelopes).
- ``meta.json`` (optional): start_time, model, wind_source, current_source, ...
"""

from __future__ import annotations

import config
from services.files import as_float, read_geojson, read_json_object
from services.models import DriftData


def load_drift() -> DriftData | None:
    """Return drift outputs grouped by forecast hour, or None if no drift files exist."""
    data = DriftData()

    collection, warning = read_geojson(config.DRIFT_FILES["drift"])
    if warning:
        data.warnings.append(warning)
    if collection is not None:
        missing_hours = 0
        for feature in collection["features"]:
            hours = as_float(feature["properties"].get("hours"))
            if hours is None or hours < 0:
                missing_hours += 1
                continue
            key = int(hours) if hours.is_integer() else hours
            data.steps.setdefault(key, []).append(feature)
        if missing_hours:
            data.warnings.append(
                f"`drift.geojson`: {missing_hours} features have no valid numeric `hours` property and were skipped."
            )
        if collection["features"] and not data.steps:
            data.warnings.append("`drift.geojson` has features, but none with a usable `hours` property.")

    data.meta, warning = read_json_object(config.DRIFT_FILES["meta"])
    if warning:
        data.warnings.append(warning)

    if not data.has_content and data.meta is None and not data.warnings:
        return None
    return data
