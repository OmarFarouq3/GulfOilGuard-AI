"""Detect: SAR imagery, predicted oil mask, model quality and the slick on the map.

With a spill selected on Overview, components.flow runs the U-Net on its radar image first.
"""

from __future__ import annotations

import streamlit as st

import config
from components import charts, flow, maps, ui
from components.data import detection_stage, selected_site
from components.labels import slick_tooltip
from services import inference, report_loader
from services.detection_loader import load_galleries

stage = detection_stage()
data = stage.data
ui.page_heading(
    "Step 01 · Detect",
    "Spot the slick from orbit",
    "A U-Net model reads SAR imagery and outlines oil on the sea surface.",     #Edit 1: Sentinel-1 radar --> SAR imagery
    stage,
)
# Team A's report describes the real model: never shown next to the demo scene or illustrative scores.
real_report = data is not None and not data.is_mock and data.metrics_info.get("synthetic") is not True


DETAIL_LABELS = {"model": "Model", "split": "Evaluated on", "n_images": "Images evaluated",
                 "threshold": "Decision threshold", "checkpoint": "Checkpoint", "epoch": "Checkpoint epoch",
                 "aggregation": "Aggregation", "created": "Evaluated"}  # "limitations" is shown as a caption
SPLIT_NAMES = {"train": "training", "test": "test"}


def accuracy_caption(split: object) -> str:
    """Name the split the scores come from, as the evaluation file states it; never assume validation."""
    name = split.strip().lower() if isinstance(split, str) else ""
    if name in ("val", "validation"):
        return ("Scores from 0 to 1, computed on the validation split. That split was also used to choose the "
                "checkpoint, so these are not an independent test.")
    if name:
        return f"Scores from 0 to 1, computed on the {SPLIT_NAMES.get(name, split.strip())} split."
    return "Scores from 0 to 1. The report doesn't say which images were scored."


OVERALL_TITLE = "Overall model accuracy"
STATIC_NOTE = "These overall scores don't change from image to image; the score for the selected image is shown above."
SPLIT_WORDS = {"val": "validation", "validation": "validation", "train": "training", "test": "test"}


def overall_caption(split: object, n_images: object) -> str:
    """Name the evaluated image set without implying a per-image average."""
    name = split.strip().lower() if isinstance(split, str) else ""
    word = SPLIT_WORDS.get(name, split.strip() if name else "")
    known = isinstance(n_images, int) and not isinstance(n_images, bool) and n_images > 0
    images = f"{n_images:,} {word} images" if known else f"all evaluated {word} images"
    return f"Scores across {' '.join(images.split())}. {accuracy_caption(split)}"


def checkpoint_note() -> None:
    """Whether the scores were computed on the checkpoint this dashboard runs (checkpoint_sha256)."""
    check = report_loader.check_checkpoint(inference.checkpoint_path())
    if check.state == "mismatch":
        st.html(f'<div class="gog-notice">{ui.esc(check.message)}</div>')
    else:
        st.html(f'<p class="gog-flow-note">{ui.esc(check.message)}</p>')


def galleries() -> None:
    """report.py's best / median / worst validation images (under Overall model accuracy), when the files exist."""
    shown, _warnings = load_galleries()  # unreadable files are listed under Diagnostics
    if not shown:
        return
    with st.expander("Best, median and worst validation images", icon=":material/photo_library:"):
        st.caption("Each row shows one image: input, reference, prediction, errors (green correct, red false "
                   "alarm, blue missed). The validation split was also used to choose the checkpoint, so these "
                   "images are not an independent test.")
        for column, (caption, content) in zip(st.columns(len(shown)), shown):
            column.image(content, caption=caption, width="stretch", alt=f"{caption} validation images")


site = selected_site()
image_scored = False  # a "Score for this image" block with scores is on the page
if site:
    image_scored = flow.detect_controls(site, data.metrics if real_report else None)
else:
    flow.no_selection_prompt()

if data is None:
    if site is None:
        ui.empty_state(
            "detect",
            "No satellite scene analysed yet",
            "Once a radar scene of the Gulf is analysed, this view shows the image, the oil the model "
            "found in it, how accurate the model is, and where the slick sits on the map.",
            ["Radar scene", "Detected oil outline", "Model performance", "Slick on the map"],   #Edit 2: Model accuracy  --> Model performance
        )
