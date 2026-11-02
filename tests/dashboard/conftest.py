"""Fixtures for the dashboard tests. dashboard_testkit must be imported before any dashboard module."""

from __future__ import annotations

import logging

import dashboard_testkit  # noqa: F401  (sets sys.path and the outputs folder first)
import pytest
import streamlit

logging.getLogger("streamlit").setLevel(logging.ERROR)  # quiet "no runtime" notices in bare mode


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
