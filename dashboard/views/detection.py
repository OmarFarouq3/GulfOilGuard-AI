"""Detect: SAR imagery, predicted oil mask, model quality and the slick on the map."""

from __future__ import annotations

import streamlit as st

import config
from components import charts, maps, ui
from components.data import detection_stage
from components.labels import KM2

stage = detection_stage()
data = stage.data
ui.page_heading(
    "Step 01 · Detect",
    "Spot the slick from orbit",
    "A U-Net model reads Sentinel-1 radar imagery and outlines oil on the sea surface.",
    stage,
)

if data is None:
    ui.empty_state(
        "detect",
        "No satellite scene analysed yet",
        "Once a radar scene of the Gulf is analysed, this view shows the image, the oil the model "
        "found in it, how accurate the model is, and where the slick sits on the map.",
        ["Radar scene", "Detected oil outline", "Model accuracy", "Slick on the map"],
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
    ui.section("How accurate is the model?", "Scores from 0 to 1 on images the model never saw in training.")
    if data.metrics:
        hints = {
            "dice": "Overlap between detected and true oil",
            "iou": "Shared area over combined area",
            "precision": "Flagged pixels that really are oil",
            "recall": "Real oil pixels that were found",
        }
        ui.stat_tiles([
            (charts.METRIC_LABELS[k], f"{data.metrics[k]:.2f}" if k in data.metrics else None, "", hints[k])
            for k in config.DETECTION_METRICS
        ])
        left, right = st.columns([3, 2], gap="large")
        with left:
            figure = charts.per_class_bar(data.per_class) if data.per_class else charts.metrics_bar(data.metrics)
            st.plotly_chart(figure, width="stretch", config=charts.CHART_CONFIG)
        with right:
            labels = {"model": "Model", "split": "Evaluated on", "n_images": "Images evaluated",
                      "threshold": "Decision threshold"}
            details = {labels.get(k, k.replace("_", " ").capitalize()): v
                       for k, v in data.metrics_info.items()
                       if k != "synthetic" and not isinstance(v, (dict, list))}
            ui.section("Evaluation details")
            if details:
                ui.details_table(details)
            else:
                ui.inline_empty("Model and evaluation details will appear here.")
    else:
        ui.inline_empty("Accuracy scores will appear here once the model has been evaluated.")

    # --- Map -------------------------------------------------------------------
    ui.section("Where is the slick?", "The detected outline placed on the map.")
    if data.spill:
        m = maps.base_map()
        maps.add_features(m, data.spill["features"], config.OIL_OBSERVED, outline=config.OIL_OUTLINE,
                          fill_opacity=0.5,
                          tooltip={"image_id": "Scene", "area_km2": f"Area ({KM2})", "confidence": "Confidence"})
        maps.render(m, data.spill["features"], key="detection_map")
        ui.legend([(config.OIL_OBSERVED, "Detected oil", "fill")])
    else:
        ui.inline_empty("The slick will appear on the map once the scene has been located geographically.")

    with st.expander("How to read this", icon=":material/help:"):
        st.markdown(
            """
- **Dark means oil.** Oil damps the small waves that reflect radar back to the satellite, so slicks look dark.
- **Look-alikes** also look dark: very calm water, algae and natural films, rain cells and ship wakes. They cause false alarms (lower precision).
- **Thin or broken slicks**, and strong wind that breaks slicks up, cause missed oil (lower recall).
- **Accuracy scores** describe the model on a labelled test set, not a guarantee for every new scene.
- **Location** is a separate step: a correct outline with wrong scene geometry still lands in the wrong place.
"""
        )