else:
    # --- Imagery ---------------------------------------------------------------
    ui.section("Radar scene and detected oil", "Oil calms the sea surface, so it appears dark in radar images.")
    if data.scenes:
        scene = data.scenes[0]
        if len(data.scenes) > 1:
            ids = [s.image_id for s in data.scenes]
            chosen = st.selectbox("Scene", ids, format_func=lambda s: "Main scene" if s == "default" else s)
            scene = data.scenes[ids.index(chosen)]
        panels = [(label, img) for label, img in (
            ("Radar image", scene.image), ("Detected oil (white)", scene.mask), ("Overlay", scene.overlay),
        ) if img]
        with st.container(key="gog-imagery"):
            for column, (label, img) in zip(st.columns(len(panels)), panels):
                column.image(img, caption=label, width="stretch", alt=label)
    else:
        ui.inline_empty("The radar image and detected oil outline will appear here.")

    # --- Model quality ---------------------------------------------------------
    if data.metrics:
        ui.section(OVERALL_TITLE, overall_caption(data.metrics_info.get("split"), data.metrics_info.get("n_images")))
        ui.stat_tiles([
            (charts.METRIC_LABELS[k], f"{data.metrics[k]:.2f}" if k in data.metrics else None, "",
             charts.METRIC_HINTS[k])
            for k in config.DETECTION_METRICS
        ])
        if image_scored:
            st.html(f'<p class="gog-flow-note">{ui.esc(STATIC_NOTE)}</p>')
        if real_report:
            checkpoint_note()
        left, right = st.columns([3, 2], gap="large")
        with left:
            figure = charts.per_class_bar(data.per_class) if data.per_class else charts.metrics_bar(data.metrics)
            st.plotly_chart(figure, width="stretch", config=charts.CHART_CONFIG)
        with right:
            # metrics_info holds only detection_loader.DETAIL_KEYS (path-like text already reduced).
            details = {DETAIL_LABELS[k]: v for k, v in data.metrics_info.items() if k in DETAIL_LABELS}
            ui.section("Evaluation details")
            if details:
                ui.details_table(details)
            else:
                ui.inline_empty("Model and evaluation details will appear here.")
            if isinstance(data.metrics_info.get("limitations"), str):
                st.caption(data.metrics_info["limitations"])
    else:
        ui.section(OVERALL_TITLE)
        ui.inline_empty("Accuracy scores will appear here once the model has been evaluated.")
    if real_report:
        galleries()

    # --- Map -------------------------------------------------------------------
    if data.outline_simulated:
        ui.section("Where is the slick?", "Simulated outline at the selected spill. The radar image is not "
                   "geolocated, so the detected mask itself has no position on the map.")
    else:
        ui.section("Where is the slick?", "The detected outline placed on the map.")
    if data.spill:
        m = maps.base_map()
        maps.add_features(m, data.spill["features"], config.OIL_OBSERVED, outline=config.OIL_OUTLINE,
                          fill_opacity=0.5,
                          tooltip=slick_tooltip(data.outline_simulated))
        maps.render(m, data.spill["features"], key="detection_map")
        ui.legend([(config.OIL_OBSERVED, "Simulated slick outline" if data.outline_simulated else "Detected oil",
                    "fill")])
    else:
        ui.inline_empty("The slick will appear on the map once the scene has been located geographically.")

    # The same caveat as the accuracy caption and detection/evaluate.py's recorded note: validation images
    # chose the checkpoint, so they are not an independent test.
    split = str(data.metrics_info.get("split") or "").strip().lower()
    scored_on = ("the labelled validation images, which were also used to choose the checkpoint, so they are not an "
                 "independent test" if split in ("val", "validation") else "a labelled evaluation set")
    with st.expander("How to read this", icon=":material/help:"):
        st.markdown(
            f"""
- **Dark means oil.** Oil damps the small waves that reflect radar back to the satellite, so slicks look dark.
- **Look-alikes** also look dark: very calm water, algae and natural films, rain cells and ship wakes. They cause false alarms (lower precision).
- **Thin or broken slicks**, and strong wind that breaks slicks up, cause missed oil (lower recall).
- **Accuracy scores** describe the model on {scored_on}; they are not a guarantee for every new scene.
- **Location** is a separate step: a correct outline with wrong scene geometry still lands in the wrong place.
"""
        )
