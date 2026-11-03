"""The selected-spill flow on the Detect, Predict and Respond pages: progress, gating, provenance.

Each step unlocks the next (services.selection.step_states). Every page states plainly
which parts of its result are real and which are simulated (see services.scenario).
"""

from __future__ import annotations

import streamlit as st

from components import charts, ui
from components.data import dev_mode
from components.labels import KM
from services import image_picker, inference, report_loader, scenario, selection
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
    "respond": "Run the drift forecast first.",
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


def _next(step: str) -> None:
    st.page_link(PAGES[step], label=f"Continue to {STEP_NAMES[step][3:]}", icon=":material/arrow_forward:",
                 icon_position="right")


# --- Detect -------------------------------------------------------------------------------


def detect_controls(site: SpillSite) -> None:
    progress()
    _incident(site, show_source=True)
    current = selection.current()
    run = selection.detection_run()

    if selection.detection_done():
        if run and run.ok:
            info = run.info
            details = [f"checkpoint {info['checkpoint']}" if info.get("checkpoint") else None,
                       f"threshold {info['threshold']:g}" if info.get("threshold") is not None else None,
                       f"{info['oil_fraction']:.1%} of the image predicted as oil"
                       if info.get("oil_fraction") is not None else None]
            st.html(f'<span class="gog-chip gog-chip-live"><span class="gog-dot"></span>{ui.esc(run.message)}</span>'
                    f'<p class="gog-flow-note">{ui.esc(" · ".join(d for d in details if d))}</p>')
            scored = _image_score(current)
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
        return

    if not selection.image_available(current):
        ui.inline_empty("No radar image is assigned to this incident, so the model has nothing to read. "
                        "Assign one on Overview, or continue with the simulated detection.")
        st.button("Use simulated detection", icon=":material/science:", key="flow_detect_simulated",
                  on_click=selection.accept_simulated_detection)
        return

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
                result = inference.run_detection(current.image_path, current.image_id)
            selection.record_detection(result)
            st.rerun()


PRECISION_UNDEFINED = "No oil was predicted, so precision is undefined"
SCORE_CAPTIONS = {
    "val": "How this image scored against its reference mask (validation report). The validation split was "
           "also used to choose the checkpoint, so this is not an independent test.",
    "test": "How this image scored against its reference mask (test report).",
}


def _image_score(current: selection.Selection) -> bool:
    """The selected image's row of Team A's per-image report; True if its scores are shown.

    A row matches on the image's split folder AND its file name: train/ and val/ reuse names.
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
        if key == "precision" and row.precision_undefined:  # the report writes 0/0 as 0
            tiles.append((charts.METRIC_LABELS[key], None, "", PRECISION_UNDEFINED))
        else:
            tiles.append((charts.METRIC_LABELS[key], f"{value:.2f}", "", charts.METRIC_HINTS[key]))
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


def predict_controls(site: SpillSite, demo: bool) -> None:
    progress()
    _incident(site)
    if _locked("predict"):
        return
    source = scenario.source_drift(demo)
    moved = scenario.shift_km(source, site)
    origin = "the demo drift scenario" if source.is_mock else "the latest drift results"
    note = (f"Simulated drift scenario, positioned at the selected spill: {origin}, moved "
            f"{moved:,.0f} {KM} so that its release point sits on this spill." if moved is not None else
            f"Simulated drift scenario, positioned at the selected spill ({origin}).")
    if not selection.predict_done():
        st.html(f'<p class="gog-flow-note">{ui.esc(note)} The drift model itself is not run for this incident yet.</p>')
        st.button("Run drift forecast", type="primary", icon=":material/play_arrow:", key="flow_run_predict",
                  on_click=selection.complete_predict)
        return
    st.html(f'<div class="gog-sim-note">{ui.esc(note)}</div>')
    _provenance([], ["Drift paths, oil footprint and particles (moved scenario)",
                     "Wind and current inputs (those of the source scenario)"])
    _next("respond")


def respond_controls(site: SpillSite) -> None:
    progress()
    _incident(site)
    if _locked("respond"):
        return
    note = ("Simulated response plan, positioned at the selected spill: the existing plan moved with the "
            "drift scenario. Bases, routes, times and volumes are those of the source plan.")
    if not selection.respond_done():
        st.html(f'<p class="gog-flow-note">{ui.esc(note)} The optimiser itself is not run for this incident yet.</p>')
        st.button("Plan the response", type="primary", icon=":material/play_arrow:", key="flow_run_respond",
                  on_click=selection.complete_respond)
        return
    st.html(f'<div class="gog-sim-note">{ui.esc(note)}</div>')
    _provenance([], ["Vessel bases, routes and visiting order (moved plan)",
                     "Distances, response time and oil recovery (unchanged from the source plan)"])
