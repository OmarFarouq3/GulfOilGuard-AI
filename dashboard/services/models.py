"""Plain data containers the pages render. Real loaders and mock_data both produce these."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DetectionScene:
    """One SAR scene with its predicted mask and overlay (PNG bytes)."""

    scene_id: str
    image: bytes | None = None
    mask: bytes | None = None
    overlay: bytes | None = None


@dataclass
class DetectionData:
    scenes: list[DetectionScene] = field(default_factory=list)
    metrics: dict[str, float] | None = None  # dice, iou, precision, recall
    per_class: dict[str, dict[str, float]] | None = None
    metrics_info: dict[str, Any] = field(default_factory=dict)  # extra keys, e.g. split, model
    spill: dict | None = None  # GeoJSON FeatureCollection in WGS84
    warnings: list[str] = field(default_factory=list)
    is_mock: bool = False

    @property
    def has_content(self) -> bool:
        return bool(self.scenes or self.metrics or self.per_class or self.spill)


@dataclass
class DriftData:
    steps: dict[float, list[dict]] = field(default_factory=dict)  # hours -> GeoJSON features
    meta: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    is_mock: bool = False

    @property
    def has_content(self) -> bool:
        return bool(self.steps)

    @property
    def hours(self) -> list[float]:
        return sorted(self.steps)


@dataclass
class VesselRoute:
    vessel_id: str
    coordinates: list[list[float]]  # [[lon, lat], ...] in visiting order
    order: list[str] = field(default_factory=list)  # target IDs in visiting order
    eta_hours: float | None = None
    distance_km: float | None = None
    oil_collected_m3: float | None = None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class RoutingData:
    routes: list[VesselRoute] = field(default_factory=list)
    summary: dict[str, Any] | None = None
    targets: dict | None = None  # optional GeoJSON FeatureCollection of target points/areas
    warnings: list[str] = field(default_factory=list)
    is_mock: bool = False

    @property
    def has_content(self) -> bool:
        return bool(self.routes or self.summary)
