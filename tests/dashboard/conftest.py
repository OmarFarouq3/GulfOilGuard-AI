"""Fixtures for the dashboard tests. dashboard_testkit must be imported before any dashboard module."""

from __future__ import annotations

import logging
import shutil

import dashboard_testkit  # noqa: F401  (sets sys.path and the outputs folder first)
import pytest
import streamlit

logging.getLogger("streamlit").setLevel(logging.ERROR)  # quiet "no runtime" notices in bare mode


@pytest.fixture(scope="session", autouse=True)
def _remove_test_outputs():
    """The outputs folder config points at for the whole session; deleted afterwards."""
    yield
    shutil.rmtree(dashboard_testkit.TEST_OUTPUTS, ignore_errors=True)
    shutil.rmtree(dashboard_testkit.TEST_RUNS, ignore_errors=True)


@pytest.fixture(autouse=True)
def _isolated_layout(tmp_path_factory, monkeypatch):
    """Every test sees an empty repo layout: no real .env, checkpoints/ or .venv-detect/ from this machine.

    Tests that want a layout build one under services.settings.ROOT (or pass ``root=`` explicitly).
    """
    from services import settings
    monkeypatch.setattr(settings, "ROOT", tmp_path_factory.mktemp("repo"))


@pytest.fixture
def session(monkeypatch) -> dict:
    """A plain dict standing in for st.session_state (services.selection only uses mapping ops)."""
    state: dict = {}
    monkeypatch.setattr(streamlit, "session_state", state)
    return state


@pytest.fixture
def image_dir(tmp_path, monkeypatch):
    """Three tiny PNGs, used as the radar dataset through GOG_IMAGE_DIR."""
    directory = dashboard_testkit.make_image_dir(tmp_path / "images")
    monkeypatch.setenv("GOG_IMAGE_DIR", str(directory))
    return directory
