"""What the pages say the four sites are matches the evidence (docs/dashboard_provenance_audit.md).

S1-S4 are separate, precomputed OpenDrift runs from hypothetical release points, with an assumed oil
and amount; their plans are optimised on each site's own run. The pages say so with values read from
each site's meta.json, never hard-coded, and the older, less accurate wording does not come back.
The demo scenario stays labelled as an illustrative, simulated scenario.
"""

from __future__ import annotations

import json

import pytest
from dashboard_testkit import DASHBOARD_DIR, page_text
from test_no_team_names import REAL, needs_real, real_outputs, render_all, string_constants  # noqa: F401
from test_site_selector import choose, overview, walk_to_respond

from components import incident, ui

SITES = ("S1", "S2", "S3", "S4")
# Wording replaced because the audit found it misleading or incomplete; it must not return.
#  (meta.json's own note, "…agreed test inputs, not a detection result.", is the drift run's text and stays.)
OLD = ("Real OpenDrift forecast", "over the next 24 hours", "Live data", "the release point is simulated",
       "are test inputs, not a detection.", "(test inputs, not a detection)", "test release point")


def expected(site: str) -> dict[str, str]:
    meta = json.loads((REAL / "sites" / site / "drift" / "meta.json").read_text(encoding="utf-8"))
    loc = meta["initial_location"]
    where = ui.coordinates(loc["latitude"], loc["longitude"])
    start = meta["start_time"][:16].replace("T", " ")
    return {
        "provenance": (f"Precomputed OpenDrift run {meta['simulation_id']} from a hypothetical release point at {where}, "
                       f"released {start} UTC, for {meta['duration_hours']:g} h. Driven by "
                       f"{meta['wind_source'].split(' (')[0]} data and {meta['current_source'].split(':')[0]} currents. "
                       f"Assumed: the release point and time, and the oil ({meta['oil_type'].title()}, "
                       f"{meta['release_volume_m3']:g} m³); this is not an observed spill."),
        "where": where,
        "option": f"Site {site} · precomputed run from a hypothetical release at {where}",
    }


def flat(text: str) -> str:
    return " ".join(text.split())


@needs_real
@pytest.mark.parametrize("site", SITES)
def test_every_page_says_what_the_site_is_from_its_own_files(real_outputs, site):
    want = expected(site)
    at = overview()
    assert want["option"] in at.selectbox(key=incident.SITE_SELECT_KEY).options  # the list
    choose(at, site)
    assert want["provenance"] in flat(page_text(at))  # Overview side panel
    predict, respond = (flat(t) for t in walk_to_respond(at))
    assert f"{want['provenance']} Nothing is re-simulated here." in predict
    assert f"OpenDrift run for site {site}, made for its own release point (not moved from another site)." in predict
    assert f"optimised on the drift run from the hypothetical release point at {want['where']}." in respond
    assert f"Precomputed response plan for site {site}, optimised on this site" in respond
    assert "Real forecast, simulated release" in predict  # the status label, as tests/check_outputs.py prints it


@needs_real
@pytest.mark.parametrize("case", ["no site", "demo", *SITES])
def test_the_old_wording_is_gone_from_every_page(real_outputs, case):
    texts = render_all(spill=None if case in ("no site", "demo") else case, demo=case == "demo")
    found = {page: [w for w in OLD if w in flat(text)] for page, text in texts.items()}
    assert not any(found.values()), found


@pytest.mark.parametrize("path", sorted(DASHBOARD_DIR.rglob("*.py")), ids=lambda p: p.relative_to(DASHBOARD_DIR).as_posix())
def test_the_old_wording_is_gone_from_the_source(path):
    found = [f"line {line}: {text[:80]!r}" for line, text in string_constants(path) if any(w in text for w in OLD)]
    assert not found, found


@needs_real
def test_the_demo_stays_illustrative_and_simulated(real_outputs):
    texts = render_all(spill="GOG-SIM-01", demo=True)
    assert "illustrative demo scenario" in texts["views/overview.py"]
    assert "Precomputed demo scenario (simulated)" in texts["views/drift.py"]
    assert "Simulated scenario" in texts["views/drift.py"] and "Simulated scenario" in texts["views/cleanup.py"]
    assert "hypothetical release point at" not in flat(texts["views/drift.py"])  # not described as a site's run


def test_saved_results_are_not_called_live():
    from components.labels import STAGE_STATUS
    assert STAGE_STATUS["live"][1] == "Saved results"
    assert "not live data" in STAGE_STATUS["live"][2]
