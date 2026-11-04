"""Overview: hero, headline KPIs, the response flow and how far results can be trusted."""

from __future__ import annotations

import streamlit as st

from components import illustrations, incident, ui
from components.data import (all_stages, combined_status, demo_mode, detection_located, release_point,
                             selected_site, spills_stage)
from components.labels import HOURS, KM2, response_time_tile
from services import scenario
from services.files import as_float
from services.geo import polygon_area_km2

stages = all_stages()
sites = scenario.sites_mode(demo_mode())
detect, predict, respond = stages["detect"].data, stages["predict"].data, stages["respond"].data

# The headline numbers mix all three stages: simulated if any input behind them is.
results_status = combined_status(stages)
hero_chip = ui.chip("simulated") if demo_mode() or results_status == "simulated" else ""
st.html(
    f"""<section class="gog-hero">
          <div class="gog-hero-eyebrow">AI for Impact · Arabian Gulf</div>
          <h1>GulfOilGuard<span>-AI</span></h1>
          <p>From satellite radar to a cleanup plan: detect oil spills at sea, predict where they will
             drift, and send response vessels where they matter most.</p>
          <div class="gog-hero-chips">{hero_chip}</div>
          {illustrations.img(illustrations.HERO_WAVES, "gog-hero-waves")}
        </section>"""
)

# --- Headline KPIs ---------------------------------------------------------------
slick_area = None
if detect and detect.spill:
    props = [f["properties"].get("area_km2") for f in detect.spill["features"]]
    given = [as_float(p) for p in props]
    slick_area = sum(given) if all(v is not None for v in given) else polygon_area_km2(detect.spill["features"])

# In the per-site layout the detected slick is only the demo outline placed at the site (the radar
# images are not georeferenced), so its area is the same for every site. Show the site's own oil
# footprint at release (its forecast's first step) instead, labelled as what it is.
release_area = None
if sites and predict and predict.steps:
    release_area = polygon_area_km2(predict.steps[min(predict.hours)]) or None

spread_24 = None
if predict and predict.steps:
    last = 24 if 24 in predict.steps else max(predict.hours)
    area = polygon_area_km2(predict.steps[last])
    spread_24 = area or None

vessels = float(len(respond.routes)) if respond and respond.routes else None
response_label, response_time, response_hint = response_time_tile(respond)

if results_status == "simulated":
    st.html(f'<div class="gog-kpi-status">{ui.chip("simulated")}'
            "<span>These numbers come from a simulated scenario, not from observations.</span></div>")
if sites:  # one set of results per site: say which one these numbers are for
    site = selected_site()
    scope = (f"These numbers are for site {site.spill_id} ({ui.coordinates(site.location.latitude, site.location.longitude)}); "
             "they fill in as you run its steps." if site else
             "Each site has its own forecast and plan: pick a site on the map or in the list below it to see its numbers.")
    st.html(f'<p class="gog-flow-note gog-kpi-scope">{ui.esc(scope)}</p>')
ui.stat_tiles([
    ("Release footprint, simulated", ui.fmt(release_area), KM2,
     "Oil footprint at release in this site's forecast; a test release, not a detected slick") if sites else
    ("Slick detected", ui.fmt(slick_area), KM2, "Area of oil found in the latest scene"),
    (f"Spread at 24 {HOURS}", ui.fmt(spread_24), KM2, "Predicted oil footprint one day later"),
    ("Vessels deployed", ui.fmt(vessels, 0), "", "Response vessels with an assigned route"),
    (response_label, ui.fmt(response_time), HOURS, response_hint),
])

# --- Choose an incident ----------------------------------------------------------
# Without spill.geojson the radar scene has no location: Detect and Predict are not the same incident yet.
located = detection_located()
if located:
    ui.section("Choose an incident", "Click a spill on the map (or choose it in the list below the map), then "
               "follow it through the three stages.")
else:
    ui.section("Choose an incident", "Click a spill on the map (or choose it in the list below the map), then "
               "follow it through the three stages. Its forecast "
               "and response plan start from a synthetic release point there; the radar image assigned to it is a "
               "sample from the dataset, not taken at that point.")
incident.picker(spills_stage())

# --- Response flow ---------------------------------------------------------------
if located:
    ui.section("Incident response flow", "Follow one incident through the three stages of the response.")
else:
    release = release_point()
    where = f" at {ui.coordinates(*release)}" if release else ""
    ui.section("Response flow", "Not one incident yet: the radar scene on Detect has no location (no georeferenced "
               f"slick), and the forecast on Predict starts from a synthetic release point{where}, not from that scene.")

FLOW = (
    ("detect", "views/detection.py", "01", "Detect",
     "A deep-learning model scans SAR (radar) imagery and outlines dark oil slicks on the sea surface."),
    ("predict", "views/drift.py", "02", "Predict",
     "Winds and ocean currents drive a drift simulation that forecasts where the oil goes over 24 hours." if located
     else "Winds and ocean currents drive a drift simulation that forecasts where oil released at a synthetic "
          "point goes over 24 hours."),
    ("respond", "views/cleanup.py", "03", "Respond",
     "An optimiser assigns vessels to the predicted oil patches and plans the fastest collection routes."),
)
# Only Detect computes anything live (the U-Net, in a subprocess); Predict and Respond read saved files.
PRECOMPUTED = ("Predict and Respond show precomputed results from saved drift runs and routing plans; nothing "
               "is re-simulated or re-optimised in the dashboard. Detect can run the "
               "detection model on the selected image.")
for column, (key, page, number, verb, text) in zip(st.columns(3), FLOW):
    with column.container(key=f"gog-stage-{key}", height="stretch"):
        st.html(
            f"""<div class="gog-stage-num">STEP {number}</div>
                <h4>{verb}</h4><p>{text}</p>{ui.chip(stages[key].status)}"""
        )
        st.page_link(page, label=f"Open {verb.lower()}", icon=":material/arrow_forward:",
                     icon_position="right")
st.caption(PRECOMPUTED)

# --- Reliability -----------------------------------------------------------------
ui.section(
    "How far can you trust this?",
    "Each stage feeds the next, so uncertainty compounds along the chain.",
)
CHAIN = (
    ("Detection", "Calm water, algae and rain cells can look like oil; thin slicks can be missed.", 25, "Low"),
    ("Geolocation", "Pixels become coordinates using the scene's geometry. Errors shift the whole slick.", 45,
     "Moderate"),
    ("Drift", "Depends on wind and current data and the oil type. Uncertainty grows with every hour.", 70,
     "Higher"),
    ("Response", "Routes to predicted patches are approximate, not checked navigation; real navigation needs local checks.", 90,
     "Highest"),
)
steps = "".join(
    f"""<div class="gog-chain-step"><b>{name}</b><p>{text}</p>
          <div class="gog-chain-bar"><span style="width:{width}%"></span></div>
          <div class="gog-chain-label">Cumulative uncertainty: {level}</div></div>"""
    for name, text, width, level in CHAIN
)
st.html(f'<div class="gog-chain">{steps}</div>')
st.caption("Uncertainty levels are qualitative. GulfOilGuard-AI is a research prototype for decision support, "
           "not an operational response system.")
