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

# 2. Dashboard data stack ---------------------------------------------------------------
print("2. importing the dashboard data stack")
from components import labels  # noqa: E402
from services import mock_data, schema  # noqa: E402
from services.detection_loader import load_detection  # noqa: E402
from services.drift_loader import load_drift  # noqa: E402
from services.routing_loader import load_routing  # noqa: E402

check(not forbidden_loaded(), f"no forbidden modules loaded: {forbidden_loaded()}")


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

# 4. Sample files -----------------------------------------------------------------------
print(f"4. sample files written to {SAMPLE_DIR}")
written = mock_data.write_sample_outputs(SAMPLE_DIR)
check(len(written) == 10, f"wrote {len(written)} files")
assert_conforms("sample", load_detection(), load_drift(), load_routing())

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
routing, drift, detection = load_routing(), load_drift(), load_detection()
for needle, warnings in (("status", routing.warnings), ("assigned_target_ids", routing.warnings),
                         ("oil_volume_m3", routing.warnings), ("timezone-aware", drift.warnings),
                         ("confidence", detection.warnings)):
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
