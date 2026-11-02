"""Setup and helpers shared by the dashboard tests (imported first by conftest.py).

The dashboard's modules are top-level names (``config``, ``services``, ``components``), as
when Streamlit runs ``dashboard/app.py``, so ``dashboard/`` goes on sys.path. ``config``
reads ``GULFOILGUARD_OUTPUTS`` once at import, so it is pointed at a throwaway folder before
anything imports it, and the GOG_* variables are cleared: tests never touch the real
``outputs/`` or ``assets/images``. The real values are kept for the end-to-end check only.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_DIR = REPO_ROOT / "dashboard"
APP = DASHBOARD_DIR / "app.py"

# Captured before clearing, for test_inference_e2e.py.
REAL_ENV = {k: os.environ.get(k) for k in ("GOG_IMAGE_DIR", "GOG_CHECKPOINT", "GOG_DETECTION_PYTHON")}
for _key in REAL_ENV:
    os.environ.pop(_key, None)
TEST_OUTPUTS = Path(tempfile.mkdtemp(prefix="gog_test_outputs_"))  # removed by conftest at session end
os.environ["GULFOILGUARD_OUTPUTS"] = str(TEST_OUTPUTS)

for _path in (DASHBOARD_DIR, REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


def make_image(path: Path, size: tuple[int, int] = (16, 12), seed: int = 0) -> Path:
    """Write a tiny grayscale image; the format follows the extension (.png / .jpg / .jpeg)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pixels = np.random.default_rng(seed).integers(0, 256, size=(size[1], size[0]), dtype=np.uint8)
    Image.fromarray(pixels).save(path, format="JPEG" if path.suffix.lower() in (".jpg", ".jpeg") else "PNG")
    return path


def make_image_dir(root: Path, count: int = 3) -> Path:
    for i in range(count):
        make_image(root / f"scene_{i}.png", seed=i)
    return root


def page_text(at) -> str:
    """Every element's protobuf as text: HTML bodies, captions, labels, image captions."""
    parts: list[str] = []

    def walk(node) -> None:
        proto = getattr(node, "proto", None)
        if proto is not None:
            parts.append(str(proto))
        for child in getattr(node, "children", {}).values():
            walk(child)

    walk(at.main)
    return "\n".join(parts)
