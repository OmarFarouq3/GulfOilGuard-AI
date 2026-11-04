"""The selected-spill flow on the Detect, Predict and Respond pages: progress, gating, provenance.

Each step unlocks the next (services.selection.step_states). Every page states plainly
which parts of its result are real and which are simulated (see services.scenario).
"""

from __future__ import annotations

import streamlit as st

from components import charts, ui
from components.data import demo_mode, dev_mode
from components.labels import KM
from services import image_picker, inference, mock_data, report_loader, scenario, selection
from services.files import read_image
from services.imaging import preview_png
from services.models import SpillSite

OVERVIEW_PAGE = "views/overview.py"
PAGES = {"detect": "views/detection.py", "predict": "views/drift.py", "respond": "views/cleanup.py"}
STEP_NAMES = {"detect": "01 Detect", "predict": "02 Predict", "respond": "03 Respond"}
STATE_WORDS = {"done": "Done", "ready": "Ready", "locked": "Locked"}
LOCKED_REASON = {
    "detect": "Pick a spill on Overview first.",
    "predict": "Run detection on the selected image first, or continue with the simulated detection.",
    "respond": "Show the drift forecast first.",
}


def progress() -> None:
    """Detect -> Predict -> Respond strip for the current selection."""
    states = selection.step_states()
    steps = "".join(
        f'<span class="gog-progress-step gog-progress-{state}" title="{ui.esc(STATE_WORDS[state])}">'
        f'<span class="gog-progress-mark"></span>{STEP_NAMES[key]}'
        f'<span class="gog-progress-state">{STATE_WORDS[state]}</span></span>'
        for key, state in states.items()
    )
    st.html(f'<div class="gog-progress" aria-label="Response progress">{steps}</div>')


def no_selection_prompt() -> None:
    """Shown on Detect / Predict / Respond when no spill is selected (the latest results follow)."""
    with st.container(key="gog-flow-prompt"):
        ui.inline_empty("No incident selected. Pick a spill on Overview to run it through Detect, Predict "
                        "and Respond. Until then this page shows the latest available results.")
        st.page_link(OVERVIEW_PAGE, label="Pick a spill on Overview", icon=":material/arrow_back:")


def _incident(site: SpillSite, show_source: bool = False) -> None:
    current = selection.current()
    image = f" · Radar image {ui.esc(current.image_path.name)}" if current.image_path else ""
    source = image_picker.image_source(current.image_path) if show_source and current.image_path else None
    image += f" ({ui.esc(source)})" if source else ""
    st.html(f'<div class="gog-flow-incident"><b>{ui.esc(site.name)}</b> · {ui.coordinates(site.location.latitude, site.location.longitude)}{image}</div>')


def _provenance(real: list[str], simulated: list[str]) -> None:
    def column(title: str, css: str, items: list[str]) -> str:
        rows = "".join(f"<li>{ui.esc(i)}</li>" for i in items) or "<li>Nothing</li>"
        return f'<div class="gog-prov-col {css}"><h5>{title}</h5><ul>{rows}</ul></div>'

    st.html(f'<div class="gog-prov">{column("Real", "gog-prov-real", real)}'
            f'{column("Simulated", "gog-prov-sim", simulated)}</div>')


def _locked(step: str) -> bool:
    """Show why ``step`` is locked (with a link to the step that unlocks it); True if locked."""
    if selection.step_states()[step] != "locked":
        return False
    previous = {"predict": "detect", "respond": "predict"}.get(step)
    ui.inline_empty(f"This step is locked. {LOCKED_REASON[step]}")
    if previous:
        st.page_link(PAGES[previous], label=f"Go to {STEP_NAMES[previous][3:]}", icon=":material/arrow_back:")
    return True


def next_step(step: str) -> None:
    """'Continue to ...' link; Predict places it below its forecast controls and map."""
    _next(step)


def _next(step: str) -> None:
    st.page_link(PAGES[step], label=f"Continue to {STEP_NAMES[step][3:]}", icon=":material/arrow_forward:",
                 icon_position="right")


# --- Detect -------------------------------------------------------------------------------


