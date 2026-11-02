"""Respond: vessel routes to the predicted oil patches, with fleet totals.

Routes, vessels and targets are shared/schemas.py dataclasses (VesselRoute, Vessel,
ResponseTarget); units and status wording come from components.labels.
"""

from __future__ import annotations

import folium
import pandas as pd
import streamlit as st

import config
from components import maps, ui
from components.data import drift_stage, routing_stage
from components.labels import HOURS, KM, M3, M_PER_S, STATUS_LABELS

stage = routing_stage()
data = stage.data
drift = drift_stage().data
ui.page_heading(
    "Step 03 · Respond",
    "Send the right vessels to the right place",
    "An optimiser assigns cleanup vessels to the predicted oil patches and plans their routes.",
    stage,
)


def step_label(hours: float) -> str:
    return "Now" if hours == 0 else f"+{hours:g} {HOURS}"


if data is None:
    ui.empty_state(
        "respond",
        "No response plan yet",
        "When a drift forecast is ready, vessels are matched to the predicted oil patches. This view then "
        "shows each vessel's route, the order of its stops, and how long the whole response takes.",
        ["Vessel routes", "Visiting order", "Fleet totals", "Estimated oil recovery"],
    )
else:
    if data.status:
        css, label = STATUS_LABELS[data.status]
        st.html(f'<span class="gog-chip {css}"><span class="gog-dot"></span>{label}</span>')

    target_oil = data.target_oil_m3
    ui.stat_tiles([
        ("Vessels deployed", ui.fmt(float(len(data.routes)), 0) if data.routes else None, "",
         "Vessels with an assigned route"),
        ("Response time", ui.fmt(data.response_time_hours), HOURS, "Until the last vessel completes its route"),
        ("Distance sailed", ui.fmt(data.total_distance_km), KM, "All vessels combined"),
        ("Estimated oil recovery", ui.fmt(data.oil_collected_m3, 0), M3,
         f"Of about {target_oil:,.0f} {M3} in the oil patches" if target_oil else "Estimated volume collected"),
    ])

    # --- Map ---------------------------------------------------------------------
    ui.section("Response plan", "Each line is one vessel, from its base to the oil patches it collects.")
    m = maps.base_map()
    fit: list[dict] = []
    legend: list[tuple[str, str, str]] = []

    if drift and drift.steps:
        hours = drift.hours
        preferred = (data.target_source_hours, 12, 24, 6)
        default = next((h for h in preferred if h in hours), hours[-1])
        shown = st.segmented_control("Predicted oil shown", hours, default=default, required=True,
                                     format_func=step_label, key="respond_step")
        oil = folium.FeatureGroup(name="Predicted oil")
        maps.add_features(oil, drift.steps[shown], config.oil_color_for_hour(shown), fill_opacity=0.3,
                          weight=1, point_radius=2)
        oil.add_to(m)
        fit += drift.steps[shown]
        legend.append((config.oil_color_for_hour(shown), f"Predicted oil ({step_label(shown).lower()})", "fill"))

    if data.targets:
        group = folium.FeatureGroup(name="Oil patches")
        for target in data.targets:
            point = (target.location.latitude, target.location.longitude)
            folium.CircleMarker(point, radius=7, color="#061521", weight=2, fill=True, fill_color=config.AMBER,
                                fill_opacity=1, tooltip=f"{target.target_id} · {target.oil_volume_m3:,.0f} {M3}"
                                ).add_to(group)
            fit.append({"geometry": {"type": "Point", "coordinates": [point[1], point[0]]}})
        group.add_to(m)
        legend.append((config.AMBER, "Oil patch to collect", "dot"))

    for i, entry in enumerate(data.routes):
        route = entry.route
        color = config.vessel_color(i)
        latlon = [(c.latitude, c.longitude) for c in route.coordinates]
        group = folium.FeatureGroup(name=route.vessel_id)
        folium.PolyLine(latlon, color=color, weight=6, opacity=0.18).add_to(group)  # soft glow
        folium.PolyLine(latlon, color=color, weight=2.5, opacity=0.95,
                        tooltip=f"{route.vessel_id}: {' → '.join(route.assigned_target_ids) or 'route'}"
                        ).add_to(group)
        folium.CircleMarker(latlon[0], radius=6, color=color, weight=2, fill=True, fill_color="#061521",
                            fill_opacity=1, tooltip=f"{route.vessel_id} base").add_to(group)
        for stop, point in enumerate(latlon[1:], start=1):
            folium.CircleMarker(point, radius=3.5, color=color, weight=0, fill=True, fill_opacity=1,
                                tooltip=f"{route.vessel_id} · stop {stop}").add_to(group)
        group.add_to(m)
        fit.append({"geometry": {"type": "LineString", "coordinates": [[lon, lat] for lat, lon in latlon]}})
        legend.append((color, route.vessel_id, "line"))

    maps.render(m, fit, key="cleanup_map", height=560)
    ui.legend(legend)

    # --- Table -------------------------------------------------------------------
    ui.section("Vessel assignments")
    if data.routes:
        columns = {
            "distance": f"Distance ({KM})",
            "time": f"Time to finish ({HOURS})",
            "speed": f"Speed ({M_PER_S})",
            "capacity": f"Capacity ({M3})",
            "oil": f"Estimated oil recovery ({M3})",
        }
        table = pd.DataFrame([{
            "Vessel": e.route.vessel_id,
            "Visiting order": " → ".join(e.route.assigned_target_ids) or "—",
            "Stops": len(e.route.assigned_target_ids),
            columns["distance"]: e.route.estimated_distance_km,
            columns["time"]: e.route.estimated_travel_hours,
            columns["speed"]: e.vessel.speed_m_per_s if e.vessel else None,
            columns["capacity"]: e.vessel.capacity_m3 if e.vessel else None,
            columns["oil"]: e.oil_collected_m3,
        } for e in data.routes])
        st.dataframe(table, hide_index=True, width="stretch", alt="Vessel assignments", column_config={
            columns["distance"]: st.column_config.NumberColumn(format="%.1f"),
            columns["time"]: st.column_config.NumberColumn(format="%.1f", help="From dispatch to the last stop"),
            columns["speed"]: st.column_config.NumberColumn(format="%.1f"),
            columns["capacity"]: st.column_config.NumberColumn(format="%.0f"),
            columns["oil"]: st.column_config.NumberColumn(format="%.0f"),
        })
    else:
        ui.inline_empty("Individual vessel routes will appear here.")

    with st.expander("How to read this", icon=":material/help:"):
        st.markdown(
            """
- Lines join each vessel's base to its oil patches in visiting order. They are **straight lines**, not checked navigation routes (shallow water, islands and traffic are not considered).
- Oil patches come from the drift forecast, so routes inherit its uncertainty, and the oil keeps moving while vessels travel.
- *Estimated oil recovery* depends on assumed recovery rates and patch volumes, and never exceeds a vessel's capacity.
- A *feasible* plan is valid but not necessarily the best possible; *optimal* means the optimiser proved it is the best.
"""
        )
