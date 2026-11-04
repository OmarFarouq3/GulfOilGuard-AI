"""A2: Predict and Respond show precomputed results; nothing on them re-runs OpenDrift or the optimiser.

Copy checks (button and control labels in the source) plus page checks (the visible note with the run id
and release time). Detect's "Run detection" is the one control that does compute: it runs the U-Net.
"""

from __future__ import annotations

import ast
import re

import pytest
from dashboard_testkit import DASHBOARD_DIR
from test_sites import SIMULATED_CHIP, bodies, go, heading, new_app, sites  # noqa: F401  (fixture)

from services import selection

COMPUTE_WORDS = re.compile(r"\b(run|re-?run|simulat(?:e|es|ing|ion)|optimi[sz](?:e|es|ing|ation)|comput(?:e|es|ing)|calculat(?:e|es|ing)|plan the)\b", re.IGNORECASE)
LIVE_CONTROLS = {"Run detection"}  # really runs the model (detection.predict_cli in a subprocess)
SOURCES = sorted(DASHBOARD_DIR.rglob("*.py"))
WIDGETS = {"button", "select_slider", "slider", "toggle", "segmented_control", "radio", "selectbox", "page_link"}


def control_labels(path) -> list[tuple[int, str, str]]:
    """(line, widget, label) for every widget call whose label is a string literal."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in WIDGETS:
            label = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "label"), None)
            if label is not None and node.func.attr == "page_link":
                label = next((k.value for k in node.keywords if k.arg == "label"), None)
            if isinstance(label, ast.Constant) and isinstance(label.value, str):
                found.append((node.lineno, node.func.attr, label.value))
    return found


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.relative_to(DASHBOARD_DIR).as_posix())
def test_no_control_label_claims_a_computation(path):
    bad = [f"line {line}: st.{widget}({label!r})" for line, widget, label in control_labels(path)
           if COMPUTE_WORDS.search(label) and label not in LIVE_CONTROLS]
    assert not bad, bad


def test_the_check_catches_the_old_labels():
    assert COMPUTE_WORDS.search("Run drift forecast") and COMPUTE_WORDS.search("Plan the response")
    assert COMPUTE_WORDS.search("Simulate") and COMPUTE_WORDS.search("Optimize routes")
    assert not COMPUTE_WORDS.search("Use simulated detection")
    assert not COMPUTE_WORDS.search("Show the drift forecast") and not COMPUTE_WORDS.search("Show the response plan")


def test_the_buttons_say_show():
    flow = DASHBOARD_DIR / "components" / "flow.py"
    labels = {label for _line, widget, label in control_labels(flow) if widget == "button"}
    assert {"Show the drift forecast", "Show the response plan"} <= labels
    assert not {"Run drift forecast", "Plan the response"} & labels


def page_text(at) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", b) for b in bodies(at, ""))


def site_at(spill: str, page: str):
    at = new_app(spill)
    at.session_state[selection.PREDICT_DONE_KEY] = True
    at.run()
    return go(at, page, "flow_run_respond" if page == "views/cleanup.py" else None)


def test_predict_says_precomputed_with_run_and_release(sites):
    sites("S2")
    text = " ".join(page_text(site_at("S2", "views/drift.py")).split())
    assert ("Precomputed result from the Team B drift run (run openoil-25.70N-55.40E-20261023T1200Z, released "
            "2026-10-23 12:00 UTC). Nothing is re-simulated here. The time controls only step through the saved "
            "forecast.") in text


def test_respond_says_precomputed_with_scenario_and_keeps_the_simulated_label(sites):
    sites("S2")
    at = site_at("S2", "views/cleanup.py")
    text = " ".join(page_text(at).split())
    assert ("Precomputed result from the Team C routing plan (scenario openoil-25.70N-55.40E-20261023T1200Z@dispatch6h, "
            "release 2026-10-23 12:00 UTC). Nothing is re-optimised here.") in text
    assert "Simulated" in heading(at) or "Real forecast" in heading(at)  # the existing label stays


def test_before_showing_the_pages_say_nothing_is_rerun(sites):
    sites("S2")
    at = new_app("S2")
    go(at, "views/drift.py")
    assert "Nothing is re-simulated here: the button shows the saved forecast." in page_text(at)
    at.session_state[selection.PREDICT_DONE_KEY] = True
    at.run()
    go(at, "views/cleanup.py")
    assert "Nothing is re-optimised here: the button shows the saved plan." in page_text(at)


def test_demo_pages_say_precomputed_demo_and_stay_simulated():
    at = go(new_app(demo=True), "views/drift.py")
    assert "Precomputed demo scenario (simulated). Nothing is re-simulated here." in page_text(at)
    assert SIMULATED_CHIP in heading(at)
    at = go(at, "views/cleanup.py")
    assert "Precomputed demo plan (simulated). Nothing is re-optimised here." in page_text(at)
    assert SIMULATED_CHIP in heading(at)


def test_overview_says_predict_and_respond_are_precomputed():
    at = new_app()
    captions = " ".join(c.value for c in at.caption)
    assert "Predict and Respond show precomputed results" in captions
    assert "nothing is re-simulated or re-optimised in the dashboard" in captions


def test_readme_says_precomputed():
    readme = (DASHBOARD_DIR / "README.md").read_text(encoding="utf-8")
    assert "Predict and Respond show precomputed results" in readme
    assert "never re-run OpenDrift or the optimiser" in readme
