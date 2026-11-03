"""Predict: forecast oil positions over time (key times 0/6/12/24 h), plus the wind and current behind them.

The centre path uses the shared DriftOutput trajectory (TimedPosition, UTC) when the drift
module provides one, otherwise the centroid of each forecast step.
"""

from __future__ import annotations

import folium
import streamlit as st

import config
from components import flow, maps, ui
from components.data import demo_mode, drift_stage, selected_site
from components.labels import HOURS, KM, KM2, M3, M_PER_S
from services import schema, selection
from services.drift_loader import afloat
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
site = selected_site()
if site:
    flow.predict_controls(site, demo_mode())
else:
    flow.no_selection_prompt()


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


STEP_KEY = "drift_step"
SAVED_STEP_KEY = "drift_step_saved"  # not a widget key: survives leaving the page
NOT_AFLOAT_COLOR = "#8fa9b8"  # muted slate: never an oil colour
NOT_AFLOAT_LABEL = "No longer afloat"
DETAIL_LABELS = {"model": "Drift model", "oil_type": "Oil type", "release_volume_m3": f"Oil released ({M3})",
                 "n_particles": "Particles", "wind_source": "Wind data", "current_source": "Current data"}
ASSUMPTION_LABELS = {"sea_water_temperature_c": "Water temperature (°C, assumed)",
                     "sea_water_salinity_psu": "Salinity (PSU, assumed)",
                     "horizontal_diffusivity_m2_per_s": "Horizontal diffusivity (m²/s, assumed)",
                     "vertical_mixing": "Vertical mixing", "release": "Release"}


def particle_count(features: list[dict]) -> int:
    return sum(len(list(iter_positions(f["geometry"]["coordinates"])))
               for f in features if f["geometry"]["type"] in ("Point", "MultiPoint"))


def run_details(meta: dict) -> dict[str, object]:
    """The run's metadata from meta.json, as written there (nothing derived or filled in)."""
    details: dict[str, object] = {}
    if data.trajectory:
        location = data.trajectory.initial_location
        details["Simulation"] = data.trajectory.simulation_id
        details["Release point"] = ui.coordinates(location.latitude, location.longitude)
    if "start_time" in meta:
        details["Release time"] = valid_at(str(meta["start_time"])) + " UTC"
    if data.trajectory:
        details["Forecast length"] = f"{data.trajectory.duration_hours:g} {HOURS}"
    details |= {label: meta[key] for key, label in DETAIL_LABELS.items() if meta.get(key) is not None}
    assumptions = meta.get("assumptions")
    if isinstance(assumptions, dict):
        for key, label in ASSUMPTION_LABELS.items():
            value = assumptions.get(key)
            if isinstance(value, bool):
                details[label] = "On" if value else "Off"
            elif value is not None and not isinstance(value, (dict, list)):
                details[label] = value
    return details


def step_center(features: list[dict]) -> tuple[float, float] | None:
    """Mean centroid (lat, lon) of all features in one step."""
    points = [c for f in features if (c := centroid(f))]
    if not points:
        return None
    return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)


if data is None:
    if site and selection.predict_done():
        flow.next_step("respond")  # no forecast to show: the link follows the note
    if site is None:
        ui.empty_state(
            "predict",
            "No active scenario yet",
            "Once a drift simulation is available, this view will show how the oil slick is expected to move and spread over time, "
            "based on wind and ocean-current data.",    #Edit 3: Entire text swapped
            ["Drift at 6, 12 and 24 h", "Oil footprint over time", "Wind and current inputs"],
        )
