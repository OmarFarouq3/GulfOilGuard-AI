"""GulfOilGuard-AI dashboard entry point.

Run from the repository root:  streamlit run dashboard/app.py
URL options: ?demo=1 starts the simulated scenario, ?dev=1 opens diagnostics.

The dashboard only reads result files (see config.py and README.md). It never imports
torch, opendrift or ortools.
"""

from __future__ import annotations

import streamlit as st

from components import nav, ui
from components.data import all_stages

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
current = st.navigation(list(PAGES.values()), position="hidden")
nav.top_bar(PAGES, all_stages())
current.run()
ui.footer()