def detect_controls(site: SpillSite, overall: dict[str, float] | None = None) -> bool:
    """Detect step for the selected spill; True if a per-image score block was shown.

    ``overall`` are the model's overall scores the page already loaded (real evaluation only); each
    per-image tile then shows the matching overall value as a small secondary line.
    """
    progress()
    _incident(site, show_source=True)
    current = selection.current()
    run = selection.detection_run()

    if selection.detection_done():
        scored = False
        if run and run.ok:
            info = run.info
            details = [f"checkpoint {info['checkpoint']}" if info.get("checkpoint") else None,
                       f"threshold {info['threshold']:g}" if info.get("threshold") is not None else None,
                       f"{info['oil_fraction']:.1%} of the image predicted as oil"
                       if info.get("oil_fraction") is not None else None]
            st.html(f'<span class="gog-chip gog-chip-live"><span class="gog-dot"></span>{ui.esc(run.message)}</span>'
                    f'<p class="gog-flow-note">{ui.esc(" · ".join(d for d in details if d))}</p>')
            scored = _image_score(current, overall)
            _provenance(
                ["Radar image: a sample from the local dataset",
                 "Oil mask and overlay: U-Net prediction on that image",
                 *(["Score against the reference mask (validation report)"] if scored else [])],
                ["Incident location (the image is not geolocated)",
                 "Slick outline and area on the map: a placeholder at the selected spill"],
            )
        else:
            if run and run.state == "checkpoint_missing":
                _failure(run, "A simulated detection is shown instead.")
            _provenance([], ["Radar image, oil mask and overlay (demo scene)",
                             "Model scores (illustrative values)",
                             "Slick outline and area on the map, placed at the selected spill"])
        _next("predict")
        return scored

    if not selection.image_available(current):
        ui.inline_empty("No radar image is assigned to this incident, so the model has nothing to read. "
                        "Assign one on Overview, or continue with the simulated detection.")
        st.button("Use simulated detection", icon=":material/science:", key="flow_detect_simulated",
                  on_click=selection.accept_simulated_detection)
        return False

    left, right = st.columns([2, 3], gap="large")
    with left:
        raw, _warning = read_image(current.image_path)
        shown = preview_png(raw) if raw else None
        if shown:
            st.image(shown, width="stretch", caption="Selected radar image (not geolocated to this spill)")
    with right:
        st.html('<p class="gog-flow-note">The U-Net reads the selected radar image and marks the pixels '
                "it takes for oil. This runs the trained model on this computer.</p>")
        if not inference.checkpoint_path().is_file():
            st.html('<p class="gog-flow-note">No trained model was found on this computer, so running '
                    "detection will show a simulated result instead.</p>")
        if run and not run.ok:
            _failure(run)
            st.button("Use simulated detection instead", icon=":material/science:", key="flow_detect_simulated",
                      on_click=selection.accept_simulated_detection)
        if st.button("Run detection", type="primary", icon=":material/play_arrow:", key="flow_run_detection"):
            with st.spinner("Running the detection model on this image..."):
                result = inference.run_detection(current.image_path, current.image_id, fresh=True)
            selection.record_detection(result)
            st.rerun()
    return False


PRECISION_UNDEFINED = "No oil was predicted, so precision is undefined"
SCORE_CAPTIONS = {
    "val": "How this image scored against its reference mask (validation report). The validation split was "
           "also used to choose the checkpoint, so this is not an independent test.",
    "test": "How this image scored against its reference mask (test report).",
}


