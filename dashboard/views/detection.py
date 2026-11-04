"""Detect: SAR imagery, the predicted oil mask for the analysed scene, and the slick on the map.

With a spill selected on Overview, components.flow runs the U-Net on its radar image first.
"""

from __future__ import annotations

import streamlit as st

import config
from components import flow, maps, ui
from components.data import detection_stage, selected_site
from components.labels import slick_tooltip
from services.detection_loader import load_galleries

stage = detection_stage()
data = stage.data
ui.page_heading(
    "Step 01 · Detect",
    "Spot the slick from orbit",
    "A U-Net model reads SAR imagery and outlines oil on the sea surface.",     #Edit 1: Sentinel-1 radar --> SAR imagery
    stage,
)
# The evaluation report's example images describe the real model: never shown next to the demo scene.
real_report = data is not None and not data.is_mock

MASK_MISSING = ("The detected oil mask for this scene is not available yet, so the radar image is shown without "
                "the model's outline.")
NO_SCENE = "The radar image and detected oil mask are not available yet. They will appear here once a scene has been analysed."


def galleries() -> None:
    """report.py's best / median / worst validation images, when the files exist."""
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
if site:
    flow.detect_controls(site)
else:
    flow.no_selection_prompt()

if data is None:
    if site is None:
        ui.empty_state(
            "detect",
            "No satellite scene analysed yet",
            "Once a radar scene of the Gulf is analysed, this view shows the image, the oil the model "
            "found in it, and where the slick sits on the map.",
            ["Radar scene", "Detected oil outline", "Slick on the map"],
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
        if scene.mask is None:
            st.html(f'<div class="gog-notice">{ui.esc(MASK_MISSING)}</div>')
        with st.container(key="gog-imagery"):
            for column, (label, img) in zip(st.columns(len(panels)), panels):
                column.image(img, caption=label, width="stretch", alt=label)
    else:
        ui.inline_empty(NO_SCENE)

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

    with st.expander("How to read this", icon=":material/help:"):
        st.markdown(
            """
- **Dark means oil.** Oil damps the small waves that reflect radar back to the satellite, so slicks look dark.
- **Look-alikes** also look dark: very calm water, algae and natural films, rain cells and ship wakes. They cause false alarms (lower precision).
- **Thin or broken slicks**, and strong wind that breaks slicks up, cause missed oil (lower recall).
- **Location** is a separate step: a correct outline with wrong scene geometry still lands in the wrong place.
"""
        )