else:
    hours = data.hours
    # One forecast time at a time: a slider through every step (the real run has 25 hourly
    # steps), plus buttons for the key times. The selected step lives in session_state.
    # Streamlit forgets a widget's value when its page is left, so the step is also kept in
    # SAVED_STEP_KEY and restored when the user comes back.
    if st.session_state.get(STEP_KEY) not in hours:
        saved = st.session_state.get(SAVED_STEP_KEY)
        st.session_state[STEP_KEY] = saved if saved in hours else next(
            (h for h in config.DRIFT_HORIZONS_HOURS if h in hours), hours[0])
    key_hours = [h for h in config.DRIFT_KEY_HOURS if h in hours]
    if key_hours and len(hours) > len(key_hours):
        with st.container(horizontal=True, key="gog-drift-jump"):
            for h in key_hours:
                st.button(step_label(h), key=f"drift_jump_{h:g}", type="tertiary",
                          on_click=st.session_state.__setitem__, args=(STEP_KEY, h))
    selected = st.select_slider("Forecast time", options=hours, format_func=step_label, key=STEP_KEY)
    st.session_state[SAVED_STEP_KEY] = selected

    features = data.steps[selected]
    oil = [f for f in features if afloat(f)]  # oil still on the water
    gone = [f for f in features if not afloat(f)]  # stranded, evaporated, ... (OpenDrift status)
    start = trajectory_point(hours[0]) or step_center([f for f in data.steps[hours[0]] if afloat(f)])
    here = trajectory_point(selected) or step_center(oil)
    if selected == hours[0]:
        distance = 0.0 if start else None  # nothing has drifted yet
    else:
        distance = haversine_km(start[1], start[0], here[1], here[0]) if start and here else None
    area = polygon_area_km2(oil) or None
    particles, not_afloat = particle_count(oil), particle_count(gone)
    timestamps = sorted({str(f["properties"]["timestamp"]) for f in features if f["properties"].get("timestamp")})
    ui.stat_tiles([
        ("Drift distance", ui.fmt(distance), KM,
         "At the release point: no drift yet" if selected == hours[0]
         else f"Centre of the slick, {step_label(hours[0]).lower()} → {step_label(selected)}"),
        ("Oil footprint", ui.fmt(area), KM2, "Area covered by the predicted oil"),
        ("Particles afloat", ui.fmt(float(particles), 0) if particles else None, "",
         f"Oil parcels still on the water; {not_afloat:,} no longer afloat" if not_afloat
         else "Oil parcels still on the water"),
        ("Valid at", valid_at(timestamps[0]) if timestamps else None, "UTC", "Time this forecast step applies to"),
    ])

    show_trail = st.toggle("Show earlier steps", value=True, help="Earlier key times (0, 6, 12, 24 h) under the selected one.")
    # With many steps, the trail (and its legend) shows only the key times: 24 hourly layers of
    # 1,000 particles each would bury the selected step and slow the map down.
    trail_hours = [h for h in hours if h < selected and (h in config.DRIFT_KEY_HOURS or len(hours) <= len(key_hours))]
    m = maps.base_map()
    centers = []
    for h in hours:
        if h > selected:
            break
        center = trajectory_point(h) or step_center([f for f in data.steps[h] if afloat(f)])
        if center:
            centers.append(center)
        if h in trail_hours and show_trail:
            group = folium.FeatureGroup(name=step_label(h))
            maps.add_features(group, [f for f in data.steps[h] if afloat(f)], config.oil_color_for_hour(h),
                              fill_opacity=0.15, weight=1, point_radius=2)
            group.add_to(m)
    if len(centers) > 1:
        folium.PolyLine(centers, color="#e2eef3", weight=2, opacity=0.7, dash_array="6 6",
                        tooltip="Path of the slick's centre").add_to(m)
    if gone:
        not_oil = folium.FeatureGroup(name=NOT_AFLOAT_LABEL)
        maps.add_features(not_oil, gone, NOT_AFLOAT_COLOR, point_radius=2)
        not_oil.add_to(m)
    current = folium.FeatureGroup(name=step_label(selected))
    maps.add_features(current, oil, config.oil_color_for_hour(selected), fill_opacity=0.45,
                      tooltip={"hours": "Hours after release", "timestamp": "Valid at"})
    current.add_to(m)
    maps.render(m, [f for h in hours for f in data.steps[h]], key="drift_map", height=560)
    ui.legend(
        [(config.oil_color_for_hour(h), step_label(h), "fill") for h in [*trail_hours, selected]
         if h == selected or show_trail]
        + [("#e2eef3", "Path of the slick's centre", "dash")]
        + ([(NOT_AFLOAT_COLOR, NOT_AFLOAT_LABEL, "dot")] if gone else [])
    )
    if site and selection.predict_done():
        flow.next_step("respond")

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
        details = run_details(meta)
        if details:
            with st.expander("Run details", icon=":material/info:"):
                ui.details_table(details)
                if isinstance(meta.get("note"), str):
                    st.caption(meta["note"])
    else:
        ui.inline_empty("Wind and current conditions will appear here.")

    with st.expander("How to read this", icon=":material/help:"):
        st.markdown(
            """
- Each colour is one forecast time. Colours move from bright amber (now) to dark orange (24 h) as the forecast becomes less certain.
- **Dots** are oil parcels tracked by the drift model; **shaded areas** outline where the oil is expected. Neither is an observation. Grey dots are parcels no longer afloat (stranded, evaporated, ...).
- Accuracy depends on the wind and current data and on the assumed oil type and release time.
- The forecast starts at its release point (see Run details). While that point is a test input rather than a located detection, the forecast shows how oil released there would move, not where a detected slick will go.
"""
        )
