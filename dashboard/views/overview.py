"""Overview: hero, headline KPIs, the response flow and how far results can be trusted."""

from __future__ import annotations

import streamlit as st

from components import illustrations, ui
from components.data import all_stages, demo_mode
from services.files import as_float
from services.geo import polygon_area_km2

stages = all_stages()
detect, predict, respond = stages["detect"].data, stages["predict"].data, stages["respond"].data

hero_chip = ui.chip("simulated") if demo_mode() else ""
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

spread_24 = None
if predict and predict.steps:
    last = 24 if 24 in predict.steps else max(predict.hours)
    area = polygon_area_km2(predict.steps[last])
    spread_24 = area or None

vessels = float(len(respond.routes)) if respond and respond.routes else None
summary = respond.summary if respond and respond.summary else {}
response_time = as_float(summary.get("total_time_hours"))

ui.stat_tiles([
    ("Slick detected", ui.fmt(slick_area), "km²", "Area of oil found in the latest scene"),
    ("Spread at 24 h", ui.fmt(spread_24), "km²", "Predicted oil footprint one day later"),
    ("Vessels deployed", ui.fmt(vessels, 0), "", "Response vessels with an assigned route"),
    ("Response time", ui.fmt(response_time), "h", "Until the last vessel completes its route"),
])

# --- Response flow ---------------------------------------------------------------
ui.section("Incident response flow", "Follow one incident through the three stages of the response.")

FLOW = (
    ("detect", "views/detection.py", "01", "Detect",
     "A deep-learning model scans Sentinel-1 radar imagery and outlines dark oil slicks on the sea surface."),
    ("predict", "views/drift.py", "02", "Predict",
     "Winds and ocean currents drive a drift simulation that forecasts where the oil goes over 24 hours."),
    ("respond", "views/cleanup.py", "03", "Respond",
     "An optimiser assigns vessels to the predicted oil patches and plans the fastest collection routes."),
)
for column, (key, page, number, verb, text) in zip(st.columns(3), FLOW):
    with column.container(key=f"gog-stage-{key}", height="stretch"):
        st.html(
            f"""<div class="gog-stage-num">STEP {number}</div>
                <h4>{verb}</h4><p>{text}</p>{ui.chip(stages[key].status)}"""
        )
        st.page_link(page, label=f"Open {verb.lower()}", icon=":material/arrow_forward:",
                     icon_position="right")

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
    ("Response", "Routes are straight lines to predicted patches; real navigation needs local checks.", 90,
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
