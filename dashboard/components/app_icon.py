"""The app icon, assets/icon/icon.jpeg: the browser tab (page_icon) and the logo in the top bar.

The file is 1254 x 1254 px, far larger than a favicon or a 30 px logo needs, so it is loaded once
with PIL and scaled down. The path comes from config.ICON_FILE (built from this package's location),
so it resolves whatever the working directory. If the file is missing or unreadable the previous
icons are used, so the dashboard never fails over its icon.
"""

from __future__ import annotations

import base64
import io
from functools import lru_cache

from PIL import Image

import config

TAB_PX = 128  # browser tab / favicon
LOGO_PX = 64  # drawn at 30 px in the top bar (2x for sharp screens)
FALLBACK_PAGE_ICON = ":material/water_drop:"


@lru_cache(maxsize=None)
def _scaled(size: int) -> Image.Image:
    with Image.open(config.ICON_FILE) as image:
        return image.convert("RGB").resize((size, size), Image.Resampling.LANCZOS)


def page_icon() -> Image.Image | str:
    """For st.set_page_config(page_icon=...): the icon as a PIL image, else the previous emoji icon."""
    try:
        return _scaled(TAB_PX)
    except OSError:  # missing or unreadable file (PIL's UnidentifiedImageError is an OSError)
        return FALLBACK_PAGE_ICON


@lru_cache(maxsize=None)
def logo_html(css_class: str = "gog-logo") -> str | None:
    """An <img> tag with the icon as a PNG data URI, or None when the file can't be read."""
    try:
        image = _scaled(LOGO_PX)
    except OSError:
        return None
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f'<img class="{css_class}" src="data:image/png;base64,{data}" alt="">'
