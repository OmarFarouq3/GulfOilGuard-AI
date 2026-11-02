"""Data containers the pages render. Real loaders and mock_data both produce these.

Wherever shared/schemas.py defines a structure, the containers hold those dataclasses
(DetectionOutput, DriftOutput, VesselRoute, Vessel, ResponseTarget). Fields marked
"not in schema" are dashboard-only extensions the shared contract does not cover.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.schema import DetectionOutput, DriftOutput, OptimizationOutput, ResponseTarget, Vessel, VesselRoute


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
    metrics: dict[str, float] | None = None  # not in schema: dice, iou, precision, recall
    per_class: dict[str, dict[str, float]] | None = None  # not in schema
    metrics_info: dict[str, Any] = field(default_factory=dict)  # not in schema: model, split, ...
    spill: dict | None = None  # GeoJSON polygons for the map (schema has points only)
    synthetic: bool = False
    warnings: list[str] = field(default_factory=list)
    is_mock: bool = False

    @property
    def has_content(self) -> bool:
        return bool(self.scenes or self.metrics or self.per_class or self.spill)


@dataclass
class DriftData:
    steps: dict[float, list[dict]] = field(default_factory=dict)  # hours since release -> GeoJSON features
    trajectory: DriftOutput | None = None  # representative track, when provided
    meta: dict[str, Any] | None = None  # inputs (wind, current, model): not in schema
    synthetic: bool = False
    warnings: list[str] = field(default_factory=list)
    is_mock: bool = False

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

    @property
    def has_content(self) -> bool:
        return bool(self.routes or self.status)

    # Fleet totals derived from schema fields (OptimizationOutput has no totals of its own).
    @property
    def total_distance_km(self) -> float | None:
        known = [r.route.estimated_distance_km for r in self.routes if r.route.estimated_distance_km is not None]
        return sum(known) if known else None

    @property
    def response_time_hours(self) -> float | None:
        """Until the last vessel finishes: max of VesselRoute.estimated_travel_hours."""
        known = [r.route.estimated_travel_hours for r in self.routes if r.route.estimated_travel_hours is not None]
        return max(known) if known else None

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
