# GulfOilGuard-AI dashboard

Streamlit dashboard for GulfOilGuard-AI. The Detect flow runs the trained U-Net in a separate Python process and reads its generated image, mask and overlay from `outputs/detection/`. Predict and Respond read result files from `outputs/`. The Streamlit process does not import `torch`, `opendrift` or `ortools`.

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

### Real detection (optional)

The Detect step runs the trained U-Net in a separate Python that has PyTorch; the dashboard's own environment stays torch-free. With the **standard layout nothing needs configuring**:

```text
checkpoints/unet_best.pth   the trained checkpoint (request it from the detection team; git-ignored)
.venv-detect/               a Python with PyTorch: Scripts\python.exe on Windows, bin/python elsewhere
assets/images/              radar images (git-ignored)
```

Create the detection environment once, from the repository root:

```powershell
py -3.13 -m venv .venv-detect
.venv-detect\Scripts\python.exe -m pip install torch==2.7.1 --index-url https://download.pytorch.org/whl/cpu
.venv-detect\Scripts\python.exe -m pip install numpy==2.2.6 Pillow==12.3.0
```

If your files live elsewhere, copy `.env.example` to `.env` (git-ignored) and set `GOG_CHECKPOINT`, `GOG_DETECTION_PYTHON` or `GOG_IMAGE_DIR` there, or set them as real environment variables. Each setting resolves as **environment variable > `.env` > standard layout**, then the built-in fallback (`runs/unet_refined_sar/best.pth`; the dashboard's own Python, which has no PyTorch and makes Detect report "setup needed"). Relative paths are resolved from the repository root, never from the working directory, so it does not matter where Streamlit is started. When detection can't run, the Detect page lists every location it checked, in order (file names only; full paths with `?dev=1`), and the options panel's Diagnostics shows what was resolved. Without a checkpoint or PyTorch, the simulated detection is still available.

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
| `summary.json` | optional | `detection/report.py`'s summary; its `micro` scores are used when `metrics.json` has none. Also looked for in `outputs/report/`. |
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

Either shape is accepted: the four scores at the top level (above), nested under `"metrics"` as `detection/evaluate.py --output-dir` writes it, or under `"micro"` as in `report.py`'s `summary.json`. Optional `"checkpoint_sha256"` (in `metrics.json` or `summary.json`) is compared with the SHA-256 of the checkpoint the dashboard runs: the Detect page then says "Scores were computed on this checkpoint", or warns "These scores were computed on a different checkpoint than the one running" (also under Diagnostics). Without it the page notes that the report doesn't say which checkpoint was scored. The hash is computed once per checkpoint file (cached on path, modification time and size).

Scores always come from **one** file, never a mix: the first of `detection/metrics.json`, `detection/summary.json`, `report/summary.json` whose four scores are all valid; if none is fully valid, the first with any valid score (the others show as "—", with the problem under Diagnostics). Viewers see only these evaluation details: `model`, `split`, `n_images`, `threshold`, `checkpoint`, `epoch`, `aggregation`, `created` and `limitations`; any path-like text in them is reduced to its file name. Other keys are ignored on the page and listed by name only under Diagnostics. The caption under "Overall model accuracy" follows `split`: `val` adds that the split also chose the checkpoint; another split is named as such; without `split` the page says the report doesn't say which images were scored.

### Evaluation report → `outputs/report/`

What `detection/report.py` writes by default (`--output-dir outputs/report`). All optional; the dashboard only reads them.

| File | Used for |
| --- | --- |
| `summary.json` | Scores for "Overall model accuracy" when `outputs/detection/` has neither `metrics.json` nor `summary.json` (order: `detection/metrics.json` > `detection/summary.json` > `report/summary.json`). |
| `per_image_metrics.csv` | "Score for this image" on Detect, after a real model run: Dice, IoU, Precision, Recall and the reference oil share (`ref_oil_pixels / 65,536`) of the selected image. Each score tile also shows the overall value in small type ("Overall 0.87"), so the per-image block and "Overall model accuracy" below it, which never changes between images, are not confused. Columns `file, ref_oil_pixels, dice, iou, precision, recall`, optionally `split`. |
| `gallery_best.png`, `gallery_median.png`, `gallery_worst.png` | The expander "Best, median and worst validation images" under "Overall model accuracy". An unreadable file is left out and listed under Diagnostics. |

**Splits.** The Refined Deep-SAR SOS `train/` and `val/` folders reuse the same file names (`palsar_0.png` exists in both, with different content), so a file name alone is ambiguous. A CSV row matches the selected image only when **both** the split and the file name agree. The image's split is the nearest folder named `train`, `val` or `test` between the image and the image folder (inclusive, so `GOG_IMAGE_DIR=assets/images/val` counts as `val`). A row's split is its `split` column, else a folder in `file` (`val/palsar_0.png`), else the report's `"split"` from `metrics.json` / `summary.json`; with none of these the rows match nothing. Images in `train/` show "No reference score: this image was part of the model's training data"; images without a matching row show "No reference score for this image"; a row with no reference oil shows "No oil in the reference mask" instead of its degenerate 0 / 1 scores. Nothing is matched by name alone.

**Caveat.** `report.py` scores the validation split, which was also used to choose the checkpoint, so these scores (overall and per image) are not an independent test. For demos, set `GOG_IMAGE_DIR=assets/images/val` (environment or `.env`): only validation images can show a per-image score, and none of them were used to fit the weights.

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
| `status` | *extension* | optional, OpenDrift element status. Only `"active"` particles are drawn and counted as oil afloat; any other status (`"stranded"`, `"evaporated"`, `"dispersed"`, ...) is drawn as grey "No longer afloat" dots with its own legend entry. Without `status`, every particle counts as afloat |

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
| `model`, `wind_source`, `current_source`, `oil_type`, `n_particles` | *extension* | descriptive; `model` also decides the label (below) |
| `release_volume_m3`, `note`, `assumptions` | *extension* | optional, shown under "Run details" with the fields above (`assumptions`: `sea_water_temperature_c`, `sea_water_salinity_psu`, `horizontal_diffusivity_m2_per_s`, `vertical_mixing`, `release`) |

The "Spread at 24 h" and "Oil footprint" tiles need polygon envelopes; with points only they show a dash.

**Label.** A `meta.json` whose `model` names an OpenDrift run (starts with `OpenDrift` and does not say "simulated" or "illustrative", e.g. `"OpenDrift 1.14.11 OpenOil"`) marks the files as real model output. Real model output labelled `"synthetic": true` (because its release point is a test input) shows **Real forecast, simulated release**; without `"synthetic": true` it shows **Live data**. **Simulated scenario** is kept for the demo and any other synthetic drift file (the demo's model is "OpenDrift OpenOil (simulated, illustrative)").

**Release point.** A real forecast applies only to its own release point (`initial_location`). With a spill selected, Predict shows it only when the spill is within 1 km of that point (`scenario.RELEASE_MATCH_KM`), unmoved; any other spill gets the demo scenario moved to it, with a note that the real forecast doesn't apply there. The forecast time is a slider over every step, with buttons for 0, 6, 12 and 24 h; "Show earlier steps" draws only those key times.

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

### Per-site results → `outputs/sites/<id>/` (optional)

One folder per spill marker, in the same formats as above. The folder name is the marker id.

```text
outputs/sites/<id>/drift/      drift.geojson, meta.json          (as outputs/drift/)
outputs/sites/<id>/routing/    routes.geojson, summary.json, targets.geojson, comparison.json, baseline/
outputs/sites/<id>/validation.json   optional: the team's per-site check ("counts": {"OK", "WARN", "FAIL"})
```

When `outputs/sites/` holds at least one site folder (and the demo is off), Predict and Respond read the selected marker's own folder, unmoved, instead of `outputs/drift/` and `outputs/routing/`:

- **Markers.** From `outputs/spills.geojson` if it exists (its `spill_id` must equal the folder name), otherwise one marker per site folder at `drift/meta.json` `initial_location`, otherwise the simulated `GOG-SIM-01`..`04` catalogue (always used in demo mode).
- **Missing site rule.** A marker without a site folder (or without drift / routing files in it) shows **No data yet** on Predict and Respond with a short note. It never shows another site's results, and never the demo mixed in with real sites.
- **Release point.** A site whose `initial_location` is more than 1 km from its marker (`scenario.RELEASE_MATCH_KM`) keeps a Diagnostics warning and is not shown as a real forecast.
- **Labels.** A real OpenDrift run at its own release point shows **Real forecast, simulated release**, as for `outputs/drift/`. Respond still shows **Simulated scenario** for the plan.
- **No selection.** Predict, Respond and the Overview headline numbers show nothing until a marker is picked (there is no single dataset); then they follow that site, and Overview says which site the numbers are for.
- **Diagnostics** lists every site folder with its file status and a validation line per site, and warns about markers without a folder, sites without a marker and failed validation checks.
- Without `outputs/sites/` the single-folder behaviour above is unchanged.

Check a per-site delivery with `python tests/check_outputs.py outputs --sites --gulf`: the drift and routing checks per site, plus whether `comparison.json` / `summary.json` `scenario_id` belongs to the site's drift run (`<simulation_id>` or `<simulation_id>@...`) and whether `initial_location` is within 1 km of the site's marker.

### Spill sites → `outputs/spills.geojson` (optional)

The incidents offered on the Overview map. One `Point` feature per incident with `spill_id` (required, unique, letters/digits/`_`/`-`), `name` (optional) and `synthetic`. Not in `shared/schemas.py`; the position is validated as a `GeoCoordinate`. Without this file (or in demo mode) the dashboard offers four simulated sites around `MAP_CENTER` (`mock_data.MOCK_SPILL_SITES`).

### Radar images → `assets/images/`

Clicking a spill assigns a **random** `.png`/`.jpg` from `assets/images/` (recursive; override with the `GOG_IMAGE_DIR` environment variable). The image is a sample from the local dataset and is not geolocated to the spill. The folder is git-ignored, so copy images in locally. For demos, point `GOG_IMAGE_DIR` at `assets/images/val`.

> **Warning:** the image folder may contain the detection model's own training data (the Refined Deep-SAR SOS `train/` crops were used to fit it, and `val/` to choose the checkpoint). Predictions on these images look better than they would on new imagery, so a demo must not be presented as an accuracy test. File names starting with `sentinel_` or `palsar_` are labelled Sentinel-1 / ALOS PALSAR in the UI (per `docs/literature_review.md`); other names get no sensor label. The selection (`sel_spill_id`, `sel_image_path`, `sel_image_id`) lives in `st.session_state` and is shared by all pages; see `services/selection.py`.

### Selected-spill flow (Detect → Predict → Respond)

With a spill selected, each page follows it and unlocks in order. **Detect** runs the U-Net on the assigned image in a subprocess (`python -m detection.predict_cli`, so Streamlit never imports torch) and writes `outputs/detection/<image_id>_{image,mask,overlay}.png` plus a `<image_id>_run.json` cache manifest. Clicking **Run detection** always executes the model, even if a matching prediction was saved earlier. The page then reads the newly written mask and overlay. Where the checkpoint and the interpreter are is resolved as described in [Real detection](#real-detection-optional); the timeout is `DETECTION_TIMEOUT_S` in `config.py`. Without a checkpoint the page falls back to the simulated detection; without PyTorch it explains which variables to set and offers the simulated detection. Error details (tracebacks, paths) appear only with `?dev=1`. Results are re-checked on every run: a spill that is no longer offered, a demo-mode toggle or a change in where drift / routing come from resets the steps, and a detection whose files were deleted has to be run again. **Predict** shows a real OpenDrift forecast only for the spill at its release point, unmoved and labelled **Real forecast, simulated release**; for any other spill it uses the demo scenario (or other drift results that are not a model run), moved so the release point sits on the spill and labelled simulated. **Respond** reuses the existing routing results (or the demo plan), moved by the same offset as the drift results, and is always labelled simulated (`services/scenario.py`).

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
    spill_loader.py       -> SpillData | None (Overview map incidents: spills.geojson or site folders)
    image_picker.py       lists / randomly picks radar images, split from folder names (no Streamlit)
    report_loader.py      per-image scores (split + file name), report split, checkpoint SHA-256 check
    settings.py           checkpoint / detection Python / image folder: env > .env > standard layout
    selection.py          selected spill + image in session_state, map-click parsing
    mock_data.py          demo scenario (synthetic)
    geo.py, imaging.py    small helpers (no shapely/geopandas)
```

Loaders return `None` when none of their files exist (empty state). If files exist but are broken or do not conform to the schema, they return a data object with `warnings`, which only the Diagnostics panel shows. The demo scenario is built by the same parse/validate functions, so it cannot contain anything a real file would fail on.

To add a field: if `shared/schemas.py` defines it, validate it in `services/schema.py` and use the schema's name; if not, agree on it with the schema owners first (do not edit the schema from the dashboard). Then read it in the loader, render it in the view, document it here, and run `python dashboard/check_schema.py`. Keep viewer-facing copy free of file names and paths.
