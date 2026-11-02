# GulfOilGuard-AI dashboard

Streamlit dashboard for GulfOilGuard-AI. It **only reads result files** written by the detection, drift and routing modules into `outputs/`. It never imports `torch`, `opendrift` or `ortools`, and it never runs a model, simulation or solver.

Until a module writes its files, its page shows an empty state that explains what the section will show. Once the files appear, the page renders them on the next rerun with no restart and no code change.

## Run it

From the repository root (Windows PowerShell):

```powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r dashboard/requirements.txt
streamlit run dashboard/app.py
```

macOS/Linux: `python3 -m venv .venv && source .venv/bin/activate`, then use the same last two commands.

`dashboard/requirements.txt` is deliberately lightweight (Streamlit 1.66 or newer). You do **not** need the root `requirements.txt` (torch, opendrift, ortools) to run the dashboard. Launch from the repo root so `.streamlit/config.toml` (theme, hidden Streamlit chrome) is picked up.

### Navigation

There is no sidebar. The top bar is a response timeline: **Overview → 01 Detect → 02 Predict → 03 Respond**. The dot after each step shows its status: sea green = live data, violet = simulated scenario, slate = no data yet.

### Presenter & developer options (gear icon, top right)

- **Demo scenario**: renders a simulated Gulf incident from `services/mock_data.py`. Every page then shows a violet **Simulated scenario** chip next to its title.
- **Refresh data**: triggers a rerun. Files are cached on their modification time, so changed files are always re-read.
- **Diagnostics** (collapsed): resolved data folder, each expected file with its last-modified time, and loader warnings (malformed files). This is the only place technical details appear; the main UI only says "Part of this result couldn't be displayed".

URL options: `?demo=1` starts in the demo scenario (the older `?mock=1` still works), `?dev=1` opens Diagnostics by default. Example: `http://localhost:8501/?demo=1&dev=1`.

Uncaught errors are hidden from viewers (`showErrorDetails = "none"` in `.streamlit/config.toml`). While developing, run with `streamlit run dashboard/app.py --client.showErrorDetails=full` to see tracebacks.

### Pointing at a different data folder

Precedence: the `GULFOILGUARD_OUTPUTS` environment variable, then `outputs_dir:` in an optional `dashboard/settings.yaml` (relative to the repo root), then the default `<repo>/outputs`.

```powershell
$env:GULFOILGUARD_OUTPUTS = "D:\gulf_runs\run_03"; streamlit run dashboard/app.py
```

### Sample files

To see exactly what the dashboard expects, write the demo scenario as real files and point the dashboard at them:

```powershell
python dashboard/make_sample_outputs.py sample_outputs
$env:GULFOILGUARD_OUTPUTS = "sample_outputs"; streamlit run dashboard/app.py
```

Every sample file is marked `"synthetic": true`, so the dashboard labels those pages **Simulated scenario** even with the demo toggle off. Do not copy them into `outputs/`.

## Demo script (about 2 minutes)

Open `http://localhost:8501/?demo=1` before you start (or switch on **Demo scenario** from the gear menu). Point out the violet **Simulated scenario** chip once, at the start: the numbers are illustrative, the pipeline and interface are real.

1. **Overview (30 s).** "GulfOilGuard-AI turns satellite radar into a cleanup plan for the Arabian Gulf." Read the four headline tiles: a 6.8 km² slick, spreading to about 52 km² within 24 hours, 3 vessels deployed, response complete in about 4.6 hours. Point to the timeline in the top bar: "Detect, Predict, Respond: one incident, three steps." Close on *How far can you trust this?*: each stage feeds the next, so uncertainty compounds, and we show that openly.
2. **01 Detect (30 s).** Radar image, detected oil and overlay side by side: "Oil calms the sea, so it looks dark to radar." Show the accuracy tiles (Dice 0.78, precision 0.81, recall 0.75) and mention look-alikes such as calm water, algae and rain cells. Finish on the map: the slick placed off the Abu Dhabi coast.
3. **02 Predict (30 s).** Step through **Now → +6 h → +12 h → +24 h** with the segmented control. The slick moves south-east and spreads as colours darken from amber to burnt orange. Mention the drivers below the map: a north-west wind (shamal) at 8 m/s and a weak current.
4. **03 Respond (30 s).** Three vessels from three bases, each in its own cool colour, converge on the amber oil patches. Read the totals (about 148 km sailed, 235 m³ of an estimated 276 m³ recovered) and the vessel table. Close: "When the detection, drift and routing models produce real results, this exact view fills in automatically."

