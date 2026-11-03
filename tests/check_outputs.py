"""Check the result files each team writes under outputs/ before the dashboard reads them.

Usage, from the repository root:
    python tests/check_outputs.py                 # checks ./outputs
    python tests/check_outputs.py sample_outputs  # or any folder with the same layout
    python tests/check_outputs.py outputs --gulf  # also require points in the Gulf region
    python tests/check_outputs.py outputs --release 2026-10-23T12:00:00Z  # agreed release time (D3)

The folder layout and file fields are the ones in dashboard/README.md ("Data contract"):
    <outputs>/detection/  metrics.json, mask.png or <image_id>_mask.png, spill.geojson (optional)
    <outputs>/drift/      drift.geojson, meta.json (optional)
    <outputs>/routing/    routes.geojson, summary.json, targets.geojson (optional)

Each file is turned into the shared dataclasses and checked with tests/contract_checks.py.
Links between teams are also checked: route targets exist, targets come from a forecast
hour that the drift output contains, and drift timestamps match release time + hours.

Findings have two levels:
    problem  breaks the shared contract, or the dashboard would show nothing or a wrong value
    note     works, but worth knowing before the demo (missing optional file, extension, ...)
--release turns a drift run that starts at another time into a problem. Without it, the
release time and point found in meta.json are only reported as a note.

--gulf applies the optional regional check from contract_checks. GeoJSON stores
[longitude, latitude], so a swapped pair is still a valid point somewhere on Earth; only
the regional check catches it.

Exit code 1 if there is at least one problem. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _path in (REPO_ROOT, REPO_ROOT / "tests"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from contract_checks import (  # noqa: E402
    GULF_REGION,
    VALID_STATUSES,
    Region,
    check_coordinate,
    check_in_region,
    check_detection,
    check_drift,
    check_optimization,
    check_vessel,
)
from shared.schemas import (  # noqa: E402
    DetectionOutput,
    DriftOutput,
    GeoCoordinate,
    OptimizationOutput,
    ResponseTarget,
    TimedPosition,
    Vessel,
    VesselRoute,
)

METRIC_KEYS = ("dice", "iou", "precision", "recall")
DRIFT_HORIZONS = (0, 6, 12, 24)
VESSEL_KEYS = ("speed_m_per_s", "capacity_m3", "available_hours")
HOURS_TOLERANCE = 0.05


@dataclass(frozen=True)
class Finding:
    section: str  # "detection", "drift" or "routing"
    level: str  # "problem" or "note"
    text: str


class _Collector:
    def __init__(self, section: str, region: Region | None = None):
        self.section = section
        self.region = region
        self.findings: list[Finding] = []

    def problem(self, text: str) -> None:
        self.findings.append(Finding(self.section, "problem", text))

    def note(self, text: str) -> None:
        self.findings.append(Finding(self.section, "note", text))


# --- Small readers --------------------------------------------------------------------


def _read_json(path: Path, out: _Collector):
    """Parsed JSON, or None (with a problem) if the file is broken."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        out.problem(f"{path.name}: cannot be read as JSON ({exc})")
        return None


