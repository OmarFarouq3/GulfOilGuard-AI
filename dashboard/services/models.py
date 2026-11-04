"""Data containers the pages render. Real loaders and mock_data both produce these.

Wherever shared/schemas.py defines a structure, the containers hold those dataclasses
(DetectionOutput, DriftOutput, VesselRoute, Vessel, ResponseTarget). Fields marked
"not in schema" are dashboard-only extensions the shared contract does not cover.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from services.schema import (
    DetectionOutput,
    DriftOutput,
    GeoCoordinate,
    OptimizationOutput,
    ResponseTarget,
    Vessel,
    VesselRoute,
)


@dataclass(frozen=True)
class SpillSite:
    """One incident the user can pick on the Overview map (not in schema)."""

    spill_id: str
    name: str
    location: GeoCoordinate
    synthetic: bool = False


@dataclass
class SpillData:
    sites: list[SpillSite] = field(default_factory=list)
    synthetic: bool = False
    warnings: list[str] = field(default_factory=list)
    is_mock: bool = False

    @property
    def has_content(self) -> bool:
        return bool(self.sites)

    def get(self, spill_id: str | None) -> SpillSite | None:
        return next((s for s in self.sites if s.spill_id == spill_id), None)


@dataclass
class DetectionScene:
    """One SAR scene (DetectionOutput.image_id) with its predicted mask and overlay (PNG bytes)."""

    image_id: str
    image: bytes | None = None
    mask: bytes | None = None
    overlay: bytes | None = None


@dataclass
class DetectionData:
    scenes: list[DetectionScene] = field(default_factory=list)
    detections: list[DetectionOutput] = field(default_factory=list)  # one per georeferenced slick
    spill: dict | None = None  # GeoJSON polygons for the map (schema has points only)
    synthetic: bool = False
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # Diagnostics only; unlike warnings, not a viewer-facing issue
    is_mock: bool = False
    # Selected-spill flow (not in schema): where the mask came from, and whether the outline on
    # the map is a simulated placeholder (a real mask from a non-geolocated image has no position).
    mask_source: Literal["model", "simulated"] | None = None
    outline_simulated: bool = False

    @property
    def has_content(self) -> bool:
        return bool(self.scenes or self.spill)


@dataclass
class DriftData:
    steps: dict[float, list[dict]] = field(default_factory=dict)  # hours since release -> GeoJSON features
    trajectory: DriftOutput | None = None  # representative track, when provided
    meta: dict[str, Any] | None = None  # inputs (wind, current, model): not in schema
    synthetic: bool = False
    warnings: list[str] = field(default_factory=list)
    is_mock: bool = False
    anchored_to: str | None = None  # not in schema: spill_id the scenario was moved to
    model_run: bool = False  # meta.json names a real OpenDrift run (drift_loader.is_model_run)

    @property
    def has_content(self) -> bool:
        return bool(self.steps)

    @property
    def hours(self) -> list[float]:
        return sorted(self.steps)


@dataclass
class RouteEntry:
    route: VesselRoute
    vessel: Vessel | None = None  # when speed / capacity / availability are provided
    oil_collected_m3: float | None = None  # not in schema
    finish_hours: float | None = None  # not in schema: sailing + cleaning, back in port (dashboard_export.py)


@dataclass
class RoutingData:
    routes: list[RouteEntry] = field(default_factory=list)
    status: str | None = None  # OptimizationOutput.status
    message: str | None = None  # OptimizationOutput.message
    targets: list[ResponseTarget] = field(default_factory=list)
    target_source_hours: float | None = None  # not in schema: drift step the targets came from
    synthetic: bool = False
    warnings: list[str] = field(default_factory=list)
    is_mock: bool = False
    anchored_to: str | None = None  # not in schema: spill_id the scenario was moved to
    # Extensions written by optimization/dashboard_export.py (not in schema), all optional:
    route_paths: dict[str, list[tuple[float, float]]] = field(default_factory=dict)  # vessel_id -> sea_path (lat, lon)
    target_info: dict[str, dict[str, Any]] = field(default_factory=dict)  # target_id -> served_by, meet/position_hours
    unserved_target_ids: list[str] = field(default_factory=list)
    idle_vessel_ids: list[str] = field(default_factory=list)
    scenario_id: str | None = None  # the drift run the plan was made for (+ "@dispatch...")

    @property
    def has_content(self) -> bool:
        return bool(self.routes or self.status)

    # Fleet totals derived from schema fields (OptimizationOutput has no totals of its own).
    @property
    def total_distance_km(self) -> float | None:
        known = [r.route.estimated_distance_km for r in self.routes if r.route.estimated_distance_km is not None]
        return sum(known) if known else None

    @property
    def sailing_time_hours(self) -> float | None:
        """Longest sailing time of any vessel: max of VesselRoute.estimated_travel_hours (no cleaning)."""
        known = [r.route.estimated_travel_hours for r in self.routes if r.route.estimated_travel_hours is not None]
        return max(known) if known else None

    @property
    def completion_hours(self) -> float | None:
        """When the last vessel is back in port, cleaning included: max of the ``finish_hours`` extension.

        None unless every route gives ``finish_hours`` (a partial maximum would understate it).
        """
        known = [r.finish_hours for r in self.routes]
        return max(known) if known and None not in known else None

    @property
    def response_time_hours(self) -> float | None:
        """The headline response time (decision D2): completion time, else sailing time only."""
        completion = self.completion_hours
        return completion if completion is not None else self.sailing_time_hours

    @property
    def target_oil_m3(self) -> float | None:
        """Oil to collect: sum of ResponseTarget.oil_volume_m3."""
        return sum(t.oil_volume_m3 for t in self.targets) if self.targets else None

    @property
    def oil_collected_m3(self) -> float | None:
        """Not in schema: sum of the per-route oil_collected_m3 extension."""
        known = [r.oil_collected_m3 for r in self.routes if r.oil_collected_m3 is not None]
        return sum(known) if known else None

    @property
    def output(self) -> OptimizationOutput | None:
        """The plan as the shared OptimizationOutput (needs a status)."""
        if self.status is None:
            return None
        return OptimizationOutput(routes=tuple(r.route for r in self.routes), status=self.status,
                                  message=self.message)