## Data contract

**`shared/schemas.py` is the single source of truth.** Wherever it defines a structure, the files below use its field names, types, units and allowed values, and the dashboard validates them into those dataclasses (`DetectionOutput`, `DriftOutput`, `TimedPosition`, `GeoCoordinate`, `VesselRoute`, `Vessel`, `ResponseTarget`, `OptimizationOutput`). Fields marked *extension* have no equivalent in the schema; they are dashboard-only and are listed as open points for the schema owners.

Conventions from the schema:
- **Coordinates:** WGS84 degrees. GeoJSON geometries use `[longitude, latitude]` (GeoJSON standard); plain JSON objects use the schema's own field names `{"latitude": .., "longitude": ..}`. Latitude in [-90, 90], longitude in [-180, 180], finite.
- **Time:** timezone-aware UTC, ISO 8601 (`2026-03-14T06:42:00Z`). Naive timestamps are rejected.
- **Units** follow the schema's field-name suffixes: `_km` kilometres, `_hours` hours, `_m3` cubic metres, `_m_per_s` metres per second. Measurements are nonnegative, speeds positive.
- **IDs** (`vessel_id`, `target_id`) are unique. `confidence` is in [0, 1].

All files live under `outputs/` at the repo root (in `.gitignore`; generated locally, not committed). Every file is optional on its own. The dashboard never crashes on malformed or non-conforming data: viewers see "Part of this result couldn't be displayed", and the exact validation error appears under Diagnostics. Run `python dashboard/check_schema.py` to validate the demo scenario and sample files against the schema. Any file may include `"synthetic": true` (top level or in feature properties) to have its page labelled as a simulated scenario.

### Detection module → `outputs/detection/`

| File | Required | Content |
| --- | --- | --- |
| `mask.png` | yes | Predicted binary mask (`DetectionOutput.mask_path`); white (>127) = oil. |
| `metrics.json` | yes | Held-out scores in [0, 1] (*extension*, see below). |
| `overlay.png` | optional | Mask drawn over the scene. If missing, the dashboard builds one from `image.png` + `mask.png`. |
| `image.png` | optional | The SAR input scene shown next to the mask. |
| `spill.geojson` | optional* | One `Polygon`/`MultiPolygon` feature per detected slick. *Needed for the map and for drift integration. |

Multiple scenes: name files `<image_id>_image.png`, `<image_id>_mask.png`, `<image_id>_overlay.png`; the page shows a scene picker.

