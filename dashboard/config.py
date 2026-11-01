"""Dashboard configuration: output paths (the data contract), map defaults and colours.

The dashboard never runs models. It only reads files written by the detection,
drift and routing modules into ``outputs/``. See ``dashboard/README.md`` for the
full data contract.

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
    "metrics": DETECTION_DIR / "metrics.json",
    "spill": DETECTION_DIR / "spill.geojson",
}

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

DRIFT_HORIZONS_HOURS = (6, 12, 24)
DETECTION_METRICS = ("dice", "iou", "precision", "recall")

# --- Map defaults --------------------------------------------------------------
# Demo centre offshore Abu Dhabi, Arabian Gulf.
MAP_CENTER = (24.5, 54.0)
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