def _read_features(path: Path, out: _Collector) -> list[dict] | None:
    data = _read_json(path, out)
    if data is None:
        return None
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        out.problem(f"{path.name}: must be a GeoJSON FeatureCollection with a 'features' list")
        return None
    features = [f for f in data["features"] if isinstance(f, dict)]
    if len(features) != len(data["features"]):
        out.problem(f"{path.name}: every feature must be an object")
    for i, f in enumerate(features):
        f.setdefault("properties", {})
        if not isinstance(f["properties"], dict):
            f["properties"] = {}
        geometry = f.get("geometry")
        if geometry is not None and not isinstance(geometry, dict):
            out.problem(f"{path.name} feature {i}: geometry must be a GeoJSON object, "
                        f"got {type(geometry).__name__}; feature skipped")
            f["_skip"] = True
    return features


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _utc(value) -> datetime | None:
    """ISO 8601 string with a timezone -> UTC datetime; None if it is not one."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None


def _position(value) -> GeoCoordinate | None:
    """GeoJSON position [longitude, latitude] -> GeoCoordinate(latitude, longitude)."""
    if isinstance(value, (list, tuple)) and len(value) >= 2 and _is_number(value[0]) and _is_number(value[1]):
        return GeoCoordinate(latitude=float(value[1]), longitude=float(value[0]))
    return None


def _positions(geometry: dict) -> list:
    """All raw positions of a Point / MultiPoint / LineString / Polygon / MultiPolygon."""
    kind, coords = geometry.get("type"), geometry.get("coordinates")
    try:
        if kind == "Point":
            return [coords]
        if kind in ("MultiPoint", "LineString"):
            return list(coords or [])
        if kind == "Polygon":
            return [p for ring in coords or [] for p in ring]
        if kind == "MultiPolygon":
            return [p for poly in coords or [] for ring in poly for p in ring]
    except TypeError:
        return [None]  # malformed nesting: reported as an invalid position
    return []


def _check_positions(geometry: dict, where: str, out: _Collector) -> None:
    for i, raw in enumerate(_positions(geometry)):
        coord = _position(raw)
        if coord is None:
            out.problem(f"{where}: position {i} must be [longitude, latitude] numbers, got {raw!r}")
            return
        name = f"{where} position {i}"
        problems = check_in_region(coord, out.region, name) if out.region else check_coordinate(coord, name)
        if problems:
            out.problem(problems[0] + " (GeoJSON order is [longitude, latitude])")
            return


def _synthetic(*objects) -> bool:
    return any(isinstance(o, dict) and o.get("synthetic") is True for o in objects)


# --- Detection ------------------------------------------------------------------------


def check_detection_dir(folder: Path, region: Region | None = None) -> list[Finding]:
    out = _Collector("detection", region)
    if not folder.is_dir():
        out.note("no detection folder: the Detect page will show its empty state")
        return out.findings

    metrics_file = folder / "metrics.json"
    raw = _read_json(metrics_file, out) if metrics_file.exists() else None
    if not metrics_file.exists():
        out.problem("metrics.json is missing (required by the dashboard)")
    elif isinstance(raw, dict):
        top = [k for k in METRIC_KEYS if k in raw]
        if not top:
            nested = next((k for k in ("metrics", "micro") if isinstance(raw.get(k), dict)
                           and any(m in raw[k] for m in METRIC_KEYS)), None)
            if nested:
                out.problem(f"metrics.json: scores are nested under '{nested}'; the dashboard reads "
                            f"{', '.join(METRIC_KEYS)} only at the top level, so it shows no scores")
            else:
                out.problem(f"metrics.json: none of {', '.join(METRIC_KEYS)} found")
        for key in top:
            if not (_is_number(raw[key]) and 0 <= raw[key] <= 1):
                out.problem(f"metrics.json: {key} must be a number in [0, 1], got {raw[key]!r}")
        missing = [k for k in METRIC_KEYS if k not in raw]
        if top and missing:
            out.note(f"metrics.json: no {', '.join(missing)}; those tiles stay empty")
        if top and "split" not in raw:
            out.note("metrics.json: add 'split' (e.g. \"val\") so viewers know which data the scores come from")
    elif raw is not None:
        out.problem("metrics.json: must be a JSON object")

    masks = sorted(p for p in folder.glob("*.png") if p.stem == "mask" or p.stem.endswith("_mask"))
    if not masks:
        out.problem("no predicted mask: write mask.png or <image_id>_mask.png")
    for mask in masks:
        scene = mask.stem[: -len("mask")]  # "" for mask.png, "<id>_" otherwise
        if not (folder / f"{scene}image.png").exists() and not (folder / f"{scene}overlay.png").exists():
            out.note(f"{mask.name}: no {scene}image.png or {scene}overlay.png next to it, "
                     "so the page shows the mask without the radar scene")

    spill_file = folder / "spill.geojson"
    if not spill_file.exists():
        out.note("no spill.geojson: there is no georeferenced oil location, so drift must start "
                 "from a release point labelled synthetic")
    else:
        features = _read_features(spill_file, out) or []
        for i, f in enumerate(features):
            if f.get("_skip"):
                continue
            geometry, props = f.get("geometry") or {}, f["properties"]
            where = f"spill.geojson feature {i}"
            if geometry.get("type") not in ("Polygon", "MultiPolygon"):
                out.problem(f"{where}: geometry must be Polygon or MultiPolygon, got {geometry.get('type')}")
                continue
            _check_positions(geometry, where, out)
            coords = tuple(c for c in (_position(p) for p in _positions(geometry)) if c is not None)
            image_id = props.get("image_id")
            detection = DetectionOutput(image_id=image_id if isinstance(image_id, str) else "",
                                        mask_path=Path(f"{image_id}_mask.png"),
                                        oil_coordinates=coords or None, confidence=props.get("confidence"))
            for p in check_detection(detection):
                if not p.startswith("detection.oil_coordinates"):  # positions were checked above
                    out.problem(f"{where}: {p}")

    if _synthetic(raw):
        out.note("labelled synthetic: the page will show 'Simulated scenario'")
    return out.findings


# --- Drift ----------------------------------------------------------------------------


def check_drift_dir(folder: Path, region: Region | None = None,
                    expected_release: datetime | None = None) -> tuple[list[Finding], set[float]]:
    """Findings and the forecast hours present in drift.geojson."""
    out = _Collector("drift", region)
    hours_found: set[float] = set()
    if not folder.is_dir():
        out.note("no drift folder: the Predict page will show its empty state")
        return out.findings, hours_found

    drift_file, meta_file = folder / "drift.geojson", folder / "meta.json"
    features: list[dict] = []
    if not drift_file.exists():
        out.problem("drift.geojson is missing (required by the dashboard)")
    else:
        features = _read_features(drift_file, out) or []
        if drift_file.exists() and not features:
            out.problem("drift.geojson has no features")

    counts: dict[float, int] = {}
    for i, f in enumerate(features):
        if f.get("_skip"):
            continue
        geometry, props = f.get("geometry") or {}, f["properties"]
        where = f"drift.geojson feature {i}"
        hours = props.get("hours")
        if not (_is_number(hours) and hours >= 0):
            out.problem(f"{where}: 'hours' (hours since release) must be a nonnegative number, got {hours!r}")
            continue
        if "timestamp" in props and _utc(props["timestamp"]) is None:
            out.problem(f"{where}: timestamp must be ISO 8601 with a timezone (UTC), got {props['timestamp']!r}")
        if geometry.get("type") not in ("Point", "MultiPoint", "Polygon", "MultiPolygon"):
            out.problem(f"{where}: geometry must be Point/MultiPoint (particles) or Polygon/MultiPolygon "
                        f"(envelope), got {geometry.get('type')}")
            continue
        _check_positions(geometry, where, out)
        hours_found.add(float(hours))
        if geometry["type"] in ("Point", "MultiPoint"):
            counts[float(hours)] = counts.get(float(hours), 0) + len(_positions(geometry))

    if hours_found:
        missing = [h for h in DRIFT_HORIZONS if float(h) not in hours_found]
        if missing:
            out.note(f"drift.geojson: no features for hour(s) {missing}; agreed horizons are {list(DRIFT_HORIZONS)}")
        if counts and len(set(counts.values())) == 1:
            n, hours = next(iter(counts.values())), sorted(counts)
            out.note(f"particles: {n} at each of {len(hours)} steps ({hours[0]:g} to {hours[-1]:g} h)")
        elif counts:
            summary = ", ".join(f"{h:g} h: {n}" for h, n in sorted(counts.items()))
            out.note(f"particles per step: {summary}")
        else:
            out.note("drift.geojson has no particle points; targets cannot be built from a particle distribution")

    meta = _read_json(meta_file, out) if meta_file.exists() else None
    release: datetime | None = None
    if meta_file.exists() and not isinstance(meta, dict):
        if meta is not None:
            out.problem("meta.json: must be a JSON object")
        meta = None
    if isinstance(meta, dict):
        release = _check_meta(meta, out)
        init = meta.get("initial_location")
        where = (f" at {init.get('latitude')}, {init.get('longitude')}" if isinstance(init, dict) else "")
        if release is not None:
            out.note(f"release: {release.strftime('%Y-%m-%dT%H:%M:%SZ')}{where}")
    if expected_release is not None and features:
        if release is None:
            out.problem("cannot check the release time: meta.json has no start_time or positions")
        elif abs((release - expected_release).total_seconds()) > HOURS_TOLERANCE * 3600:
            out.problem(f"release time is {release.strftime('%Y-%m-%dT%H:%M:%SZ')}, not the agreed "
                        f"{expected_release.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    if release is not None:
        for i, f in enumerate(features):
            stamp, hours = _utc(f["properties"].get("timestamp")), f["properties"].get("hours")
            if stamp and _is_number(hours):
                gap = (stamp - release).total_seconds() / 3600
                if abs(gap - hours) > HOURS_TOLERANCE:
                    out.problem(f"drift.geojson feature {i}: hours={hours} but timestamp is {gap:.2f} h "
                                "after the release time")
                    break

    if _synthetic(meta, *(f["properties"] for f in features)):
        out.note("labelled synthetic: the page will show 'Simulated scenario'")
    elif features:
        out.note("not labelled synthetic: add \"synthetic\": true to meta.json while the release point "
                 "is not a georeferenced detection")
    return out.findings, hours_found


def _check_meta(meta: dict, out: _Collector) -> datetime | None:
    """Validate the DriftOutput in meta.json; return the release time if known."""
    release = None
    if "start_time" in meta:
        release = _utc(meta["start_time"])
        if release is None:
            out.problem(f"meta.json: start_time must be ISO 8601 with a timezone (UTC), got {meta['start_time']!r}")
    if not any(k in meta for k in ("simulation_id", "initial_location", "positions", "duration_hours")):
        if release is None:
            out.note("meta.json has neither a DriftOutput nor start_time, so timestamps cannot be cross-checked")
        return release
    raw_positions = meta.get("positions")
    if not isinstance(raw_positions, list):
        out.problem("meta.json: 'positions' must be a list of {timestamp, coordinate}")
        return release
    positions = []
    for i, p in enumerate(raw_positions):
        coord = p.get("coordinate") if isinstance(p, dict) else None
        if not isinstance(coord, dict):
            out.problem(f"meta.json: positions[{i}] needs a 'coordinate' object with latitude and longitude")
            return release
        stamp = p.get("timestamp")
        positions.append(TimedPosition(timestamp=_utc(stamp) or stamp,
                                       coordinate=GeoCoordinate(coord.get("latitude"), coord.get("longitude"))))
    init = meta.get("initial_location")
    initial = (GeoCoordinate(init.get("latitude"), init.get("longitude")) if isinstance(init, dict)
               else GeoCoordinate(float("nan"), float("nan")))
    drift = DriftOutput(simulation_id=str(meta.get("simulation_id", "")), initial_location=initial,
                        positions=tuple(positions), duration_hours=meta.get("duration_hours"))
    if not meta.get("simulation_id"):
        out.problem("meta.json: simulation_id is required with the DriftOutput fields")
    for p in check_drift(drift):
        out.problem(f"meta.json: {p}")
    if positions and isinstance(positions[0].timestamp, datetime):
        first = positions[0].timestamp
        if release is not None and abs((first - release).total_seconds()) > HOURS_TOLERANCE * 3600:
            out.problem("meta.json: start_time differs from the first position's timestamp")
        release = release or first
    return release


# --- Routing --------------------------------------------------------------------------


def check_routing_dir(folder: Path, drift_hours: set[float] | None = None,
                      region: Region | None = None) -> list[Finding]:
    out = _Collector("routing", region)
    if not folder.is_dir():
        out.note("no routing folder: the Respond page will show its empty state")
        return out.findings

    summary_file = folder / "summary.json"
    summary = _read_json(summary_file, out) if summary_file.exists() else None
    status = summary.get("status") if isinstance(summary, dict) else None
    valid_status = isinstance(status, str) and status in VALID_STATUSES
    if not summary_file.exists():
        out.problem("summary.json is missing (required by the dashboard)")
    elif isinstance(summary, dict) and not valid_status:
        out.problem(f"summary.json: status must be one of {', '.join(sorted(VALID_STATUSES))}, got {status!r}")

    routes, vessels, missing_vessel_info = [], [], False
    route_props: list[dict] = []
    returns_to_start = False
    routes_file = folder / "routes.geojson"
    if routes_file.exists():
        for i, f in enumerate(_read_features(routes_file, out) or []):
            if f.get("_skip"):
                continue
            geometry, props = f.get("geometry") or {}, f["properties"]
            where = f"routes.geojson feature {i}"
            if geometry.get("type") != "LineString":
                out.problem(f"{where}: geometry must be a LineString, got {geometry.get('type')}")
                continue
            _check_positions(geometry, where, out)
            coords = tuple(c for c in (_position(p) for p in _positions(geometry)) if c is not None)
            ids = props.get("assigned_target_ids")
            if not isinstance(ids, list) or not all(isinstance(t, str) and t for t in ids):
                out.problem(f"{where}: assigned_target_ids must be a list of target ID strings")
                ids = []
            vessel_id = props.get("vessel_id")
            if not isinstance(vessel_id, str) or not vessel_id:
                out.problem(f"{where}: vessel_id must be a non-empty string")
                continue
            routes.append(VesselRoute(vessel_id, tuple(ids), coords,
                                      props.get("estimated_distance_km"), props.get("estimated_travel_hours")))
            route_props.append(props)
            returns_to_start |= len(coords) > 1 and coords[0] == coords[-1]
            given = [k for k in VESSEL_KEYS if k in props]
            if len(given) == len(VESSEL_KEYS) and coords:
                vessels.append(Vessel(vessel_id, coords[0], *(props[k] for k in VESSEL_KEYS)))
            elif given:
                out.problem(f"{where}: give all of {', '.join(VESSEL_KEYS)} or none (the dashboard needs all three)")
            else:
                missing_vessel_info = True
    elif status in ("optimal", "feasible"):
        out.note(f"status is {status!r} but there is no routes.geojson, so no routes are drawn")

    targets: list[ResponseTarget] = []
    source_hours: set[float] = set()
    targets_file = folder / "targets.geojson"
    if targets_file.exists():
        for i, f in enumerate(_read_features(targets_file, out) or []):
            if f.get("_skip"):
                continue
            geometry, props = f.get("geometry") or {}, f["properties"]
            where = f"targets.geojson feature {i}"
            if geometry.get("type") != "Point":
                out.problem(f"{where}: geometry must be a Point, got {geometry.get('type')}")
                continue
            _check_positions(geometry, where, out)
            coord = _position(geometry.get("coordinates"))
            target_id, volume = props.get("target_id"), props.get("oil_volume_m3")
            if not isinstance(target_id, str) or not target_id:
                out.problem(f"{where}: target_id must be a non-empty string")
                continue
            if not (_is_number(volume) and volume >= 0):
                out.problem(f"{where}: oil_volume_m3 must be a nonnegative number, got {volume!r}")
                continue
            if coord is not None:
                targets.append(ResponseTarget(target_id, coord, float(volume)))
            if _is_number(props.get("source_hours")):
                source_hours.add(float(props["source_hours"]))
        ids = [t.target_id for t in targets]
        if len(ids) != len(set(ids)):
            out.problem("targets.geojson: target_id values must be unique")
    elif routes:
        out.note("no targets.geojson: route target IDs cannot be checked and the oil-to-collect tile stays empty")

    invalid_vessels = set()
    for v in vessels:
        for p in check_vessel(v):
            if "location" not in p:  # route positions were checked above
                out.problem(f"routes.geojson: {p}")
                invalid_vessels.add(v.vessel_id)
    vessels = [v for v in vessels if v.vessel_id not in invalid_vessels]

    if valid_status:
        plan = OptimizationOutput(routes=tuple(routes), status=status,
                                  message=summary.get("message") if isinstance(summary, dict) else None)
        skip = []
        if missing_vessel_info:
            skip.append("unknown vessel")
            out.note("some routes have no vessel fields, so capacity and hours checks were skipped for them")
        if not targets_file.exists():
            skip.append("unknown target")
        skip += [f"unknown vessel {v}" for v in invalid_vessels]  # already reported above
        for p in check_optimization(plan, vessels, targets):
            if not any(s in p for s in skip):
                out.problem(p)

    if drift_hours:
        if not source_hours and targets:
            out.note("targets.geojson has no 'source_hours', so the page assumes the 12 h drift layer; "
                     "write the forecast hour the targets were taken from")
        for h in sorted(source_hours - drift_hours):
            out.problem(f"targets come from forecast hour {h:g}, which drift.geojson does not contain")
    if len(source_hours) > 1:
        out.problem(f"targets come from several forecast hours {sorted(source_hours)}; they must be separate "
                    "oil patches at one forecast time")

    travel = [r.estimated_travel_hours for r in routes if _is_number(r.estimated_travel_hours)]
    finish = [p["finish_hours"] for p in route_props if _is_number(p.get("finish_hours"))]
    if travel and finish and max(finish) > max(travel) + 0.01:
        back = ", including the trip back to port" if returns_to_start else ""
        out.note(f"response time (D2): largest 'finish_hours' is {max(finish):.2f} h (sailing + cleanup{back}); "
                 f"longest sailing time is {max(travel):.2f} h. Show both with clear labels")
    unserved = summary.get("unserved_target_ids") if isinstance(summary, dict) else None
    if isinstance(unserved, list) and unserved:
        out.note(f"{len(unserved)} target(s) not served ({', '.join(map(str, unserved))}); "
                 "the dashboard does not show this list yet")

    if _synthetic(summary):
        out.note("labelled synthetic: the page will show 'Simulated scenario'")
    return out.findings


# --- All sections ---------------------------------------------------------------------


def check_outputs(root: Path, region: Region | None = None,
                  expected_release: datetime | None = None) -> list[Finding]:
    root = Path(root)
    findings = check_detection_dir(root / "detection", region)
    drift_findings, drift_hours = check_drift_dir(root / "drift", region, expected_release)
    findings += drift_findings
    findings += check_routing_dir(root / "routing", drift_hours, region)
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the result files under an outputs folder.")
    parser.add_argument("folder", nargs="?", default=str(REPO_ROOT / "outputs"))
    parser.add_argument("--gulf", action="store_true", help="also require points in the Gulf region")
    parser.add_argument("--release", help="agreed drift release time, ISO 8601 UTC, e.g. 2026-10-23T12:00:00Z")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    region = GULF_REGION if args.gulf else None
    expected = _utc(args.release) if args.release else None
    if args.release and expected is None:
        print(f"--release must be ISO 8601 with a timezone, e.g. 2026-10-23T12:00:00Z, got {args.release!r}")
        return 2
    root = Path(args.folder)
    if not root.is_dir():
        print(f"Folder not found: {root}")
        return 1
    findings = check_outputs(root, region, expected)
    extras = [f"region: {region.name}"] if region else []
    extras += [f"agreed release: {args.release}"] if expected else []
    print(f"Checking {root}" + (f" ({'; '.join(extras)})" if extras else "") + "\n")
    for section in ("detection", "drift", "routing"):
        items = [f for f in findings if f.section == section]
        problems = [f for f in items if f.level == "problem"]
        print(f"{section.upper()}: {'OK' if not problems else f'{len(problems)} problem(s)'}")
        for f in items:
            print(f"  [{f.level}] {f.text}")
        print()
    total = sum(f.level == "problem" for f in findings)
    print("All files follow the contract." if not total else f"{total} problem(s) found.")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
