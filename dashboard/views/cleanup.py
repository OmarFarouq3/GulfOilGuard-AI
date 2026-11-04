"""Respond: vessel routes to the predicted oil patches, with fleet totals.

Routes, vessels and targets are shared/schemas.py dataclasses (VesselRoute, Vessel,
ResponseTarget); units and status wording come from components.labels. For a site in the
per-site layout (outputs/sites/<id>/routing/) the page also shows what the routing team's files
provide: sea paths, unserved patches, the plan's assumptions, the nearest-target baseline
(comparison.json, baseline/) and the team's own warnings (validation.json).
"""

from __future__ import annotations

import re

import folium
import pandas as pd
import streamlit as st

import config
from components import flow, maps, ui
from components.data import demo_mode, drift_stage, routing_stage, selected_site
from components.labels import (COMPARE_RESPONSE_ROW, COMPARE_SAILING_ROW, FALLBACK_CAPTION, FINISH_HELP, HOURS, KM, M3,
                               M_PER_S, RESPONSE_CAPTION, SAILING_HELP, SAILING_HINT, STATUS_LABELS,
                               response_time_tile)
from services import scenario
from services.drift_loader import afloat
from services.files import display_text

stage = routing_stage()
data = stage.data
drift = drift_stage().data
ui.page_heading(
    "Step 03 · Respond",
    "Send the right vessels to the right place",
    "An optimiser assigns cleanup vessels to the predicted oil patches and plans their routes.",
    stage,
)
site = selected_site()
if site:
    flow.respond_controls(site)
else:
    flow.no_selection_prompt()

# What the optimiser aims for, in this order (optimization/routing_model.py, weights in optimization/config.py;
# the moving-oil re-planning keeps the best sailed round by the same order, optimization/moving_targets.py).
OBJECTIVE = ("The optimiser does not aim for the shortest total distance. In order, it aims to recover the most oil "
             "(leaving a patch unserved costs far more than any detour), then to get the last vessel back to port, "
             "cleanup included, as early as possible (one hour earlier is worth 100 km of extra sailing, an "
             "assumption), and only then to sail the fewest kilometres. So it may sail further than the baseline to "
             "finish sooner.")
STEP_KEY = "respond_step"
SAVED_STEP_KEY = "respond_step_saved"  # (anchored_to, hours): not a widget key, survives leaving the page
UNSERVED_COLOR = "#f87171"
BASELINE_COLOR = "#8fa9b8"


def step_label(hours: float) -> str:
    return "Now" if hours == 0 else f"+{hours:g} {HOURS}"


def oil_step(hours: list[float], default: float) -> float:
    """Forecast step for the oil layer: a slider over every step plus the key times (as on Predict).

    The step is kept per site when the user leaves the page and comes back.
    """
    owner = drift.anchored_to if drift else None
    if st.session_state.get(STEP_KEY) not in hours:
        saved = st.session_state.get(SAVED_STEP_KEY)
        st.session_state[STEP_KEY] = saved[1] if saved and saved[0] == owner and saved[1] in hours else default
    key_hours = [h for h in config.DRIFT_KEY_HOURS if h in hours]
    if key_hours and len(hours) > len(key_hours):
        with st.container(horizontal=True, key="gog-respond-jump"):
            for h in key_hours:
                st.button(step_label(h), key=f"respond_jump_{h:g}", type="tertiary",
                          on_click=st.session_state.__setitem__, args=(STEP_KEY, h))
    shown = st.select_slider("Predicted oil shown", options=hours, format_func=step_label, key=STEP_KEY,
                             help="Steps through the saved forecast; the plan is not re-optimised.")
    st.session_state[SAVED_STEP_KEY] = (owner, shown)
    return shown


def route_line(entry, paths: dict) -> list[tuple[float, float]]:
    """The water path the routing team drew around land, else the straight stops (lat, lon)."""
    return paths.get(entry.route.vessel_id) or [(c.latitude, c.longitude) for c in entry.route.coordinates]


