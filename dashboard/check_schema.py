"""Check that the dashboard's data handling conforms to shared/schemas.py.

Usage (from the repository root):
    python dashboard/check_schema.py

Exits non-zero on any mismatch. Checks:
1. importing shared.schemas (clean interpreter) loads no torch / opendrift / ortools
2. the dashboard data stack loads none of them either
3. the demo scenario validates with zero warnings into the shared dataclasses
4. sample files written to disk validate through the real file loaders
5. deliberately non-conforming files are rejected (validation is not a no-op)
6. display units and solver-status wording cover the schema
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parent
REPO_ROOT = DASHBOARD_DIR.parent
FORBIDDEN = ("torch", "opendrift", "ortools")

# Point the loaders at a temporary data folder before config is imported.
SAMPLE_DIR = Path(tempfile.mkdtemp(prefix="gog_schema_check_"))
os.environ["GULFOILGUARD_OUTPUTS"] = str(SAMPLE_DIR)
sys.path.insert(0, str(DASHBOARD_DIR))
logging.getLogger("streamlit").setLevel(logging.ERROR)  # quiet "no runtime" cache notices

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    print(("  ok    " if condition else "  FAIL  ") + message)
    if not condition:
        failures.append(message)


def forbidden_loaded() -> list[str]:
    return sorted({m.split(".")[0] for m in sys.modules} & set(FORBIDDEN))


# 1. Clean-interpreter import guard -----------------------------------------------------
print("1. importing shared.schemas in a clean interpreter")
probe = (
    "import sys; sys.path.append(sys.argv[1]); import shared.schemas; "
    f"print(sorted({{m.split('.')[0] for m in sys.modules}} & {set(FORBIDDEN)!r}))"
)
result = subprocess.run([sys.executable, "-I", "-c", probe, str(REPO_ROOT)], capture_output=True, text=True)
check(result.returncode == 0, f"import succeeds ({result.stderr.strip() or 'no errors'})")
check(result.stdout.strip() == "[]", f"no forbidden modules loaded: {result.stdout.strip()}")

print("1b. importing services.inference in a clean interpreter (the U-Net runs in a subprocess)")
probe = (
    "import sys; sys.path.insert(0, sys.argv[1]); import services.inference; "
    f"print(sorted({{m.split('.')[0] for m in sys.modules}} & {set(FORBIDDEN) | {'detection'}!r}))"
)
result = subprocess.run([sys.executable, "-I", "-c", probe, str(DASHBOARD_DIR)], capture_output=True, text=True)
check(result.returncode == 0, f"import succeeds ({result.stderr.strip()[-200:] or 'no errors'})")
check(result.stdout.strip() == "[]", f"no torch / opendrift / ortools / detection loaded: {result.stdout.strip()}")

# 2. Dashboard data stack ---------------------------------------------------------------
print("2. importing the dashboard data stack")
from components import labels  # noqa: E402
from services import mock_data, schema  # noqa: E402
from services.detection_loader import load_detection  # noqa: E402
from services.drift_loader import load_drift  # noqa: E402
from services.routing_loader import load_routing  # noqa: E402
from services.spill_loader import load_spills  # noqa: E402
from services import geo as geo_mod  # noqa: E402
from services import image_picker, inference, scenario, selection  # noqa: E402, F401  (import guard)

check(not forbidden_loaded(), f"no forbidden modules loaded: {forbidden_loaded()}")


def assert_spills(label: str, spills) -> None:
    """The spill catalogue validates with zero warnings into unique, simulated SpillSites."""
    check(spills is not None and spills.has_content, f"{label} spills: has content")
    if spills is not None:
        check(not spills.warnings, f"{label} spills: no validation warnings {spills.warnings or ''}")
        ids = [s.spill_id for s in spills.sites]
        check(len(ids) == len(set(ids)), f"{label} spills: spill IDs unique")
        check(all(isinstance(s.location, schema.GeoCoordinate) for s in spills.sites),
              f"{label} spills: positions are GeoCoordinate")
        check(all(s.synthetic for s in spills.sites), f"{label} spills: every site is labelled synthetic")


def assert_conforms(label: str, detection, drift, routing) -> None:
    """Zero warnings, and every structure is a shared dataclass with valid values."""
    for name, data in (("detection", detection), ("drift", drift), ("routing", routing)):
        check(data is not None and data.has_content, f"{label} {name}: has content")
        if data is not None:
            check(not data.warnings, f"{label} {name}: no validation warnings {data.warnings or ''}")
    if detection:
        check(bool(detection.detections) and all(isinstance(d, schema.DetectionOutput) for d in detection.detections),
              f"{label}: slicks are DetectionOutput")
        check(all(d.confidence is None or 0 <= d.confidence <= 1 for d in detection.detections),
              f"{label}: confidence in [0, 1]")
    if drift:
        check(isinstance(drift.trajectory, schema.DriftOutput), f"{label}: drift trajectory is DriftOutput")
        if drift.trajectory:
            stamps = [p.timestamp for p in drift.trajectory.positions]
            check(all(t.utcoffset().total_seconds() == 0 for t in stamps), f"{label}: positions are UTC")
            check(stamps == sorted(stamps), f"{label}: positions ordered by timestamp")
    if routing:
        output = routing.output
        check(isinstance(output, schema.OptimizationOutput), f"{label}: plan is OptimizationOutput")
        check(output is not None and output.status in schema.SOLVER_STATUSES, f"{label}: status in schema enum")
        check(all(isinstance(r.route, schema.VesselRoute) for r in routing.routes), f"{label}: routes are VesselRoute")
        check(all(isinstance(r.vessel, schema.Vessel) and r.vessel.speed_m_per_s > 0 for r in routing.routes),
              f"{label}: every route has a Vessel with positive speed")
        check(all(r.oil_collected_m3 is None or r.oil_collected_m3 <= r.vessel.capacity_m3 for r in routing.routes),
              f"{label}: oil collected within capacity_m3")
        check(all(r.route.estimated_travel_hours <= r.vessel.available_hours for r in routing.routes),
              f"{label}: travel time within available_hours")
        check(all(isinstance(t, schema.ResponseTarget) for t in routing.targets), f"{label}: targets are ResponseTarget")
        ids = [r.route.vessel_id for r in routing.routes] + [t.target_id for t in routing.targets]
        check(len(ids) == len(set(ids)), f"{label}: vessel and target IDs unique")


# 3. Demo scenario ----------------------------------------------------------------------
print("3. demo scenario (in memory)")
assert_conforms("demo", mock_data.detection(), mock_data.drift(), mock_data.routing())
assert_spills("demo", mock_data.spills())

print("3b. demo scenario positioned at a selected spill")
site = mock_data.spills().sites[-1]
moved_drift, moved_routing = scenario.selected_drift(site, True), scenario.selected_routing(site, True)
origin = moved_drift.trajectory.initial_location
check(abs(origin.latitude - site.location.latitude) < 1e-6 and abs(origin.longitude - site.location.longitude) < 1e-6,
      "drift release point sits on the selected spill")
outline = scenario.selected_detection(site, None, simulated_accepted=True)
assert_conforms("anchored", outline, moved_drift, moved_routing)
source_routing = mock_data.routing()
check(all(abs(geo_mod.path_length_km([[c.longitude, c.latitude] for c in a.route.coordinates])
              - geo_mod.path_length_km([[c.longitude, c.latitude] for c in b.route.coordinates])) < 0.05 * max(
              1.0, b.route.estimated_distance_km or 1.0) for a, b in zip(moved_routing.routes, source_routing.routes)),
      "moved routes keep their length (within 5 %)")
check(moved_drift.synthetic and moved_routing.synthetic, "anchored drift and routing are labelled synthetic")
check(outline is not None and outline.outline_simulated and outline.synthetic, "simulated outline is labelled synthetic")
check(outline is not None and all(d.confidence is None for d in outline.detections), "simulated outline has no confidence")

# 4. Sample files -----------------------------------------------------------------------
print(f"4. sample files written to {SAMPLE_DIR}")
written = mock_data.write_sample_outputs(SAMPLE_DIR)
check(len(written) == 11, f"wrote {len(written)} files")
assert_conforms("sample", load_detection(), load_drift(), load_routing())
assert_spills("sample", load_spills())

# 5. Non-conforming files are rejected ---------------------------------------------------
print("5. non-conforming files are rejected")


def rewrite(relative: str, change) -> None:
    path = SAMPLE_DIR / relative
    content = json.loads(path.read_text(encoding="utf-8"))
    change(content)
    path.write_text(json.dumps(content), encoding="utf-8")


rewrite("routing/summary.json", lambda c: c.update(status="done"))
rewrite("routing/routes.geojson", lambda c: c["features"][0]["properties"].pop("assigned_target_ids"))
rewrite("routing/targets.geojson", lambda c: c["features"][0]["properties"].update(oil_volume_m3=-5))
rewrite("drift/meta.json", lambda c: c["positions"][0].update(timestamp="2026-03-14T06:42:00"))
rewrite("detection/spill.geojson", lambda c: c["features"][0]["properties"].update(confidence=1.7))
rewrite("spills.geojson", lambda c: c["features"][1]["properties"].update(spill_id="GOG-SIM-01"))
routing, drift, detection, spills = load_routing(), load_drift(), load_detection(), load_spills()
for needle, warnings in (("status", routing.warnings), ("assigned_target_ids", routing.warnings),
                         ("oil_volume_m3", routing.warnings), ("timezone-aware", drift.warnings),
                         ("confidence", detection.warnings), ("duplicate spill_id", spills.warnings)):
    check(any(needle in w for w in warnings), f"rejects bad `{needle}`")
check(routing.status is None and routing.output is None, "invalid status is not shown as a plan")

# 6. Labels -------------------------------------------------------------------------------
print("6. display units and status wording")
check(set(labels.STATUS_LABELS) == set(schema.SOLVER_STATUSES), f"wording for every status {schema.SOLVER_STATUSES}")
unit_fields = [(cls.__name__, f.name) for cls in (schema.Vessel, schema.ResponseTarget, schema.VesselRoute,
                                                   schema.DriftOutput) for f in dataclasses.fields(cls)
               if f.name.endswith(tuple(s for s, _ in schema.UNIT_SUFFIXES))]
check(all(schema.unit(getattr(schema, c), f) for c, f in unit_fields), f"unit for every suffixed field: {unit_fields}")
check(not forbidden_loaded(), "still no forbidden modules after all checks")

print()
print("FAILED: " + "; ".join(failures) if failures else "All schema checks passed.")
sys.exit(1 if failures else 0)
