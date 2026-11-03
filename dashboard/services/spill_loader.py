"""Load the spill sites offered on the Overview map from ``outputs/spills.geojson`` (optional).

- ``spills.geojson``: one ``Point`` feature per incident. Properties: ``spill_id`` (required,
  unique, letters/digits/``_``/``-`` only), ``name`` (optional, defaults to the id),
  ``synthetic``. Not in shared/schemas.py; the position is validated as a ``GeoCoordinate``.

Without this file, one marker per site folder ``outputs/sites/<id>/`` (``load_site_spills``):
id = folder name, position = ``drift/meta.json`` ``initial_location`` (the release point the
site's forecast was made for). Without either, the simulated catalogue in ``mock_data``.
"""

from __future__ import annotations

import re
from typing import Any

import config
from services import schema
from services.files import read_geojson, read_json_object, validate_geojson
from services.models import SpillData, SpillSite

SPILL_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


def parse_spills(collection: dict | None, data: SpillData, name: str = "spills.geojson") -> None:
    """Validate Point features into SpillSite; only valid, uniquely named sites are offered."""
    if collection is None:
        return
    seen: set[str] = set()
    for i, feature in enumerate(collection["features"]):
        geometry, props = feature["geometry"], feature["properties"]
        synthetic = props.get("synthetic") is True
        data.synthetic |= synthetic
        if geometry["type"] != "Point":
            data.warnings.append(f"`{name}` feature {i}: {geometry['type']} is not a Point; skipped.")
            continue
        try:
            spill_id = schema.text(props.get("spill_id"), "spill_id")
            if not SPILL_ID_PATTERN.fullmatch(spill_id):
                raise schema.SchemaError(f"`spill_id` may only use letters, digits, _ and -, got {spill_id!r}")
            label = schema.text(props["name"], "name") if props.get("name") is not None else spill_id
            location = schema.geo(geometry["coordinates"])
        except schema.SchemaError as exc:
            data.warnings.append(f"`{name}` feature {i}: {exc}; skipped.")
            continue
        if spill_id in seen:
            data.warnings.append(f"`{name}` feature {i}: duplicate spill_id {spill_id!r}; skipped.")
            continue
        seen.add(spill_id)
        data.sites.append(SpillSite(spill_id, label, location, synthetic))


def build_spills(collection: Any) -> SpillData:
    """Validate an already-parsed spill catalogue (used for demo data)."""
    data = SpillData()
    valid, warning = validate_geojson(collection, "spills")
    data.warnings += [warning] if warning else []
    parse_spills(valid, data)
    return data


def site_ids() -> list[str]:
    """Site folders under outputs/sites/ whose names can be marker ids, sorted. [] without the folder."""
    if not config.SITES_DIR.is_dir():
        return []
    return sorted(p.name for p in config.SITES_DIR.iterdir() if p.is_dir() and SPILL_ID_PATTERN.fullmatch(p.name))


def load_site_spills() -> SpillData | None:
    """One marker per site folder, at its drift/meta.json initial_location; None without site folders.

    A folder whose meta.json is missing or has no valid initial_location gets no marker (warning).
    """
    ids = site_ids()
    if not ids:
        return None
    data = SpillData()
    for site_id in ids:
        meta, warning = read_json_object(config.site_files(site_id)["drift"]["meta"])
        if warning:
            data.warnings.append(warning)
            continue
        try:
            location = schema.geo_object((meta or {}).get("initial_location"), "initial_location")
        except schema.SchemaError as exc:
            data.warnings.append(f"Site `{site_id}`: drift/meta.json {exc}; no marker for this site.")
            continue
        synthetic = (meta or {}).get("synthetic") is True
        data.synthetic |= synthetic
        data.sites.append(SpillSite(site_id, f"Site {site_id}", location, synthetic))
    return data


def load_spills() -> SpillData | None:
    """Return the spill sites from outputs/spills.geojson, or None if the file does not exist."""
    data = SpillData()
    collection, warning = read_geojson(config.SPILLS_FILE)
    if warning:
        data.warnings.append(warning)
    parse_spills(collection, data)
    if not data.has_content and not data.warnings:
        return None
    return data