def stops(entry) -> list[tuple[float, float]]:
    """Stops after the base; a final return to the base is the trip home, not another stop."""
    points = [(c.latitude, c.longitude) for c in entry.route.coordinates]
    return points[1:-1] if len(points) > 1 and points[-1] == points[0] else points[1:]


def unserved_reasons(message: str | None) -> str | None:
    """The plan's own words after 'unserved:' in its message, if it gives them."""
    found = re.search(r"unserved: (.+?)(?:; |$)", message or "")
    return display_text(found.group(1)) if found else None


if data is None:
    if site is None:
        ui.empty_state(
            "respond",
            "No response plan yet",
            "When a drift forecast is ready, vessels are matched to the predicted oil patches. This view then "
            "shows each vessel's route, the order of its stops, and how long the whole response takes.",
            ["Vessel routes", "Visiting order", "Fleet totals", "Estimated oil recovery"],
        )
else:
    flow.precomputed_plan_note(data, drift)
    site_plan = bool(site and data.anchored_to == site.spill_id and scenario.sites_mode(demo_mode()))
    comparison, baseline, _warnings = scenario.site_comparison(site) if site_plan else (None, None, [])  # Diagnostics
    if data.status:
        css, label = STATUS_LABELS[data.status]
        st.html(f'<span class="gog-chip {css}"><span class="gog-dot"></span>{label}</span>')
    if site_plan:
        dispatch = comparison.get("dispatch_hours") if comparison else None
        when = (f" (+{dispatch:g} {HOURS} after the release" + (f", {comparison['dispatch_time'][:16].replace('T', ' ')} UTC"
                if comparison.get("dispatch_time") else "") + ")") if dispatch is not None else ""
        fleet = (f" (fleet file {display_text(comparison['fleet'])}.json)"
                 if comparison and comparison.get("fleet") else "")
        st.caption(f"Assumptions, not observations: the vessels and their start positions, taken as home "
                   f"ports{fleet}, and the dispatch time{when}.")

    target_oil = data.target_oil_m3
    response_label, response_hours, response_hint = response_time_tile(data)
    completion = data.completion_hours is not None
    ui.stat_tiles([
        ("Vessels deployed", ui.fmt(float(len(data.routes)), 0) if data.routes else None, "",
         "Vessels with an assigned route"),
        (response_label, ui.fmt(response_hours), HOURS, response_hint),
        *([("Sailing time", ui.fmt(data.sailing_time_hours), HOURS, SAILING_HINT)]
          if completion else []),
        ("Distance sailed", ui.fmt(data.total_distance_km), KM, "All vessels combined"),
        ("Estimated oil recovery", ui.fmt(data.oil_collected_m3, 0), M3,
         f"Of about {target_oil:,.0f} {M3} in the oil patches" if target_oil else "Estimated volume collected"),
    ])
    st.caption(RESPONSE_CAPTION if completion else FALLBACK_CAPTION)

    unserved = [t for t in data.targets if t.target_id in data.unserved_target_ids]
    if data.unserved_target_ids:  # every id summary.json lists, with its volume when targets.geojson has it
        reasons = unserved_reasons(data.message)
        volumes = {t.target_id: t.oil_volume_m3 for t in data.targets}
        listed = ", ".join(f"{t} ({volumes[t]:,.1f} {M3})" if t in volumes else t for t in data.unserved_target_ids)
        count = len(data.unserved_target_ids)
        total = len(set(volumes) | set(data.unserved_target_ids)) if data.targets else 0  # every patch the plan names
        share = f"{count} of {total} oil patches" if total else f"{count} oil patch{'es' if count != 1 else ''}"
        st.html(f'<div class="gog-notice">Not served: {share}: {ui.esc(listed)}.'
                + (f" The plan says: {ui.esc(reasons)}." if reasons else "") + "</div>")

    # --- Map ---------------------------------------------------------------------
    paths = data.route_paths
    ui.section("Response plan", "Each line is one vessel, from its base to the oil patches it collects and back"
               + (", following sea paths around land." if paths else "."))
    meets = {t: i["meet_hours"] for t, i in data.target_info.items() if "meet_hours" in i}
    if site_plan and meets and comparison and comparison.get("dispatch_hours") is not None:
        layer = f" The map opens at {step_label(data.target_source_hours)}: the forecast step closest to the average " \
                "meeting time, the oil layer the plan files point to." if data.target_source_hours is not None else ""
        st.caption(f"The oil patches were cut from the oil afloat at the {step_label(comparison['dispatch_hours'])} "
                   "dispatch. Each patch marker sits where its vessel meets it (the hour is in its tooltip); a patch "
                   f"nobody serves stays where it was at dispatch.{layer}")
    show_baseline = bool(baseline and baseline.routes) and st.toggle(
        "Show the nearest-target baseline routes", value=False,
        help="The simple comparison plan: every vessel takes the nearest open patch next, under the same rules.")
    m = maps.base_map()
    fit: list[dict] = []
    legend: list[tuple[str, str, str]] = []

    if drift and drift.steps:
        hours = drift.hours
        preferred = (data.target_source_hours, 12, 24, 6)
        shown = oil_step(hours, next((h for h in preferred if h in hours), hours[-1]))
        oil = folium.FeatureGroup(name="Predicted oil")
        maps.add_features(oil, [f for f in drift.steps[shown] if afloat(f)], config.oil_color_for_hour(shown),
                          fill_opacity=0.3, weight=1, point_radius=2)
        oil.add_to(m)
        legend.append((config.oil_color_for_hour(shown), f"Predicted oil afloat ({step_label(shown).lower()})", "fill"))

    if data.targets:
        group = folium.FeatureGroup(name="Oil patches")
        for target in data.targets:
            point = (target.location.latitude, target.location.longitude)
            info = data.target_info.get(target.target_id, {})
            text = f"{target.target_id} · {target.oil_volume_m3:,.1f} {M3}"
            if target.target_id in data.unserved_target_ids:
                where = f" (as at {step_label(info['position_hours'])})" if "position_hours" in info else ""
                folium.CircleMarker(point, radius=8, color=UNSERVED_COLOR, weight=2.5, fill=False,
                                    tooltip=f"{text} · not served{where}").add_to(group)
            else:
                met = f" · met at {step_label(info['meet_hours'])}" if "meet_hours" in info else ""
                by = f" by {info['served_by']}" if info.get("served_by") else ""
                folium.CircleMarker(point, radius=7, color="#061521", weight=2, fill=True, fill_color=config.AMBER,
                                    fill_opacity=1, tooltip=f"{text}{met}{by}").add_to(group)
            fit.append({"geometry": {"type": "Point", "coordinates": [point[1], point[0]]}})
        group.add_to(m)
        legend.append((config.AMBER, "Oil patch, where the vessel meets it" if meets else "Oil patch to collect", "dot"))
        if unserved:
            legend.append((UNSERVED_COLOR, "Oil patch not served", "dot"))

    for i, entry in enumerate(data.routes):
        route = entry.route
        color = config.vessel_color(i)
        line = route_line(entry, paths)
        group = folium.FeatureGroup(name=route.vessel_id)
        folium.PolyLine(line, color=color, weight=6, opacity=0.18).add_to(group)  # soft glow
        folium.PolyLine(line, color=color, weight=2.5, opacity=0.95,
                        tooltip=f"{route.vessel_id}: {' → '.join(route.assigned_target_ids) or 'route'}"
                        ).add_to(group)
        base = (route.coordinates[0].latitude, route.coordinates[0].longitude)
        folium.CircleMarker(base, radius=6, color=color, weight=2, fill=True, fill_color="#061521",
                            fill_opacity=1, tooltip=f"{route.vessel_id} base").add_to(group)
        for stop, point in enumerate(stops(entry), start=1):
            folium.CircleMarker(point, radius=3.5, color=color, weight=0, fill=True, fill_opacity=1,
                                tooltip=f"{route.vessel_id} · stop {stop}").add_to(group)
        group.add_to(m)
        fit.append({"geometry": {"type": "LineString", "coordinates": [[lon, lat] for lat, lon in line]}})
        legend.append((color, route.vessel_id, "line"))

    if show_baseline:
        group = folium.FeatureGroup(name="Nearest-target baseline")
        for entry in baseline.routes:
            line = route_line(entry, baseline.route_paths)
            folium.PolyLine(line, color=BASELINE_COLOR, weight=2, opacity=0.9, dash_array="6 6",
                            tooltip=f"Baseline {entry.route.vessel_id}: {' → '.join(entry.route.assigned_target_ids)}"
                            ).add_to(group)
            fit.append({"geometry": {"type": "LineString", "coordinates": [[lon, lat] for lat, lon in line]}})
        group.add_to(m)
        legend.append((BASELINE_COLOR, "Nearest-target baseline", "dash"))

    # Fit to the routes and patches (not the whole oil layer), so stops and patches can be told apart.
    if not fit and drift:
        fit = [f for h in drift.hours for f in drift.steps[h]]
    maps.render(m, fit, key="cleanup_map", height=560)
    ui.legend(legend)

    # --- Table -------------------------------------------------------------------
    ui.section("Vessel assignments")
    if data.routes:
        columns = {
            "distance": f"Distance ({KM})",
            "finish": f"Time to finish ({HOURS})",
            "time": f"Sailing ({HOURS})",
            "speed": f"Speed ({M_PER_S})",
            "capacity": f"Capacity ({M3})",
            "oil": f"Oil ({M3})",
        }
        table = pd.DataFrame([{
            "Vessel": e.route.vessel_id,
            "Visiting order": " → ".join(e.route.assigned_target_ids) or "—",
            "Stops": len(e.route.assigned_target_ids),
            columns["distance"]: e.route.estimated_distance_km,
            columns["finish"]: e.finish_hours,
            columns["time"]: e.route.estimated_travel_hours,
            columns["speed"]: e.vessel.speed_m_per_s if e.vessel else None,
            columns["capacity"]: e.vessel.capacity_m3 if e.vessel else None,
            columns["oil"]: e.oil_collected_m3,
        } for e in data.routes])
        # Pixel widths sized to the headers and the real vessel ids (HAMRIYAH-OSRV-RESERVE), so all nine fit at 1,150 px.
        st.dataframe(table, hide_index=True, width="stretch", alt="Vessel assignments", column_config={
            "Vessel": st.column_config.TextColumn(width=200),
            "Visiting order": st.column_config.TextColumn(width=210),
            "Stops": st.column_config.NumberColumn(width=55),
            columns["distance"]: st.column_config.NumberColumn(format="%.1f", width=105),
            columns["finish"]: st.column_config.NumberColumn(
                format="%.1f", width=130, help=FINISH_HELP),
            columns["time"]: st.column_config.NumberColumn(
                format="%.1f", width=95, help=SAILING_HELP),
            columns["speed"]: st.column_config.NumberColumn(format="%.1f", width=95),
            columns["capacity"]: st.column_config.NumberColumn(format="%.0f", width=105),
            columns["oil"]: st.column_config.NumberColumn(format="%.0f", width=80,
                                                          help="Estimated oil recovered by this vessel, in m³"),
        })
        if data.idle_vessel_ids:
            st.caption(f"Not deployed: {', '.join(data.idle_vessel_ids)}.")
    else:
        ui.inline_empty("Individual vessel routes will appear here.")

    # --- Optimised vs baseline ---------------------------------------------------------
    metrics = comparison.get("metrics") if comparison else None
    if metrics:
        ui.section("Optimised plan vs nearest-target baseline",
                   "The same vessels, oil and rules; the baseline sends each vessel to the nearest open patch next.")

        def pair(key: str, digits: int = 1) -> tuple[str, str]:
            return tuple(ui.fmt(metrics.get(f"{plan}_{key}"), digits) or "—" for plan in ("optimized", "baseline"))

        total = metrics.get("total_oil_m3")
        share = {plan: f"{metrics[f'{plan}_oil_recovered_m3'] / total:.0%}"
                 for plan in ("optimized", "baseline") if total and f"{plan}_oil_recovered_m3" in metrics}
        rows = [
            (f"{COMPARE_RESPONSE_ROW} ({HOURS})", *pair("response_hours", 2)),
            ("Patches served", *pair("targets_covered", 0)),
            (f"Oil recovered ({M3})", *pair("oil_recovered_m3", 0)),
            ("Oil recovered, share of the targeted oil", share.get("optimized", "—"), share.get("baseline", "—")),
            (f"{COMPARE_SAILING_ROW} ({HOURS})", *pair("longest_route_hours", 2)),
            (f"Distance sailed ({KM})", *pair("distance_km")),
        ]
        ui.table(["", "Optimised", "Baseline"], rows, numeric=(1, 2), key="gog-compare")
        st.caption(OBJECTIVE)
        st.caption(f"Shares are of the oil in the targeted patches ({total:,.0f} {M3}), which were cut from all the oil "
                   "still afloat at dispatch; they are not shares of the oil spilled." if total else
                   "Shares are of the oil in the targeted patches, not of the oil spilled.")
        assignments = comparison.get("assignments") or {}
        if assignments:
            by_plan = {"optimized": {e.route.vessel_id: e for e in data.routes},
                       "baseline": {e.route.vessel_id: e for e in baseline.routes} if baseline else {}}
            vessels = sorted({v for plan in assignments.values() for v in plan})
            per_vessel = []
            for vessel in vessels:
                row = [vessel]
                for plan in ("optimized", "baseline"):
                    entry = by_plan[plan].get(vessel)
                    row += [" → ".join(assignments.get(plan, {}).get(vessel, [])) or "—",
                            ui.fmt(entry.route.estimated_distance_km) if entry else "—"]
                per_vessel.append(row)
            ui.table(["Vessel", "Optimised", f"Optimised ({KM})", "Baseline", f"Baseline ({KM})"], per_vessel,
                     numeric=(2, 4), key="gog-compare-vessels", scroll_hint=True)

    # --- What the files say about themselves --------------------------------------------
    if data.message:
        with st.expander("Plan assumptions", icon=":material/rule:"):
            st.markdown("\n".join(f"- {display_text(part.strip())}" for part in data.message.split("; ")
                                   if part.strip()))
    warnings = scenario.site_validation_warnings(site) if site_plan else []
    if warnings:
        with st.expander("Warnings from the plan's own checks", icon=":material/warning:"):
            st.caption("As written in the site's validation report.")
            st.markdown("\n".join(f"- {display_text(w)}" for w in warnings))  # st.markdown renders no HTML

    with st.expander("How to read this", icon=":material/help:"):
        st.markdown(
            f"""
- Lines join each vessel's base to its oil patches in visiting order and back. {"They follow sea paths around land on an approximate grid, not checked navigation routes." if paths else "They are **straight lines**, not checked navigation routes (shallow water, islands and traffic are not considered)."}
- Oil patches come from the drift forecast, so routes inherit its uncertainty, and the oil keeps moving while vessels travel.
- *Estimated oil recovery* depends on assumed recovery rates and patch volumes, and never exceeds a vessel's capacity.
- A *feasible* plan is valid but not necessarily the best possible; *optimal* means the optimiser proved it is the best.
"""
        )
