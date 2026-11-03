"""Dashboard configuration: output paths (the data contract), map defaults and colours.

Detect can run the U-Net in a subprocess and read its results from ``outputs/``.
Predict and Respond read files written by their modules. See ``dashboard/README.md``.

The outputs folder resolves in this order:
1. ``GULFOILGUARD_OUTPUTS`` environment variable
2. ``outputs_dir`` in ``dashboard/settings.yaml`` (optional, relative paths are
   resolved against the repository root)
3. ``<repo root>/outputs``
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

DASHBOARD_DIR = Path(__file__).resolve().parent
REPO_ROOT = DASHBOARD_DIR.parent
SETTINGS_FILE = DASHBOARD_DIR / "settings.yaml"


def _resolve_outputs_dir() -> Path:
    """Return the outputs folder from env var, settings.yaml, or the default."""
    env_value = os.environ.get("GULFOILGUARD_OUTPUTS")
    if env_value:
        return Path(env_value).expanduser().resolve()
    if SETTINGS_FILE.exists():
        try:
            settings = yaml.safe_load(SETTINGS_FILE.read_text(encoding="utf-8")) or {}
            if isinstance(settings, dict) and settings.get("outputs_dir"):
                return (REPO_ROOT / str(settings["outputs_dir"])).resolve()
        except (OSError, yaml.YAMLError):
            pass  # fall back to the default rather than crash the dashboard
    return REPO_ROOT / "outputs"


OUTPUTS_DIR = _resolve_outputs_dir()

# --- Data contract -----------------------------------------------------------
# Detection module
DETECTION_DIR = OUTPUTS_DIR / "detection"
DETECTION_FILES = {
    "image": DETECTION_DIR / "image.png",  # optional: the SAR input scene
    "mask": DETECTION_DIR / "mask.png",
    "overlay": DETECTION_DIR / "overlay.png",
    "metrics": DETECTION_DIR / "metrics.json",  # detection/evaluate.py (scores nested under "metrics")
    "summary": DETECTION_DIR / "summary.json",  # detection/report.py (scores nested under "micro"), fallback
    "spill": DETECTION_DIR / "spill.geojson",
}

# Evaluation report (detection/report.py writes here by default; read by services/report_loader.py)
REPORT_DIR = OUTPUTS_DIR / "report"
REPORT_FILES = {
    "summary": REPORT_DIR / "summary.json",  # same format as DETECTION_FILES["summary"], last fallback
    "per_image": REPORT_DIR / "per_image_metrics.csv",  # scores per image of the evaluated split
    "gallery_best": REPORT_DIR / "gallery_best.png",
    "gallery_median": REPORT_DIR / "gallery_median.png",
    "gallery_worst": REPORT_DIR / "gallery_worst.png",
}
# The order in which evaluation files are read for scores, the report's split and checkpoint_sha256.
EVALUATION_FILES = (DETECTION_FILES["metrics"], DETECTION_FILES["summary"], REPORT_FILES["summary"])

# Drift module
DRIFT_DIR = OUTPUTS_DIR / "drift"
DRIFT_FILES = {
    "drift": DRIFT_DIR / "drift.geojson",
    "meta": DRIFT_DIR / "meta.json",  # optional
}

# Routing module
ROUTING_DIR = OUTPUTS_DIR / "routing"
ROUTING_FILES = {
    "routes": ROUTING_DIR / "routes.geojson",
    "summary": ROUTING_DIR / "summary.json",
    "targets": ROUTING_DIR / "targets.geojson",  # optional
}

# Spill sites offered on the Overview map (optional; otherwise the simulated catalogue)
SPILLS_FILE = OUTPUTS_DIR / "spills.geojson"

# Detection runs (services/inference.py): the U-Net runs in a subprocess, never in Streamlit.
# Where the checkpoint and the interpreter with torch are is resolved in services/settings.py
# (environment, .env, then checkpoints/unet_best.pth and .venv-detect/); this is the last fallback.
DETECTION_CHECKPOINT = REPO_ROOT / "runs" / "unet_refined_sar" / "best.pth"
DETECTION_TIMEOUT_S = 300  # first torch import + model load on CPU can be slow

DRIFT_HORIZONS_HOURS = (6, 12, 24)
DRIFT_KEY_HOURS = (0, 6, 12, 24)  # quick-jump times on Predict; earlier steps on the map use only these
DETECTION_METRICS = ("dice", "iou", "precision", "recall")

# --- Map defaults --------------------------------------------------------------
# Demo centre offshore Abu Dhabi, Arabian Gulf.
MAP_CENTER = (25.85, 55.65)
MAP_ZOOM = 9

# --- Colours (dark "ocean operations" palette; keep in sync with .streamlit/config.toml) ---
NAVY = "#061521"
SURFACE = "#0c2232"
TEXT = "#e2eef3"
TEXT_MUTED = "#8fa9b8"
GRID = "rgba(226, 238, 243, 0.08)"
TEAL = "#2dd4bf"
SEA_GREEN = "#34d399"
AMBER = "#f59e0b"
SIMULATED = "#a78bfa"
EMPTY = "#6b8797"

# Oil is always warm. The detected slick is amber; drift steps run from bright
# amber (release) to dark burnt orange (24 h), fading as uncertainty grows.
OIL_OBSERVED = "#f59e0b"
OIL_OUTLINE = "#fcd34d"
OIL_BY_HOUR = {0: "#fcd34d", 6: "#f59e0b", 12: "#ea580c", 24: "#c2410c"}

# Vessels use cool, bright colours so routes never look like oil.
VESSEL_COLORS = ("#22d3ee", "#34d399", "#a78bfa", "#60a5fa", "#5eead4", "#f472b6", "#e2e8f0")


def oil_color_for_hour(hours: float) -> str:
    """Return the oil colour for a drift step, falling back to the nearest known step."""
    nearest = min(OIL_BY_HOUR, key=lambda h: abs(h - hours))
    return OIL_BY_HOUR[nearest]


def vessel_color(index: int) -> str:
    """Return a stable colour for the n-th vessel (wraps after seven vessels)."""
    return VESSEL_COLORS[index % len(VESSEL_COLORS)]
