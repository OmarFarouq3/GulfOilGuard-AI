"""Overview incident picker: spill markers on a map, a list of the same spills, the selected spill and its image.

The selection itself lives in services.selection (one key, ``selection.SPILL_KEY``); this module only
draws it. The map and the list are two ways to change that one selection: a marker click and a choice
in the list both call ``selection.select_spill`` (or ``clear_selection``), and the list's widget value
is rewritten from the selection before every render, so it never holds a choice of its own. The list
works without the map, which needs an internet connection (Leaflet and the tiles come from CDNs).
"""

from __future__ import annotations

import streamlit as st

import config
from components import flow, maps, ui
from components.data import Stage, demo_mode, site_forecast
from services import image_picker, scenario, selection, settings
from services.files import read_image
from services.imaging import preview_png
from services.models import SpillSite

DETECT_PAGE = "views/detection.py"
SITE_SELECT_KEY = "overview_site_select"  # the list's widget value: a mirror of selection.SPILL_KEY, see _site_list
NO_INCIDENT = ""  # the list's "no incident" option
NO_INCIDENT_LABEL = "No incident selected"
MAP_OFFLINE = "The map needs an internet connection. Choose a site in the list below the map."


def picker(stage: Stage) -> None:
    """Map with clickable spills on the left, the selected spill and its image on the right."""
    sites = stage.data.sites if stage.data else []
    if not sites:
        ui.inline_empty("Reported spills will appear here.")
        return
    chosen = stage.data.get(selection.selected_spill_id())  # unknown ids were cleared in app.py

    left, right = st.columns([3, 2], gap="large")
    with left:
        m = maps.base_map()
        maps.add_spill_markers(m, sites, chosen.spill_id if chosen else None)
        points = [{"geometry": {"type": "Point", "coordinates": [s.location.longitude, s.location.latitude]}}
                  for s in sites]
        with st.container(key="gog-overview-map"):  # keeps its height when the map can't load (styles.css)
            # Behind the map (styles.css): covered while the map paints, readable when it can't load.
            st.html(f'<div class="gog-map-offline" aria-hidden="true">{ui.esc(MAP_OFFLINE)}</div>')
            clicked = maps.render(m, points, key="overview_map", height=480,
                                  returned_objects=selection.MAP_CLICK_OBJECTS)
        if scenario.sites_mode(demo_mode()):  # each marker is a site with its own drift run from a hypothetical release point
            site_label = "Forecast site (simulated release point)"
        else:
            site_label = "Simulated spill site" if stage.status == "simulated" else "Reported spill"
        ui.legend([(config.OIL_OBSERVED, site_label, "dot"), (config.TEAL, "Selected spill", "dot")])
        if selection.handle_map_click(clicked, sites):
            st.rerun()  # redraw the highlighted marker, the list and the panel
        _site_list(sites)
    with right:
        if chosen is None:
            ui.inline_empty("No incident selected yet. Click a spill on the map, or choose one in the list below "
                            "the map, to follow it through Detect, Predict and Respond.")
        else:
            _selected(chosen, simulated=chosen.synthetic or stage.status == "simulated")


def site_option(site: SpillSite | None) -> str:
    """How a spill is named in the list: what it is, from the files (docs/dashboard_provenance_audit.md)."""
    if site is None:
        return NO_INCIDENT_LABEL
    where = ui.coordinates(site.location.latitude, site.location.longitude)
    if demo_mode():  # the demo scenario, moved onto this point (services.scenario)
        return f"{site.name} · illustrative demo scenario at {where}"
    if scenario.sites_mode(False):  # labelled from the site's own files, as on Predict (components.data)
        status = site_forecast(site).status
        if status == "forecast":  # its own drift run at its own release point
            return f"{site.name} · precomputed run from a hypothetical release at {where}"
        return f"{site.name} · {'no drift run yet' if status == 'empty' else 'precomputed scenario'} at {where}"
    return f"{site.name} · {where}"


