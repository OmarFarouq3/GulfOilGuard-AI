"""B1: the README says to launch from the repo root (the simulated-scores caption left with the accuracy section)."""

from __future__ import annotations

from dashboard_testkit import DASHBOARD_DIR


def test_readme_says_launch_from_the_repo_root():
    assert "**Launch from the repo root**, not from `dashboard/`" in (DASHBOARD_DIR / "README.md").read_text(
        encoding="utf-8")