def _image_score(current: selection.Selection, overall: dict[str, float] | None = None) -> bool:
    """The selected image's row of Team A's per-image report; True if its scores are shown.

    A row matches on the image's split folder AND its file name: train/ and val/ reuse names.
    Each score tile also shows the model's overall value for that score ("Overall 0.87") when known.
    """
    split = image_picker.image_split(current.image_path)
    row = None if split == "train" else report_loader.per_image_report().lookup(split, current.image_path.name)
    if split == "train":
        missing = "No reference score: this image was part of the model's training data."
    elif row is None:
        missing = "No reference score for this image."
    elif row.empty_reference:  # Dice / IoU are then degenerate (0 or 1)
        missing = "No oil in the reference mask."
    else:
        missing = None
    if missing:
        ui.section("Score for this image")
        ui.inline_empty(missing)
        return False
    ui.section("Score for this image", SCORE_CAPTIONS[split])
    tiles = []
    for key, value in row.scores().items():
        secondary = f"Overall {overall[key]:.2f}" if overall and overall.get(key) is not None else None
        if key == "precision" and row.precision_undefined:  # the report writes 0/0 as 0
            tiles.append((charts.METRIC_LABELS[key], None, "", PRECISION_UNDEFINED, secondary))
        else:
            tiles.append((charts.METRIC_LABELS[key], f"{value:.2f}", "", charts.METRIC_HINTS[key], secondary))
    ui.stat_tiles(tiles + [("Reference oil", f"{row.ref_oil_fraction * 100:.1f}", "%",
                            "Share of the image that is oil in the reference mask")])
    return True


def _failure(run: inference.DetectionRun, follow_up: str = "") -> None:
    """Short, viewer-safe message. Tracebacks and paths only with ?dev=1, collapsed."""
    st.html(f'<div class="gog-notice">{ui.esc(run.message)} {ui.esc(follow_up)}</div>')
    if run.detail and dev_mode():
        with st.expander("Technical details", icon=":material/terminal:"):
            st.code(run.detail, language=None, wrap_lines=True)


# --- Predict / Respond ---------------------------------------------------------------------

PRECOMPUTED_DRIFT = "Precomputed result from the Team B drift run"
PRECOMPUTED_PLAN = "Precomputed result from the Team C routing plan"


def _utc(timestamp: object) -> str | None:
    return f"{timestamp[:16].replace('T', ' ')} UTC" if isinstance(timestamp, str) and len(timestamp) >= 16 else None


def precomputed_drift_note(data) -> None:
    """Predict shows a saved drift run; nothing here re-runs the model (the controls only step through it)."""
    if data.is_mock:
        text = "Precomputed demo scenario (simulated). Nothing is re-simulated here."
    else:
        run = data.trajectory.simulation_id if data.trajectory else (data.meta or {}).get("simulation_id")
        release = _utc((data.meta or {}).get("start_time"))
        details = ", ".join(x for x in (f"run {run}" if run else None, f"released {release}" if release else None) if x)
        text = f"{PRECOMPUTED_DRIFT}{f' ({details})' if details else ''}. Nothing is re-simulated here."
    st.html(f'<p class="gog-flow-note gog-precomputed">{ui.esc(text)} The time controls only step through '
            f'the saved forecast.</p>')


def precomputed_plan_note(data, drift=None) -> None:
    """Respond shows a saved routing plan; nothing here re-runs the optimiser."""
    if data.is_mock:
        text = "Precomputed demo plan (simulated). Nothing is re-optimised here."
    else:
        release = _utc((drift.meta or {}).get("start_time")) if drift is not None and not drift.is_mock else None
        details = ", ".join(x for x in (f"scenario {data.scenario_id}" if data.scenario_id else None,
                                        f"release {release}" if release else None) if x)
        text = f"{PRECOMPUTED_PLAN}{f' ({details})' if details else ''}. Nothing is re-optimised here."
    st.html(f'<p class="gog-flow-note gog-precomputed">{ui.esc(text)} The controls only change what is '
            f'shown.</p>')


