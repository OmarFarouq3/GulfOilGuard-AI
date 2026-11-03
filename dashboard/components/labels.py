"""Display units and wording derived from shared/schemas.py.

Units come from the schema's field-name suffixes (via services.schema.unit), and the
status wording covers exactly the OptimizationOutput.status values; check_schema.py
fails if the schema gains a status that has no wording here.
"""

from __future__ import annotations

from typing import get_args

from components.data import Status
from services.schema import SOLVER_STATUSES, ResponseTarget, Vessel, VesselRoute, suffix_unit, unit

KM = unit(VesselRoute, "estimated_distance_km")
HOURS = unit(VesselRoute, "estimated_travel_hours")
M3 = unit(ResponseTarget, "oil_volume_m3")
M_PER_S = unit(Vessel, "speed_m_per_s")
KM2 = "km²"  # area: the schema has no area field or unit (polygon areas are a dashboard extension)
assert suffix_unit("wind_speed_m_per_s") == M_PER_S

# Stage status (components.data.Status) -> (chip style, chip wording, timeline tooltip)
STAGE_STATUS: dict[str, tuple[str, str, str]] = {
    "live": ("gog-chip-live", "Live data", "Live data available"),
    "simulated": ("gog-chip-sim", "Simulated scenario", "Showing a simulated scenario"),
    "mixed": ("gog-chip-mixed", "Real detection, simulated location",
              "Real model output on a radar image; the incident location is simulated"),
    "forecast": ("gog-chip-forecast", "Real forecast, simulated release",
                 "Real OpenDrift forecast on real wind and current data; the release point is simulated"),
    "empty": ("gog-chip-empty", "No data yet", "No data yet"),
}
assert set(STAGE_STATUS) == set(get_args(Status)), "stage status wording out of sync with components.data.Status"


def slick_tooltip(outline_simulated: bool) -> dict[str, str]:
    """Map tooltip fields for detected slicks. A simulated outline shows its ``outline`` property
    (services.scenario.SIMULATED_OUTLINE) and never names a scene, so it can't read as if it
    was traced from that image."""
    if outline_simulated:
        return {"outline": "Outline", "area_km2": f"Simulated area ({KM2})"}
    return {"image_id": "Scene", "area_km2": f"Area ({KM2})", "confidence": "Confidence"}


# OptimizationOutput.status -> (chip style, viewer wording)
STATUS_LABELS: dict[str, tuple[str, str]] = {
    "optimal": ("gog-chip-live", "Optimal plan"),
    "feasible": ("gog-chip-live", "Feasible plan"),
    "infeasible": ("gog-chip-empty", "No feasible plan"),
    "not_solved": ("gog-chip-empty", "Plan not computed"),
    "error": ("gog-chip-empty", "Plan unavailable"),
}
assert set(STATUS_LABELS) == set(SOLVER_STATUSES), "status wording out of sync with shared/schemas.py"
