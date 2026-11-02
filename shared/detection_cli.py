"""Contract between the dashboard (services/inference.py) and detection/predict_cli.py.

Standard library only: the dashboard imports this and must never pull in torch.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

MODULE = "detection.predict_cli"  # run as `python -m detection.predict_cli` from the repo root
RESULT_PREFIX = "GOG_RESULT "  # the last stdout line on success: RESULT_PREFIX + JSON
KINDS = ("image", "mask", "overlay")  # written as <image_id>_<kind>.png
EXIT_BAD_ARGS = 2  # argparse's own exit code
EXIT_NO_TORCH = 3
EXIT_FAILED = 4


def atomic_replace(source: str | Path, target: str | Path, attempts: int = 5, delay_s: float = 0.1) -> None:
    """os.replace with a few retries: on Windows it fails while another process has the target open."""
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay_s)
