"""Small image helpers (PIL + numpy only)."""

from __future__ import annotations

import io

import numpy as np
import streamlit as st
from PIL import Image

OVERLAY_RGB = (245, 158, 11)  # amber tint for predicted oil pixels (oil is amber everywhere)
OVERLAY_ALPHA = 0.45


def to_png(array: np.ndarray) -> bytes:
    """Encode a uint8 array (H, W) or (H, W, 3) as PNG bytes."""
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG")
    return buffer.getvalue()


@st.cache_data(show_spinner=False)
def compose_overlay(image_png: bytes, mask_png: bytes) -> bytes | None:
    """Tint mask pixels (>127) on top of the SAR image. Returns None if sizes cannot be matched."""
    try:
        image = Image.open(io.BytesIO(image_png)).convert("RGB")
        mask = Image.open(io.BytesIO(mask_png)).convert("L")
    except Exception:
        return None
    if mask.size != image.size:
        mask = mask.resize(image.size, Image.NEAREST)
    rgb = np.asarray(image, dtype=np.float32)
    oil = np.asarray(mask) > 127
    tint = np.array(OVERLAY_RGB, dtype=np.float32)
    rgb[oil] = (1 - OVERLAY_ALPHA) * rgb[oil] + OVERLAY_ALPHA * tint
    return to_png(rgb.clip(0, 255).astype(np.uint8))
