"""GulfOilGuard-AI dashboard entry point.

Run from the repository root:  streamlit run dashboard/app.py
URL options: ?demo=1 starts the simulated scenario, ?dev=1 opens diagnostics.

Detect can run the U-Net in a subprocess; the Streamlit process does not import
torch, opendrift or ortools. See config.py and README.md for output paths.
"""

from __future__ import annotations

import streamlit as st

from components import nav, ui
from components.data import all_stages, reconcile_selection

st.set_page_config(
    page_title="GulfOilGuard-AI",
    page_icon=":material/water_drop:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

PAGES = {
    "overview": st.Page("views/overview.py", title="Overview", icon=":material/radar:", default=True),
    "detect": st.Page("views/detection.py", title="Detect", icon=":material/satellite_alt:", url_path="detect"),
    "predict": st.Page("views/drift.py", title="Predict", icon=":material/waves:", url_path="predict"),
    "respond": st.Page("views/cleanup.py", title="Respond", icon=":material/directions_boat:",
                       url_path="respond"),
}

ui.load_styles()
nav.init_state()
reconcile_selection()  # one place decides whether the selection and its results are still valid
current = st.navigation(list(PAGES.values()), position="hidden")
nav.top_bar(PAGES, all_stages())
current.run()
ui.footer()
