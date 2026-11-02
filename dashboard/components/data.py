"""One place that decides which data each page shows and how to label it.

Status per stage:
- ``live``: real outputs were found
- ``simulated``: demo scenario is on, or the outputs label themselves ``"synthetic": true``
- ``empty``: nothing to show yet

With a spill selected on Overview (services.selection), each stage follows that spill
instead: its data is built by services.scenario and appears only once the step is done
(Detect -> Predict -> Respond). That data is always synthetic, so the status is "simulated".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import streamlit as st

from services import mock_data, scenario, selection
from services.detection_loader import load_detection
from services.drift_loader import load_drift
from services.models import DetectionData, DriftData, RoutingData, SpillData, SpillSite
from services.routing_loader import load_routing
from services.spill_loader import load_spills

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


def dev_mode() -> bool:
    """?dev=1: show technical details (tracebacks, paths) next to errors."""
    return st.query_params.get("dev") == "1"


def data_source() -> tuple:
    """What the selected-spill results are built from: demo flag + drift / routing origin."""
    demo = demo_mode()
    return (demo, "demo" if scenario.source_drift(demo).is_mock else "outputs",
            "demo" if scenario.source_routing(demo).is_mock else "outputs")


def reconcile_selection() -> None:
    """Validate the selection against the current spill list and data source (app.py, once per run)."""
    selection.sync([s.spill_id for s in spills_stage().data.sites], data_source())


def selected_site() -> SpillSite | None:
    """The spill selected on Overview (reconcile_selection has already dropped unknown ids)."""
    spill_id = selection.selected_spill_id()
    return spills_stage().data.get(spill_id) if spill_id else None


def combined_status(stages: dict[str, Stage]) -> Status:
    """One status for numbers built from several stages: simulated if any input is simulated."""
    statuses = {s.status for s in stages.values()}
    return "simulated" if "simulated" in statuses else "live" if "live" in statuses else "empty"


def detection_stage() -> Stage:
    site = selected_site()
    if site:
        data = scenario.selected_detection(site, selection.detection_run(), selection.simulated_detection_accepted())
        return _stage("detect", data)
    data: DetectionData | None = mock_data.detection() if demo_mode() else load_detection()
    return _stage("detect", data)


def drift_stage() -> Stage:
    site = selected_site()
    if site:
        return _stage("predict", scenario.selected_drift(site, demo_mode()) if selection.predict_done() else None)
    data: DriftData | None = mock_data.drift() if demo_mode() else load_drift()
    return _stage("predict", data)


def routing_stage() -> Stage:
    site = selected_site()
    if site:
        return _stage("respond", scenario.selected_routing(site, demo_mode()) if selection.respond_done() else None)
    data: RoutingData | None = mock_data.routing() if demo_mode() else load_routing()
    return _stage("respond", data)


def spills_stage() -> Stage:
    """Spill sites for the Overview map: outputs/spills.geojson, else the simulated catalogue.

    Unlike the three stages there is always something to pick, so an unusable file falls back
    to the catalogue (its warnings still show under Diagnostics).
    """
    loaded = None if demo_mode() else load_spills()
    data: SpillData = loaded if loaded and loaded.has_content else mock_data.spills()
    return _stage("spills", data)


def all_stages() -> dict[str, Stage]:
    return {"detect": detection_stage(), "predict": drift_stage(), "respond": routing_stage()}
