"""B1: the simulated detection's caption reads cleanly, and the README says to launch from the repo root."""

from __future__ import annotations

import re

from dashboard_testkit import DASHBOARD_DIR
from test_sites import bodies, go, new_app


def test_simulated_detection_caption_reads_cleanly():
    at = go(new_app(demo=True), "views/detection.py")
    caption = next(b for b in bodies(at, "gog-section") if "Overall model accuracy" in b)
    caption = " ".join(re.sub(r"<[^>]+>", " ", caption).split())
    assert "Simulated scores from 0 to 1 for 120 validation images: illustrative values, not computed by the model." \
        in caption
    assert "Validation set (simulated) images" not in caption and "Validation set (simulated) split" not in caption
    how = " ".join(m.value for e in at.expander if e.label == "How to read this" for m in e.markdown)
    assert "illustrative values, not scores computed by the model" in how


def test_readme_says_launch_from_the_repo_root():
    assert "**Launch from the repo root**, not from `dashboard/`" in (DASHBOARD_DIR / "README.md").read_text(
        encoding="utf-8")