def _site_list(sites: list[SpillSite]) -> None:
    """The same choice as a marker click, without the map. One source of truth: selection.SPILL_KEY.

    The widget value is overwritten from the selection before every render, so a marker click shows
    here at once and the list never keeps a choice of its own; changing it calls the same functions
    as a click.
    """
    labels = {NO_INCIDENT: site_option(None), **{s.spill_id: site_option(s) for s in sites}}
    current = selection.selected_spill_id()
    st.session_state[SITE_SELECT_KEY] = current if current in labels else NO_INCIDENT
    st.selectbox("Spill site", list(labels), key=SITE_SELECT_KEY, format_func=labels.__getitem__,
                 on_change=_site_list_changed, help="The same choice as clicking a marker on the map.")


def _site_list_changed() -> None:
    chosen = st.session_state.get(SITE_SELECT_KEY)
    if chosen:
        selection.select_spill(chosen)
    else:
        selection.clear_selection()


def _selected(site: SpillSite, simulated: bool) -> None:
    details = {"Incident": site.spill_id, "Position": ui.coordinates(site.location.latitude, site.location.longitude)}
    chip = ui.chip("simulated") if simulated else ""
    if scenario.sites_mode(demo_mode()):  # label it as Predict will (components.data._stage), from the site's files
        forecast = site_forecast(site)
        chip = ui.chip(forecast.status) if forecast.status != "empty" else ""
        trajectory = forecast.data.trajectory if forecast.data else None
        if trajectory:
            location = trajectory.initial_location
            details["Drift run"] = trajectory.simulation_id
            details["Release point"] = ui.coordinates(location.latitude, location.longitude)
        else:
            details["Drift run"] = "None for this site yet"
    st.html(f'<div class="gog-incident-head"><h4>{ui.esc(site.name)}</h4>{chip}</div>')
    ui.details_table(details)
    provenance = flow.drift_provenance(site_forecast(site).data) if scenario.sites_mode(demo_mode()) else None
    if provenance:
        st.html(f'<p class="gog-flow-note gog-site-provenance">{ui.esc(provenance)}</p>')
    flow.progress()

    current = selection.current()
    images = selection.available_images()
    if not selection.image_available(current):
        if not images:
            _images_missing()
        else:
            ui.inline_empty("The radar image for this incident is no longer available."
                            if current.image_path else "No radar image assigned yet.")
            st.button("Assign a radar image", icon=":material/image:", key="sel_assign_image",
                      on_click=selection.reroll_image)
        _clear_button()
        return

    raw, _warning = read_image(current.image_path)
    shown = preview_png(raw) if raw else None
    if shown is None:
        ui.inline_empty("The assigned radar image can't be displayed. Pick another image.")
    else:
        st.image(shown, width="stretch", alt="Radar image assigned to this incident",
                 caption=f"{_source_prefix(current.image_path)}Random sample from the local radar dataset "
                         f"({current.image_path.name}). "
                         "It is not geolocated to this spill.")
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        st.button("Pick another image", icon=":material/shuffle:", key="sel_reroll_image",
                  on_click=selection.reroll_image, disabled=len(images) < 2,
                  help="Draw a different random image from the local radar dataset")
        _clear_button()
    st.page_link(DETECT_PAGE, label="Continue to Detect", icon=":material/arrow_forward:", icon_position="right")


def _source_prefix(path) -> str:
    """'Sentinel-1 SAR sample from the local dataset. ' when the file name says so, else nothing."""
    source = image_picker.image_source(path)
    return f"{source}. " if source else ""


def _clear_button() -> None:
    st.button("Clear selection", icon=":material/close:", type="tertiary", key="sel_clear",
              on_click=selection.clear_selection)


def _images_missing() -> None:
    """What to put where. The exact folder is shown because nothing works without it."""
    st.html(
        f"""<div class="gog-inline-empty gog-images-missing"><b>No radar images found.</b> Add <code>.png</code> or
              <code>.jpg</code> radar images (subfolders are fine) to
              <code class="gog-path">{ui.esc(settings.shown_folder(image_picker.image_dir()))}</code>
              or point the <code>{image_picker.IMAGE_DIR_ENV}</code> environment variable at another folder,
              then refresh. The folder is not in git, so every machine needs its own copy. For a demo,
              <code>{image_picker.IMAGE_DIR_ENV}</code> can point at <code>assets/images/val</code>.</div>"""
    )
