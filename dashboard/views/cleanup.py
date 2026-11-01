"""Respond: vessel routes to the predicted oil patches, with fleet totals."""

from __future__ import annotations

import folium
import pandas as pd
import streamlit as st

import config
from components import maps, ui
from components.data import drift_stage, routing_stage
from services.files import as_float
from services.geo import centroid

stage = routing_stage()
data = stage.data
drift = drift_stage().data
ui.page_heading(
    "Step 03 · Respond",
    "Send the right vessels to the right place",
    "An optimiser assigns cleanup vessels to the predicted oil patches and plans their routes.",
    stage,
)

SOLVER_STATUS = {
    "optimal": ("gog-chip-live", "Optimal plan"),
    "feasible": ("gog-chip-live", "Feasible plan"),
    "infeasible": ("gog-chip-empty", "No feasible plan"),
    "not_solved": ("gog-chip-empty", "Plan not computed"),
    "error": ("gog-chip-empty", "Plan unavailable"),
}

if data is None:
    ui.empty_state(
        "respond",
        "No response plan yet",
        "When a drift forecast is ready, vessels are matched to the predicted oil patches. This view then "
        "shows each vessel's route, the order of its stops, and how long the whole response takes.",
        ["Vessel routes", "Visiting order", "Fleet totals", "Oil recovered"],
    )
else:
    summary = data.summary or {}
    status = str(summary.get("status", "")).lower()
    if status in SOLVER_STATUS:
        css, label = SOLVER_STATUS[status]
        st.html(f'<span class="gog-chip {css}"><span class="gog-dot"></span>{label}</span>')

    collected = as_float(summary.get("oil_collected_m3"))
    total_oil = as_float(summary.get("oil_total_m3"))
    vessel_count = as_float(summary.get("vessel_count"))
    ui.stat_tiles([
        ("Vessels deployed", ui.fmt(vessel_count if vessel_count is not None else float(len(data.routes)), 0), "",
         "Vessels with an assigned route"),
        ("Response time", ui.fmt(as_float(summary.get("total_time_hours"))), "h",
         "Until the last vessel completes its route"),
        ("Distance sailed", ui.fmt(as_float(summary.get("total_distance_km"))), "km", "All vessels combined"),
        ("Oil recovered", ui.fmt(collected, 0), "m³",
         f"Of about {total_oil:,.0f} m³ predicted" if total_oil else "Estimated volume collected"),
    ])

    # --- Map ---------------------------------------------------------------------
    ui.section("Response plan", "Each line is one vessel, from its base to the oil patches it collects.")
    m = maps.base_map()
    fit: list[dict] = []
    legend: list[tuple[str, str, str]] = []

    if drift and drift.steps:
        hours = drift.hours
        target_hours = {as_float(f["properties"].get("source_hours")) for f in (data.targets or {}).get("features", [])}
        default = next((h for h in hours if h in target_hours), next((h for h in (12, 24, 6) if h in hours), hours[-1]))
        shown = st.segmented_control("Predicted oil shown", hours, default=default, required=True,
                                     format_func=lambda h: "Now" if h == 0 else f"+{h:g} h", key="respond_step")
        oil = folium.FeatureGroup(name="Predicted oil")
        maps.add_features(oil, drift.steps[shown], config.oil_color_for_hour(shown), fill_opacity=0.3,
                          weight=1, point_radius=2)
        oil.add_to(m)
        fit += drift.steps[shown]
        legend.append((config.oil_color_for_hour(shown), f"Predicted oil ({'now' if shown == 0 else f'+{shown:g} h'})",
                       "fill"))

    if data.targets:
        group = folium.FeatureGroup(name="Oil patches")
        for feature in data.targets["features"]:
            point = centroid(feature)
            if not point:
                continue
            props = feature["properties"]
            volume = as_float(props.get("oil_volume_m3"))
            label = str(props.get("target_id", "Patch")) + (f" · {volume:,.0f} m³" if volume is not None else "")
            folium.CircleMarker(point, radius=7, color="#061521", weight=2, fill=True, fill_color=config.AMBER,
                                fill_opacity=1, tooltip=label).add_to(group)
        group.add_to(m)
        fit += data.targets["features"]
        legend.append((config.AMBER, "Oil patch to collect", "dot"))

    for i, route in enumerate(data.routes):
        color = config.vessel_color(i)
        latlon = [(lat, lon) for lon, lat, *_ in route.coordinates]
        group = folium.FeatureGroup(name=route.vessel_id)
        folium.PolyLine(latlon, color=color, weight=6, opacity=0.18).add_to(group)  # soft glow
        folium.PolyLine(latlon, color=color, weight=2.5, opacity=0.95,
                        tooltip=f"{route.vessel_id}: {' → '.join(route.order) or 'route'}").add_to(group)
        folium.CircleMarker(latlon[0], radius=6, color=color, weight=2, fill=True, fill_color="#061521",
                            fill_opacity=1, tooltip=f"{route.vessel_id} base").add_to(group)
        for stop, point in enumerate(latlon[1:], start=1):
            folium.CircleMarker(point, radius=3.5, color=color, weight=0, fill=True, fill_opacity=1,
                                tooltip=f"{route.vessel_id} · stop {stop}").add_to(group)
        group.add_to(m)
        fit.append({"geometry": {"type": "LineString", "coordinates": route.coordinates}})
        legend.append((color, route.vessel_id, "line"))

    maps.render(m, fit, key="cleanup_map", height=560)
    ui.legend(legend)

    # --- Table -------------------------------------------------------------------
    ui.section("Vessel assignments")
    if data.routes:
        table = pd.DataFrame([{
            "Vessel": r.vessel_id,
            "Visiting order": " → ".join(r.order) if r.order else "—",
            "Stops": len(r.order),
            "Distance (km)": r.distance_km,
            "Time to finish (h)": r.eta_hours,
            "Oil recovered (m³)": r.oil_collected_m3,
        } for r in data.routes])
        st.dataframe(table, hide_index=True, width="stretch", alt="Vessel assignments", column_config={
            "Distance (km)": st.column_config.NumberColumn(format="%.1f"),
            "Time to finish (h)": st.column_config.NumberColumn(format="%.1f"),
            "Oil recovered (m³)": st.column_config.NumberColumn(format="%.0f"),
        })
    else:
        ui.inline_empty("Individual vessel routes will appear here.")

    with st.expander("How to read this", icon=":material/help:"):
        st.markdown(
            """
- Lines join each vessel's base to its oil patches in visiting order. They are **straight lines**, not checked navigation routes (shallow water, islands and traffic are not considered).
- Oil patches come from the drift forecast, so routes inherit its uncertainty, and the oil keeps moving while vessels travel.
- *Oil recovered* depends on assumed recovery rates and patch volumes.
- A *feasible* plan is valid but not necessarily the best possible; *optimal* means the optimiser proved it is the best.
"""
        )
