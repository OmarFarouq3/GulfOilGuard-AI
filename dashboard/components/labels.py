"""Display units and wording derived from shared/schemas.py.

Units come from the schema's field-name suffixes (via services.schema.unit), and the
status wording covers exactly the OptimizationOutput.status values; check_schema.py
fails if the schema gains a status that has no wording here.
"""

from __future__ import annotations

from services.schema import SOLVER_STATUSES, ResponseTarget, Vessel, VesselRoute, suffix_unit, unit

KM = unit(VesselRoute, "estimated_distance_km")
HOURS = unit(VesselRoute, "estimated_travel_hours")
M3 = unit(ResponseTarget, "oil_volume_m3")
M_PER_S = unit(Vessel, "speed_m_per_s")
KM2 = "km²"  # area: the schema has no area field or unit (polygon areas are a dashboard extension)
assert suffix_unit("wind_speed_m_per_s") == M_PER_S

# OptimizationOutput.status -> (chip style, viewer wording)
STATUS_LABELS: dict[str, tuple[str, str]] = {
    "optimal": ("gog-chip-live", "Optimal plan"),
    "feasible": ("gog-chip-live", "Feasible plan"),
    "infeasible": ("gog-chip-empty", "No feasible plan"),
    "not_solved": ("gog-chip-empty", "Plan not computed"),
    "error": ("gog-chip-empty", "Plan unavailable"),
}
assert set(STATUS_LABELS) == set(SOLVER_STATUSES), "status wording out of sync with shared/schemas.py"
