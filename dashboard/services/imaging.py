"""Small image helpers (PIL + numpy only)."""

from __future__ import annotations

import io

import numpy as np
import streamlit as st
from PIL import Image

OVERLAY_RGB = (245, 158, 11)  # amber tint for predicted oil pixels (oil is amber everywhere)
OVERLAY_ALPHA = 0.45
PREVIEW_MAX_SIDE = 1024
HIGH_BIT_MODES = ("I", "I;16", "I;16B", "I;16L", "F")  # 16-bit / float radar exports


def to_png(array: np.ndarray) -> bytes:
    """Encode a uint8 array (H, W) or (H, W, 3) as PNG bytes."""
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG")
    return buffer.getvalue()


@st.cache_data(show_spinner=False)
def preview_png(raw: bytes, max_side: int = PREVIEW_MAX_SIDE) -> bytes | None:
    """Display copy of a dataset image: 8-bit, at most ``max_side`` px. None if unreadable."""
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            if img.mode in HIGH_BIT_MODES:  # stretch 1st-99th percentile to 0-255
                values = np.asarray(img, dtype=np.float32)
                low, high = np.percentile(values, (1, 99))
                img = Image.fromarray((np.clip((values - low) / max(high - low, 1e-6), 0, 1) * 255).astype(np.uint8))
            else:
                img = img.convert("RGB")
            img.thumbnail((max_side, max_side))
            return to_png(np.asarray(img))
    except Exception:  # PIL raises many exception types for bad images
        return None


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
