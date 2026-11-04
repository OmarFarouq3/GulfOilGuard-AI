"""Problem 1: a site's drift.geojson that exists but cannot be read is not "no forecast yet".

Its loader warning reaches Diagnostics, Predict says the file could not be read, and Respond keeps
its cautious "Simulated scenario" label.
"""

from __future__ import annotations

import re

from test_sites import SIMULATED_CHIP, bodies, go, heading, new_app, sites  # noqa: F401  (fixture)

import config
from services import selection

UNREADABLE = "The drift forecast file for site S1 could not be read, so no forecast is shown."
MISSING = "There is no drift forecast for site S1 yet."


def text(at) -> str:
    return " ".join(" ".join(re.sub(r"<[^>]+>", " ", b) for b in bodies(at, "")).split())


def diagnostics(at) -> str:
    return " ".join(str(m.value) for m in at.markdown)


def predict(spill: str = "S1"):
    at = new_app(spill)
    at.session_state[selection.PREDICT_DONE_KEY] = True
    at.run()
    return go(at, "views/drift.py")


def break_drift(site_id: str = "S1") -> None:
    config.site_files(site_id)["drift"]["drift"].write_text("{ not json", encoding="utf-8")


def test_unreadable_drift_file_is_named_on_predict_and_in_diagnostics(sites):
    sites("S1", "S2")
    break_drift("S1")
    at = predict("S1")
    page = text(at)
    assert UNREADABLE in page and MISSING not in page
    warnings = diagnostics(at)
    assert "No warnings" not in warnings
    assert re.search(r"Site `S1`: .*drift\.geojson", warnings), warnings


def test_a_missing_drift_file_still_says_no_forecast_yet(sites):
    sites("S1", "S2")
    config.site_files("S1")["drift"]["drift"].unlink()  # meta.json stays, so the S1 marker stays
    page = text(predict("S1"))
    assert MISSING in page and UNREADABLE not in page


def test_respond_stays_simulated_when_the_forecast_is_unreadable(sites):
    sites("S1")
    break_drift("S1")
    at = predict("S1")
    at = go(at, "views/cleanup.py", "flow_run_respond")
    assert SIMULATED_CHIP in heading(at)

