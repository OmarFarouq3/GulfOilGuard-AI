"""The spill and radar image the user is following, and how far it has got, in ``st.session_state``.

Streamlit reruns the page script on every interaction, and all pages of the app share
one session_state. So the random image is drawn only inside ``select_spill`` and
``reroll_image`` and stored; pages just read ``current()``.

Keys are namespaced ``sel_``. Everything computed for a selection (the detection run, the
"step completed" flags) lives under ``DOWNSTREAM_PREFIX``, so ``clear_downstream()`` drops it
whenever the spill or the image changes. The steps unlock in order:
Detect (model run, or simulated detection) -> Predict -> Respond.

``parse_map_click`` is pure (no session state) so it can be unit-tested without a browser.
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import streamlit as st

from services import image_picker, inference
from services.files import as_float, mtime
from services.geo import haversine_km
from services.inference import DetectionRun
from services.models import SpillSite

SPILL_KEY = "sel_spill_id"
IMAGE_PATH_KEY = "sel_image_path"
IMAGE_ID_KEY = "sel_image_id"
LAST_CLICK_KEY = "sel_last_click"
DOWNSTREAM_PREFIX = "sel_result_"
DETECT_RUN_KEY = DOWNSTREAM_PREFIX + "detect_run"  # DetectionRun of the last attempt
DETECT_SIMULATED_KEY = DOWNSTREAM_PREFIX + "detect_simulated"  # simulated detection accepted
PREDICT_DONE_KEY = DOWNSTREAM_PREFIX + "predict_done"
RESPOND_DONE_KEY = DOWNSTREAM_PREFIX + "respond_done"
OWNER_KEY = DOWNSTREAM_PREFIX + "for"  # (spill_id, image_path, source) the results belong to
SOURCE_KEY = "sel_source"  # current data source, set by sync() on every run
STASH_KEY = "sel_stash"  # (spill_id, image_path, image_id) of a selection dropped only because it wasn't offered
STEPS = ("detect", "predict", "respond")
StepState = Literal["done", "ready", "locked"]

# What st_folium must return for parse_map_click. The click count makes a repeat click on
# the same marker distinguishable from st_folium re-sending the last click on a rerun.
MAP_CLICK_OBJECTS = ("last_object_clicked", "last_object_clicked_count", "last_object_clicked_tooltip")
CLICK_RADIUS_KM = 5.0  # fallback match distance; catalogue sites are 20+ km apart
IMAGE_LIST_TTL_S = 60  # newly added images show up within a minute


@dataclass(frozen=True)
class Selection:
    spill_id: str | None = None
    image_path: Path | None = None
    image_id: str | None = None


def current() -> Selection:
    path = st.session_state.get(IMAGE_PATH_KEY)
    return Selection(st.session_state.get(SPILL_KEY), Path(path) if path else None,
                     st.session_state.get(IMAGE_ID_KEY))


def selected_spill_id() -> str | None:
    return st.session_state.get(SPILL_KEY)


def active() -> bool:
    """A spill is selected, so the pages follow it instead of showing the latest global results."""
    return selected_spill_id() is not None


# --- Images ---------------------------------------------------------------------------
# Listing verifies every file with PIL, so it is cached. The folder's mtime is part of the key
# (files added or removed at the top level show up at once); the TTL catches subfolders.


@st.cache_data(ttl=IMAGE_LIST_TTL_S, show_spinner=False)
def _images_cached(directory: str, stamp: float | None) -> list[str]:
    return [str(p) for p in image_picker.list_images(directory)]


def available_images() -> list[Path]:
    """Readable images in the radar dataset folder (see services.image_picker)."""
    directory = image_picker.image_dir()
    stamp = directory.stat().st_mtime if directory.is_dir() else None
    return [Path(p) for p in _images_cached(str(directory), stamp)]


def _store_image(path: Path | None) -> None:
    if path is None:
        st.session_state.pop(IMAGE_PATH_KEY, None)
        st.session_state.pop(IMAGE_ID_KEY, None)
    else:
        st.session_state[IMAGE_PATH_KEY] = str(path)
        st.session_state[IMAGE_ID_KEY] = image_picker.image_id(path)


def image_available(selection: Selection) -> bool:
    """The assigned image still exists on disk."""
    return selection.image_path is not None and mtime(selection.image_path) is not None


# --- State changes ----------------------------------------------------------------------


def clear_downstream() -> None:
    """Drop every result and "step completed" flag of the previous selection.

    That is the detection run, the simulated-detection choice and the Predict / Respond flags,
    plus anything else stored under DOWNSTREAM_PREFIX.
    """
    for key in [k for k in st.session_state.keys() if str(k).startswith(DOWNSTREAM_PREFIX)]:
        del st.session_state[key]


def _clear_after_detection() -> None:
    for key in (PREDICT_DONE_KEY, RESPOND_DONE_KEY):
        st.session_state.pop(key, None)


def _owner() -> tuple:
    """What the stored results depend on: spill, image and data source (see ``sync``)."""
    selection = current()
    return (selection.spill_id, str(selection.image_path) if selection.image_path else None,
            st.session_state.get(SOURCE_KEY))


def _claim() -> None:
    """Mark the stored results as belonging to the current spill, image and data source."""
    st.session_state[OWNER_KEY] = _owner()


def sync(valid_spill_ids: Iterable[str], source: Any) -> None:
    """Bring the selection and its results in line with the world, once per run (app.py).

    The single place that decides whether the selection is still valid, so ``active()``
    and every page agree:
    - a spill id that is no longer offered (spill list changed, demo toggled) clears the
      whole selection, but the spill and its image are restored if that spill is offered again
      (switching the demo off brings the site back; its steps must be run again);
    - results computed for another spill, image or data ``source`` (demo flag + where the
      drift / routing come from) are dropped, so steps never stay "done" over swapped data;
    - a model detection whose ``<image_id>_*`` files have disappeared is no longer done.
    """
    st.session_state[SOURCE_KEY] = source
    spill_id, valid = selected_spill_id(), set(valid_spill_ids)
    if spill_id is not None and spill_id not in valid:
        # Not offered any more (e.g. the demo catalogue replaced the site markers): remember the
        # spill and its image, and restore them once that spill is offered again.
        stash = (spill_id, st.session_state.get(IMAGE_PATH_KEY), st.session_state.get(IMAGE_ID_KEY))
        clear_selection()
        st.session_state[STASH_KEY] = stash
        return
    stash = st.session_state.get(STASH_KEY)
    if spill_id is None and stash and stash[0] in valid:
        st.session_state.pop(STASH_KEY)
        st.session_state[SPILL_KEY], st.session_state[IMAGE_PATH_KEY], st.session_state[IMAGE_ID_KEY] = stash
        return
    owner = st.session_state.get(OWNER_KEY)
    if owner is not None and tuple(owner) != _owner():
        clear_downstream()
        return
    run = detection_run()
    if run and run.ok and not inference.outputs_exist(run.image_id):
        st.session_state.pop(DETECT_RUN_KEY, None)
        _clear_after_detection()


# --- Steps ------------------------------------------------------------------------------


def detection_run() -> DetectionRun | None:
    return st.session_state.get(DETECT_RUN_KEY)


def simulated_detection_accepted() -> bool:
    return bool(st.session_state.get(DETECT_SIMULATED_KEY))


def record_detection(run: DetectionRun) -> None:
    """Store a detection attempt. Without a model checkpoint, fall back to the simulated detection."""
    _clear_after_detection()
    _claim()
    st.session_state[DETECT_RUN_KEY] = run
    st.session_state[DETECT_SIMULATED_KEY] = run.state == "checkpoint_missing"


def accept_simulated_detection() -> None:
    _clear_after_detection()
    _claim()
    st.session_state[DETECT_SIMULATED_KEY] = True


def detection_done() -> bool:
    run = detection_run()
    return bool(run and run.ok) or simulated_detection_accepted()


def predict_done() -> bool:
    return detection_done() and bool(st.session_state.get(PREDICT_DONE_KEY))


def respond_done() -> bool:
    return predict_done() and bool(st.session_state.get(RESPOND_DONE_KEY))


def complete_predict() -> None:
    if detection_done():
        _claim()
        st.session_state[PREDICT_DONE_KEY] = True
        st.session_state.pop(RESPOND_DONE_KEY, None)


def complete_respond() -> None:
    if predict_done():
        _claim()
        st.session_state[RESPOND_DONE_KEY] = True


def step_states() -> dict[str, StepState]:
    """Detect -> Predict -> Respond: each step is ready once the previous one is done."""
    done = {"detect": detection_done(), "predict": predict_done(), "respond": respond_done()}
    ready = {"detect": active(), "predict": done["detect"], "respond": done["predict"]}
    return {s: "done" if done[s] else "ready" if ready[s] else "locked" for s in STEPS}


def select_spill(spill_id: str, rng: random.Random | None = None) -> None:
    """Select a spill and draw its radar image once. Re-selecting the current spill keeps its image."""
    previous = current()
    if spill_id == previous.spill_id and previous.image_path is not None:
        return
    clear_downstream()
    st.session_state.pop(STASH_KEY, None)  # a deliberate choice replaces any remembered one
    st.session_state[SPILL_KEY] = spill_id
    # A new spill gets a different image than the last one, so the change is visible.
    _store_image(image_picker.choose_image(available_images(), exclude=previous.image_path, rng=rng))


def reroll_image(rng: random.Random | None = None) -> None:
    """Draw a new image for the selected spill (a different one when there is a choice)."""
    selection = current()
    if selection.spill_id is None:
        return
    clear_downstream()
    _store_image(image_picker.choose_image(available_images(), exclude=selection.image_path, rng=rng))


def clear_selection() -> None:
    for key in (SPILL_KEY, IMAGE_PATH_KEY, IMAGE_ID_KEY, STASH_KEY):
        st.session_state.pop(key, None)
    clear_downstream()


# --- Map clicks -------------------------------------------------------------------------


def parse_map_click(returned: Any, spills: Iterable[SpillSite], radius_km: float = CLICK_RADIUS_KM) -> str | None:
    """Spill id hit by the last st_folium object click, or None.

    The marker tooltip (the spill id) decides. Only when the click carries no tooltip is the
    nearest site within ``radius_km`` of the click used; a click on some other object that
    has its own tooltip never selects a spill.
    """
    if not isinstance(returned, dict):
        return None
    sites = list(spills)
    tooltip = returned.get("last_object_clicked_tooltip")
    if isinstance(tooltip, str) and tooltip.strip():
        return next((s.spill_id for s in sites if s.spill_id == tooltip.strip()), None)

    point = returned.get("last_object_clicked")
    if not isinstance(point, dict):
        return None
    lat, lng = as_float(point.get("lat")), as_float(point.get("lng"))
    if lat is None or lng is None:
        return None
    distances = [(haversine_km(lng, lat, s.location.longitude, s.location.latitude), s.spill_id) for s in sites]
    nearest = min(distances, default=None)
    return nearest[1] if nearest and nearest[0] <= radius_km else None


def _click_signature(returned: Any) -> tuple | None:
    if not isinstance(returned, dict) or not isinstance(returned.get("last_object_clicked"), dict):
        return None
    point = returned["last_object_clicked"]
    return (returned.get("last_object_clicked_count"), returned.get("last_object_clicked_tooltip"),
            point.get("lat"), point.get("lng"))


def handle_map_click(returned: Any, spills: Iterable[SpillSite]) -> str | None:
    """Apply a new map click; return the newly selected spill id (caller reruns to redraw).

    st_folium re-sends its last click on every rerun, so a click is processed once. A map
    without a click (first render, or remounted because its markers changed) resets the
    memory, so the first click on the fresh map always counts.
    """
    signature = _click_signature(returned)
    if signature is None:
        st.session_state.pop(LAST_CLICK_KEY, None)
        return None
    if signature == st.session_state.get(LAST_CLICK_KEY):
        return None
    st.session_state[LAST_CLICK_KEY] = signature
    spill_id = parse_map_click(returned, spills)
    if spill_id is None or spill_id == selected_spill_id():
        return None
    select_spill(spill_id)
    return spill_id
