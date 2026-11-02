"""Predict: forecast oil positions at 6/12/24 h, plus the wind and current behind them.

The centre path uses the shared DriftOutput trajectory (TimedPosition, UTC) when the drift
module provides one, otherwise the centroid of each forecast step.
"""

from __future__ import annotations

import folium
import streamlit as st

import config
from components import maps, ui
from components.data import drift_stage
from components.labels import HOURS, KM, KM2, M_PER_S
from services import schema
from services.files import as_float, iter_positions
from services.geo import centroid, haversine_km, polygon_area_km2

stage = drift_stage()
data = stage.data
ui.page_heading(
    "Step 02 · Predict",
    "Forecast where the oil will go",
    "Winds and ocean currents drive a drift simulation of the slick over the next 24 hours.",
    stage,
)


def step_label(hours: float) -> str:
    return "Now" if hours == 0 else f"+{hours:g} {HOURS}"


def valid_at(timestamp: str) -> str:
    """UTC ISO 8601 -> '14 Mar 12:42' (loaders already rejected invalid timestamps)."""
    return schema.utc(timestamp).strftime("%d %b %H:%M")


def degrees(value: object) -> str | None:
    number = as_float(value)
    return None if number is None else f"{number:.0f}°"


def trajectory_point(hours: float) -> tuple[float, float] | None:
    """(lat, lon) of the DriftOutput position `hours` after its first position, if provided."""
    if not (data.trajectory and data.trajectory.positions):
        return None
    start = data.trajectory.positions[0].timestamp
    for position in data.trajectory.positions:
        if abs((position.timestamp - start).total_seconds() / 3600 - hours) < 0.05:
            return position.coordinate.latitude, position.coordinate.longitude
    return None


def step_center(features: list[dict]) -> tuple[float, float] | None:
    """Mean centroid (lat, lon) of all features in one step."""
    points = [c for f in features if (c := centroid(f))]
    if not points:
        return None
    return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)


if data is None:
    ui.empty_state(
        "predict",
        "No active scenario yet",
        "Once a drift simulation is available, this view will show how the oil slick is expected to move and spread over time, "
        "based on wind and ocean-current data.",    #Edit 3: Entire text swapped
        ["Drift at 6, 12 and 24 h", "Oil footprint over time", "Wind and current inputs"],
    )
else:
    hours = data.hours
    default = next((h for h in config.DRIFT_HORIZONS_HOURS if h in hours), hours[0])
    selected = st.segmented_control("Forecast time", hours, default=default, required=True,
                                    format_func=step_label, key="drift_step")

    features = data.steps[selected]
    start = trajectory_point(hours[0]) or step_center(data.steps[hours[0]])
    here = trajectory_point(selected) or step_center(features)
    distance = haversine_km(start[1], start[0], here[1], here[0]) if start and here and selected != hours[0] else None
    area = polygon_area_km2(features) or None
    particles = sum(len(list(iter_positions(f["geometry"]["coordinates"])))
                    for f in features if f["geometry"]["type"] in ("Point", "MultiPoint"))
    timestamps = sorted({str(f["properties"]["timestamp"]) for f in features if f["properties"].get("timestamp")})
    ui.stat_tiles([
        ("Drift distance", ui.fmt(distance), KM, f"Centre of the slick, {step_label(hours[0]).lower()} → {step_label(selected)}"),
        ("Oil footprint", ui.fmt(area), KM2, "Area covered by the predicted oil"),
        ("Simulated particles", ui.fmt(float(particles), 0) if particles else None, "", "Oil parcels tracked by the model"),
        ("Valid at", valid_at(timestamps[0]) if timestamps else None, "UTC", "Time this forecast step applies to"),
    ])

    show_trail = st.toggle("Show earlier steps", value=True)
    m = maps.base_map()
    centers = []
    for h in hours:
        if h > selected:
            break
        center = trajectory_point(h) or step_center(data.steps[h])
        if center:
            centers.append(center)
        if h != selected and show_trail:
            group = folium.FeatureGroup(name=step_label(h))
            maps.add_features(group, data.steps[h], config.oil_color_for_hour(h), fill_opacity=0.15,
                              weight=1, point_radius=2)
            group.add_to(m)
    if len(centers) > 1:
        folium.PolyLine(centers, color="#e2eef3", weight=2, opacity=0.7, dash_array="6 6",
                        tooltip="Path of the slick's centre").add_to(m)
    current = folium.FeatureGroup(name=step_label(selected))
    maps.add_features(current, features, config.oil_color_for_hour(selected), fill_opacity=0.45,
                      tooltip={"hours": "Hours after detection", "timestamp": "Valid at"})
    current.add_to(m)
    maps.render(m, [f for h in hours for f in data.steps[h]], key="drift_map", height=560)
    ui.legend(
        [(config.oil_color_for_hour(h), step_label(h), "fill") for h in hours if h <= selected]
        + [("#e2eef3", "Path of the slick's centre", "dash")]
    )

    # --- Inputs ----------------------------------------------------------------
    ui.section("What drives the forecast", "Weather and ocean conditions used by the simulation.")
    meta = data.meta or {}
    if meta:
        ui.stat_tiles([
            ("Wind speed", ui.fmt(as_float(meta.get("wind_speed_m_per_s"))), M_PER_S, "Near-surface wind"),
            ("Wind from", degrees(meta.get("wind_from_deg")), "", "Direction the wind blows from"),
            ("Current speed", ui.fmt(as_float(meta.get("current_speed_m_per_s")), 2), M_PER_S,
             "Surface ocean current"),
            ("Current towards", degrees(meta.get("current_to_deg")), "", "Direction the water flows"),
        ])
        labels = {"model": "Drift model", "start_time": "Simulation start", "wind_source": "Wind data",
                  "current_source": "Current data", "oil_type": "Oil type", "n_particles": "Particles"}
        details = {labels[k]: valid_at(str(v)) + " UTC" if k == "start_time" else v
                   for k, v in meta.items() if k in labels}
        if data.trajectory:
            details["Simulation"] = data.trajectory.simulation_id
            details["Forecast length"] = f"{data.trajectory.duration_hours:g} {HOURS}"
        if details:
            st.html('<div style="height:.8rem"></div>')
            ui.details_table(details)
    else:
        ui.inline_empty("Wind and current conditions will appear here.")

    with st.expander("How to read this", icon=":material/help:"):
        st.markdown(
            """
- Each colour is one forecast time. Colours move from bright amber (now) to dark orange (24 h) as the forecast becomes less certain.
- **Dots** are simulated oil parcels; **shaded areas** outline where the oil is expected. Neither is an observation.
- Accuracy depends on the wind and current data and on the assumed oil type and release time.
- The starting position comes from the detection step, so any detection or location error carries through.
"""
        )