def predict_controls(site: SpillSite, demo: bool) -> None:
    progress()
    _incident(site)
    if _locked("predict"):
        return
    real = None if scenario.sites_mode(demo) else scenario.real_forecast(demo)
    if scenario.sites_mode(demo):
        note, real_parts, simulated_parts = _site_drift_note(site)
    elif real is not None and scenario.forecast_applies(real, site):
        note = ("Real OpenDrift forecast, made for this release point. The release point and time are test "
                "inputs, not a detection.")
        real_parts = ["Drift paths, oil footprint and particles (OpenDrift run)", "Wind and current inputs"]
        simulated_parts = ["Release point and time (test inputs, not a detection)"]
    else:
        source = mock_data.drift() if real is not None else scenario.source_drift(demo)
        moved = scenario.shift_km(source, site)
        origin = "the demo drift scenario" if source.is_mock else "the latest drift results"
        note = (f"Simulated drift scenario, positioned at the selected spill: {origin}, moved "
                f"{moved:,.0f} {KM} so that its release point sits on this spill." if moved is not None else
                f"Simulated drift scenario, positioned at the selected spill ({origin}).")
        if real is not None:
            release = scenario.drift_origin(real)
            note = (f"The real forecast was made for a release at {ui.coordinates(*release)} and doesn't apply "
                    f"to this spill, so it isn't shown. {note}")
        real_parts = []
        simulated_parts = ["Drift paths, oil footprint and particles (moved scenario)",
                           "Wind and current inputs (those of the source scenario)"]
    if not selection.predict_done():
        later = " Nothing is re-simulated here: the button shows the saved forecast."
        st.html(f'<p class="gog-flow-note">{ui.esc(note + later)}</p>')
        st.button("Show the drift forecast", type="primary", icon=":material/visibility:", key="flow_run_predict",
                  on_click=selection.complete_predict)
        return
    st.html(f'<div class="{"gog-flow-note" if real_parts else "gog-sim-note"}">{ui.esc(note)}</div>')
    if real_parts or simulated_parts:
        _provenance(real_parts, simulated_parts)


def _site_drift_note(site: SpillSite) -> tuple[str, list[str], list[str]]:
    """Note and Real / Simulated lists for a spill in the per-site layout (outputs/sites/<id>/)."""
    data = scenario.site_drift(site)
    if data is None:
        if scenario.site_drift_unreadable(site):
            return (f"The drift forecast file for site {site.spill_id} could not be read, so no forecast is "
                    "shown. Details are under Diagnostics in the options panel.", [], [])
        return f"There is no drift forecast for site {site.spill_id} yet.", [], []
    if data.model_run:
        return (f"Real OpenDrift forecast for site {site.spill_id}, made for its release point. The release "
                "point and time are test inputs, not a detection.",
                ["Drift paths, oil footprint and particles (OpenDrift run)", "Wind and current inputs"],
                ["Release point and time (test inputs, not a detection)"])
    return (f"The drift results for site {site.spill_id} are not shown as a real forecast: they are not an "
            "OpenDrift run made for this release point.", [],
            ["Drift paths, oil footprint and particles", "Wind and current inputs"])


def respond_controls(site: SpillSite) -> None:
    progress()
    _incident(site)
    if _locked("respond"):
        return
    note = ("Simulated response plan, positioned at the selected spill: the existing plan moved with the "
            "drift scenario. Bases, routes, times and volumes are those of the source plan.")
    real_parts: list[str] = []
    simulated_parts = ["Vessel bases, routes and visiting order (moved plan)",
                       "Distances, response time and oil recovery (unchanged from the source plan)"]
    if scenario.sites_mode(demo_mode()):  # the spill's own site folder, not moved
        if scenario.site_routing(site) is None:
            note, simulated_parts = f"There is no response plan for site {site.spill_id} yet.", []
        else:
            note = (f"Response plan for site {site.spill_id}: the optimiser's plan for this site's drift "
                    "forecast, not moved. It starts from a test release point, not a detection.")
            real_parts = ["Vessel routes and visiting order (optimiser plan for this site)"]
            simulated_parts = ["Release point and time behind the forecast (test inputs)",
                               "Fleet, cleanup rate and other assumptions listed in the plan"]
    if not selection.respond_done():
        later = " Nothing is re-optimised here: the button shows the saved plan."
        st.html(f'<p class="gog-flow-note">{ui.esc(note + later)}</p>')
        st.button("Show the response plan", type="primary", icon=":material/visibility:", key="flow_run_respond",
                  on_click=selection.complete_respond)
        return
    st.html(f'<div class="{"gog-flow-note" if real_parts else "gog-sim-note"}">{ui.esc(note)}</div>')
    if real_parts or simulated_parts:
        _provenance(real_parts, simulated_parts)
