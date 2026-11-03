"""Top bar: brand, the Detect -> Predict -> Respond response timeline, and the options panel.

The options panel (gear icon) is the only place that shows technical details such as
the resolved data folder, file timestamps and loader warnings.
"""

from __future__ import annotations

import streamlit as st

import config
from components import illustrations
from components.data import DEMO_STATE_KEY, Stage, demo_mode, dev_mode
from components.labels import STAGE_STATUS
from services import image_picker, report_loader, selection, settings
from services.detection_loader import load_detection, load_galleries
from services.drift_loader import load_drift
from services.files import format_mtime
from services.routing_loader import load_routing
from services.selection import available_images
from services.spill_loader import load_spills

STATUS_HELP = {status: help_text for status, (_css, _label, help_text) in STAGE_STATUS.items()}
STEPS = (("detect", "01", "Detect"), ("predict", "02", "Predict"), ("respond", "03", "Respond"))
# With a spill selected, the timeline doubles as its progress indicator.
STEP_HELP = {
    "done": "Done for the selected spill",
    "ready": "Ready: open this step to run it",
    "locked": "Locked: finish the previous step first",
}


def init_state() -> None:
    """Initialise session state once from the URL (?demo=1, legacy ?mock=1)."""
    if DEMO_STATE_KEY not in st.session_state:
        params = st.query_params
        st.session_state[DEMO_STATE_KEY] = params.get("demo") == "1" or params.get("mock") == "1"


def top_bar(pages: dict[str, st.Page], stages: dict[str, Stage]) -> None:
    """Brand on the left, response timeline in the middle, options gear on the right."""
    with st.container(horizontal=True, key="gog-topbar", vertical_alignment="center", gap="medium"):
        st.html(
            f'<div class="gog-brand">{illustrations.img(illustrations.LOGO, "gog-logo")}'
            '<div><div class="gog-brand-name">GulfOilGuard<span>-AI</span></div>'
            '<div class="gog-brand-tag">Oil spill response · Arabian Gulf</div></div></div>',
            width="content",
        )
        with st.container(horizontal=True, key="gog-timeline", vertical_alignment="center", gap=None,
                          width="content"):
            st.page_link(pages["overview"], label="Overview", icon=":material/radar:")
            progress = selection.step_states() if selection.active() else None
            for key, number, verb in STEPS:
                st.html('<div class="gog-connector" aria-hidden="true"></div>', width="content")
                status = stages[key].status
                # Status dot is drawn by CSS from the container key (…-live / -simulated / -empty).
                with st.container(key=f"gog-step-{key}-{status}", width="content"):
                    st.page_link(pages[key], label=f"{number} {verb}",
                                 help=STEP_HELP[progress[key]] if progress else STATUS_HELP[status])
        options_panel()


def options_panel() -> None:
    """Discreet gear popover: demo scenario, refresh, and collapsed diagnostics."""
    with st.popover("Options", icon=":material/settings:", type="tertiary", key="gog-options",
                    help="Presenter & developer options"):
        st.markdown("**Presenter & developer options**")
        st.toggle(
            "Demo scenario",
            value=demo_mode(),
            key="_demo_toggle",
            on_change=lambda: st.session_state.update({DEMO_STATE_KEY: st.session_state["_demo_toggle"]}),
            help="Show a simulated Gulf incident on every page. Pages are labelled as simulated.",
        )
        st.button("Refresh data", icon=":material/refresh:", width="stretch",
                  help="Re-read results. Changed files are picked up automatically on every refresh.")
        with st.expander("Diagnostics", icon=":material/terminal:", expanded=dev_mode()):
            diagnostics()


def diagnostics() -> None:
    """Technical details for developers: data folder, file status, loader warnings."""
    st.caption("Data folder")
    st.code(str(config.OUTPUTS_DIR), language=None, wrap_lines=True)
    rows = []
    for module, files in (("detection", config.DETECTION_FILES), ("report", config.REPORT_FILES),
                          ("drift", config.DRIFT_FILES), ("routing", config.ROUTING_FILES)):
        for path in files.values():
            rows.append({"Module": module, "File": f"{path.parent.name}/{path.name}",
                         "Modified": format_mtime(path) or "missing"})
    rows.append({"Module": "spills", "File": config.SPILLS_FILE.name,
                 "Modified": format_mtime(config.SPILLS_FILE) or "missing (simulated catalogue)"})
    st.dataframe(rows, hide_index=True, width="stretch")

    st.caption(f"Radar image folder ({len(available_images())} readable images)")
    st.code(str(image_picker.image_dir()), language=None, wrap_lines=True)
    st.caption("Detection setup (environment > .env > standard layout)")
    checkpoint, python = settings.resolve_checkpoint(), settings.resolve_python()
    st.code(f"checkpoint: {checkpoint.path}  [{checkpoint.source}{'' if checkpoint.path.is_file() else ', missing'}]\n"
            f"python:     {python.path}  [{python.source}]", language=None, wrap_lines=True)

    warnings = list(settings.env_file()[1])
    warnings += report_loader.per_image_report().warnings + load_galleries()[1]
    warnings += report_loader.check_checkpoint(checkpoint.path).warnings
    for loader in (load_detection, load_drift, load_routing, load_spills):
        data = loader()
        if data is not None:
            warnings.extend(data.warnings)
    st.caption("Loader warnings")
    if warnings:
        for message in warnings:
            st.markdown(f"- {message}")
    else:
        st.markdown(":green[No warnings]")
    st.caption(f"Demo scenario: {'on' if demo_mode() else 'off'}. URL options: ?demo=1, ?dev=1")
