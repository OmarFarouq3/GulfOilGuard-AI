"""The app icon comes from assets/icon/icon.jpeg: browser tab and top-bar logo, with a safe fallback."""

from __future__ import annotations

import base64
import io
import os

import pytest
from dashboard_testkit import APP, REPO_ROOT
from PIL import Image
from streamlit.testing.v1 import AppTest

import config
from components import app_icon


@pytest.fixture(autouse=True)
def fresh_cache():
    app_icon._scaled.cache_clear()
    app_icon.logo_html.cache_clear()
    yield
    app_icon._scaled.cache_clear()
    app_icon.logo_html.cache_clear()


def test_the_icon_path_is_absolute_and_independent_of_the_working_directory(tmp_path):
    assert config.ICON_FILE == REPO_ROOT / "assets" / "icon" / "icon.jpeg" and config.ICON_FILE.is_absolute()
    before = os.getcwd()
    try:
        os.chdir(tmp_path)
        assert isinstance(app_icon.page_icon(), Image.Image)
    finally:
        os.chdir(before)


def test_the_tab_icon_is_the_scaled_file():
    icon = app_icon.page_icon()
    assert isinstance(icon, Image.Image) and icon.size == (app_icon.TAB_PX, app_icon.TAB_PX)


def test_the_top_bar_logo_is_the_file_as_a_small_png():
    tag = app_icon.logo_html()
    assert tag.startswith('<img class="gog-logo" src="data:image/png;base64,')
    data = base64.b64decode(tag.split("base64,")[1].split('"')[0])
    with Image.open(io.BytesIO(data)) as image:
        assert image.size == (app_icon.LOGO_PX, app_icon.LOGO_PX)


def test_a_missing_file_falls_back_instead_of_breaking(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ICON_FILE", tmp_path / "gone.jpeg")
    assert app_icon.page_icon() == app_icon.FALLBACK_PAGE_ICON
    assert app_icon.logo_html() is None
    at = AppTest.from_file(str(APP), default_timeout=120).run()
    assert not at.exception
    assert any('class="gog-logo"' in h.proto.body and "image/svg+xml" in h.proto.body for h in at.get("html"))


def test_the_app_uses_the_icon_in_the_top_bar():
    at = AppTest.from_file(str(APP), default_timeout=120).run()
    assert not at.exception
    brand = [h.proto.body for h in at.get("html") if 'class="gog-brand"' in h.proto.body]
    assert brand and 'src="data:image/png;base64,' in brand[0]
    assert app_icon.FALLBACK_PAGE_ICON not in (APP.read_text(encoding="utf-8"))  # page_icon comes from the file