`spill.geojson` feature properties, validated as a `DetectionOutput` (the outline's vertices become `oil_coordinates`):

| Property | Schema | Notes |
| --- | --- | --- |
| `image_id` | `DetectionOutput.image_id` | required, non-empty string |
| `confidence` | `DetectionOutput.confidence` | optional, [0, 1] |
| `area_km2` | *extension* | optional, nonnegative; otherwise the polygon area is computed |

```json
{
  "dice": 0.78, "iou": 0.64, "precision": 0.81, "recall": 0.75,
  "per_class": {"oil": {"dice": 0.78, "iou": 0.64, "precision": 0.81, "recall": 0.75}},
  "model": "unet-baseline-v1", "split": "val", "n_images": 1615, "threshold": 0.5
}
```

`metrics.json` is an *extension*: `shared/schemas.py` has no metrics type. Its four keys match `SegmentationMetrics` in `detection/evaluate.py`. `per_class` and the descriptive keys are optional.

### Drift module → `outputs/drift/`

| File | Required | Content |
| --- | --- | --- |
| `drift.geojson` | yes | Oil state per forecast step: `Point`/`MultiPoint` particles and/or `Polygon`/`MultiPolygon` envelopes (*extension*). |
| `meta.json` | optional | The `DriftOutput` trajectory plus model inputs. |

`drift.geojson` feature properties:

| Property | Schema | Notes |
| --- | --- | --- |
| `hours` | *extension* | required: hours since release (`0`, `6`, `12`, `24`; other values work) |
| `timestamp` | `TimedPosition.timestamp` | optional, UTC; must equal release time + `hours` when a release time is known |
| `kind` | *extension* | optional: `"particles"` or `"envelope"` |

`meta.json`:

| Field | Schema | Notes |
| --- | --- | --- |
| `simulation_id` | `DriftOutput.simulation_id` | required if any `DriftOutput` field is given |
| `initial_location` | `DriftOutput.initial_location` | `{"latitude": .., "longitude": ..}` |
| `positions` | `DriftOutput.positions` | `[{"timestamp": "..Z", "coordinate": {"latitude": .., "longitude": ..}}]`, ordered by time; drawn as the slick's centre path |
| `duration_hours` | `DriftOutput.duration_hours` | nonnegative |
| `start_time` | (same type as `EnvironmentalData.start_time`) | optional, UTC; release time when `positions` is absent |
| `wind_speed_m_per_s`, `current_speed_m_per_s` | *extension* (schema unit suffix) | nonnegative |
| `wind_from_deg`, `current_to_deg` | *extension* | 0-360 |
| `model`, `wind_source`, `current_source`, `oil_type`, `n_particles` | *extension* | descriptive |

The "Spread at 24 h" and "Oil footprint" tiles need polygon envelopes; with points only they show a dash.

### Routing module → `outputs/routing/`

| File | Required | Content |
| --- | --- | --- |
| `routes.geojson` | yes | One `LineString` per vessel (`VesselRoute.coordinates`), starting at the vessel's position and visiting targets in order. |
| `summary.json` | yes | `OptimizationOutput` without its routes: `status` (required) and `message`. |
| `targets.geojson` | optional | One `Point` per `ResponseTarget`. |

`routes.geojson` feature properties:

| Property | Schema | Notes |
| --- | --- | --- |
| `vessel_id` | `VesselRoute.vessel_id` / `Vessel.vessel_id` | required, unique |
| `assigned_target_ids` | `VesselRoute.assigned_target_ids` | required list of target IDs in visiting order |
| `estimated_distance_km` | `VesselRoute.estimated_distance_km` | optional, nonnegative |
| `estimated_travel_hours` | `VesselRoute.estimated_travel_hours` | optional, nonnegative; from dispatch to the last stop |
| `speed_m_per_s`, `capacity_m3`, `available_hours` | `Vessel` | optional, but all three together; `Vessel.location` = first route coordinate |
| `oil_collected_m3` | *extension* | optional, nonnegative; warned if above `capacity_m3` |

```json
{"status": "feasible", "message": "Solved in 2.1 s with OR-Tools RoutingModel"}
```

`status` must be one of `optimal`, `feasible`, `infeasible`, `not_solved`, `error` (read from `OptimizationOutput.status`). Fleet totals are derived, not read: vessels = number of routes, response time = max `estimated_travel_hours`, distance = sum of `estimated_distance_km`, oil to collect = sum of target `oil_volume_m3`.

`targets.geojson` feature properties: `target_id` (`ResponseTarget.target_id`, required, unique), `oil_volume_m3` (`ResponseTarget.oil_volume_m3`, required, nonnegative), optional `source_hours` (*extension*: the drift step the targets came from, used to pick the oil layer under the routes). Every `assigned_target_ids` entry should exist in `targets.geojson`.

### Spill sites → `outputs/spills.geojson` (optional)

The incidents offered on the Overview map. One `Point` feature per incident with `spill_id` (required, unique, letters/digits/`_`/`-`), `name` (optional) and `synthetic`. Not in `shared/schemas.py`; the position is validated as a `GeoCoordinate`. Without this file (or in demo mode) the dashboard offers four simulated sites around `MAP_CENTER` (`mock_data.MOCK_SPILL_SITES`).

### Radar images → `assets/images/`

Clicking a spill assigns a **random** `.png`/`.jpg` from `assets/images/` (recursive; override with the `GOG_IMAGE_DIR` environment variable). The image is a sample from the local dataset and is not geolocated to the spill. The folder is git-ignored, so copy images in locally. The selection (`sel_spill_id`, `sel_image_path`, `sel_image_id`) lives in `st.session_state` and is shared by all pages; see `services/selection.py`.

### Selected-spill flow (Detect → Predict → Respond)

With a spill selected, each page follows it and unlocks in order. **Detect** runs the U-Net on the assigned image in a subprocess (`python -m detection.predict_cli`, so Streamlit never imports torch) and writes `outputs/detection/<image_id>_{image,mask,overlay}.png` plus a `<image_id>_run.json` cache manifest. Settings: `GOG_CHECKPOINT` (default `runs/unet_refined_sar/best.pth`), `GOG_DETECTION_PYTHON` (an interpreter with torch; default the dashboard's own), timeout `DETECTION_TIMEOUT_S` in `config.py`. Without a checkpoint the page falls back to the simulated detection; without PyTorch it explains which variables to set and offers the simulated detection. Error details (tracebacks, paths) appear only with `?dev=1`. Results are re-checked on every run: a spill that is no longer offered, a demo-mode toggle or a change in where drift / routing come from resets the steps, and a detection whose files were deleted has to be run again. **Predict** and **Respond** reuse the existing drift and routing results (or the demo scenario), moved so the drift's release point sits on the selected spill (`services/scenario.py`), and are always labelled simulated.

## Code layout

```
dashboard/
  app.py                  entry point: styles, hidden st.navigation, top bar, footer
  config.py               data paths (data contract), map centre, palette
  make_sample_outputs.py  writes the demo scenario as files
  check_schema.py         validates demo + sample files against shared/schemas.py (exit 1 on mismatch)
  assets/styles.css       theme layer: glass cards, top bar, hero, chips, empty states
  views/                  overview, detection (Detect), drift (Predict), cleanup (Respond)
                          (not "pages/": that name triggers Streamlit's legacy auto-navigation)
  components/
    data.py               demo vs real data, per-stage status (live / simulated / empty)
    labels.py             display units and status wording derived from the schema
    nav.py                top bar (response timeline) and the options panel + diagnostics
    incident.py           Overview incident picker (spill map, selected spill, assigned image)
    ui.py                 headings, chips, stat tiles, empty states, legend, footer
    illustrations.py      inline SVG art (embedded as data-URI images)
    maps.py, charts.py    Folium (dark basemap) and Plotly helpers
  services/
    schema.py             imports shared/schemas.py; validators that build its dataclasses
    files.py              tolerant JSON / GeoJSON / image readers, cached on mtime
    models.py             containers the pages render (holding the shared dataclasses)
    detection_loader.py   -> DetectionData | None
    drift_loader.py       -> DriftData | None
    routing_loader.py     -> RoutingData | None
    spill_loader.py       -> SpillData | None (Overview map incidents)
    image_picker.py       lists / randomly picks radar images (no Streamlit; unit-testable)
    selection.py          selected spill + image in session_state, map-click parsing
    mock_data.py          demo scenario (synthetic)
    geo.py, imaging.py    small helpers (no shapely/geopandas)
```

Loaders return `None` when none of their files exist (empty state). If files exist but are broken or do not conform to the schema, they return a data object with `warnings`, which only the Diagnostics panel shows. The demo scenario is built by the same parse/validate functions, so it cannot contain anything a real file would fail on.

To add a field: if `shared/schemas.py` defines it, validate it in `services/schema.py` and use the schema's name; if not, agree on it with the schema owners first (do not edit the schema from the dashboard). Then read it in the loader, render it in the view, document it here, and run `python dashboard/check_schema.py`. Keep viewer-facing copy free of file names and paths.
