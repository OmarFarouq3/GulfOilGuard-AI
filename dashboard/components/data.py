"""One place that decides which data each page shows and how to label it.

Status per stage:
- ``live``: real outputs were found
- ``simulated``: demo scenario is on, or the outputs label themselves ``"synthetic": true``
- ``empty``: nothing to show yet
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import streamlit as st

from services import mock_data
from services.detection_loader import load_detection
from services.drift_loader import load_drift
from services.models import DetectionData, DriftData, RoutingData
from services.routing_loader import load_routing

DEMO_STATE_KEY = "demo_mode"
Status = Literal["live", "simulated", "empty"]


def demo_mode() -> bool:
    """True when the presenter has switched on the demo scenario."""
    return bool(st.session_state.get(DEMO_STATE_KEY, False))


@dataclass
class Stage:
    key: str
    data: Any
    status: Status
    has_issue: bool  # some files could not be read; details live in diagnostics only


def _stage(key: str, data: Any) -> Stage:
    if data is None or not data.has_content:
        return Stage(key, None, "empty", bool(data and data.warnings))
    simulated = data.is_mock or data.synthetic  # loaders set `synthetic` from "synthetic": true flags
    return Stage(key, data, "simulated" if simulated else "live", bool(data.warnings))


def detection_stage() -> Stage:
    data: DetectionData | None = mock_data.detection() if demo_mode() else load_detection()
    return _stage("detect", data)


def drift_stage() -> Stage:
    data: DriftData | None = mock_data.drift() if demo_mode() else load_drift()
    return _stage("predict", data)


def routing_stage() -> Stage:
    data: RoutingData | None = mock_data.routing() if demo_mode() else load_routing()
    return _stage("respond", data)


def all_stages() -> dict[str, Stage]:
    return {"detect": detection_stage(), "predict": drift_stage(), "respond": routing_stage()}
