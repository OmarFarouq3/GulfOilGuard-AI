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

All files live under `outputs/` at the repo root. That folder is in `.gitignore`: outputs are generated locally and not committed. All coordinates are **WGS84, GeoJSON order `[longitude, latitude]`**. Times are ISO 8601 UTC (`2026-03-14T06:42:00Z`). Units follow `shared/schemas.py`: km, hours, m/s, m³.

Every file is optional on its own. The dashboard renders whatever is present and never crashes on malformed files: it shows a generic notice to viewers and lists the details under Diagnostics. GeoJSON features with invalid geometry or out-of-range coordinates are skipped; the rest still render. Any file may include `"synthetic": true` (top level or in feature properties) to have its page labelled as a simulated scenario.

### Detection module → `outputs/detection/`

| File | Required | Content |
| --- | --- | --- |
| `mask.png` | yes | Predicted binary mask; white (>127) = oil. |
| `metrics.json` | yes | Held-out metrics (see below). |
| `overlay.png` | optional | Mask drawn over the scene. If missing, the dashboard builds one from `image.png` + `mask.png`. |
| `image.png` | optional | The SAR input scene shown next to the mask. |
| `spill.geojson` | optional* | Detected oil as `Polygon`/`MultiPolygon` in lon/lat. *Needed for the map and for drift integration. |

Multiple scenes: name files `<scene>_image.png`, `<scene>_mask.png`, `<scene>_overlay.png` (e.g. `S1A_20260314_mask.png`). The page shows a scene picker.

```json
{
  "dice": 0.78, "iou": 0.64, "precision": 0.81, "recall": 0.75,
  "per_class": {"oil": {"dice": 0.78, "iou": 0.64, "precision": 0.81, "recall": 0.75}},
  "model": "unet-baseline-v1", "split": "val", "n_images": 1615, "threshold": 0.5
}
```

Metric values are 0-1. `per_class` and any other keys are optional; extra scalar keys are shown as "Evaluation details". Suggested `spill.geojson` feature properties: `id`, `area_km2`, `confidence`, `scene_id`, `detected_at`. The Overview "Slick detected" tile uses `area_km2` when every feature has it, otherwise the polygon area.

### Drift module → `outputs/drift/`

| File | Required | Content |
| --- | --- | --- |
| `drift.geojson` | yes | FeatureCollection; **every feature has a numeric `hours` property** (`0` = release, `6`, `12`, `24`; other values also work). Geometry: `Point`/`MultiPoint` for particles and/or `Polygon`/`MultiPolygon` for oil envelopes. |
| `meta.json` | optional | Inputs and settings shown under "What drives the forecast". |

Optional feature properties: `timestamp` (UTC valid time), `kind` (`"particles"` / `"envelope"`). The "Spread at 24 h" and "Oil footprint" tiles need polygon envelopes; with points only they show a dash.

```json
{
  "start_time": "2026-03-14T06:42:00Z", "model": "OpenDrift OpenOil",
  "wind_source": "ERA5", "current_source": "Copernicus Marine GLOBAL_ANALYSISFORECAST_PHY",
  "wind_speed_ms": 8.0, "wind_from_deg": 315, "current_speed_ms": 0.2, "current_to_deg": 110,
  "n_particles": 1000, "oil_type": "..."
}
```

The four `wind_*`/`current_*` numbers are shown as tiles; `model`, `start_time`, `wind_source`, `current_source`, `oil_type` and `n_particles` are listed below them.

### Routing module → `outputs/routing/`

| File | Required | Content |
| --- | --- | --- |
| `routes.geojson` | yes | One `LineString` per vessel, starting at the vessel's base and visiting targets in order. |
| `summary.json` | yes | Fleet totals and solver status. |
| `targets.geojson` | optional | Target points/areas the solver used. |

`routes.geojson` feature properties: `vessel_id` (str), `order` (list of target IDs in visiting order, e.g. `["T1","T3"]`), `eta_hours` (time to finish the route from dispatch), optional `distance_km`, `oil_collected_m3`, `depot`.

```json
{
  "status": "feasible", "solver": "OR-Tools RoutingModel",
  "vessel_count": 3, "total_time_hours": 4.6, "total_distance_km": 148.0,
  "oil_collected_m3": 214.0, "oil_total_m3": 252.0
}
```

`status` is one of `optimal`, `feasible`, `infeasible`, `not_solved`, `error` (as in `shared/schemas.py`). `targets.geojson` properties: `target_id`, `oil_volume_m3`, optional `source_hours` (the drift step the targets were derived from, used to pick the default oil layer under the routes).

## Code layout

```
dashboard/
  app.py                  entry point: styles, hidden st.navigation, top bar, footer
  config.py               data paths (data contract), map centre, palette
  make_sample_outputs.py  writes the demo scenario as files
  assets/styles.css       theme layer: glass cards, top bar, hero, chips, empty states
  views/                  overview, detection (Detect), drift (Predict), cleanup (Respond)
                          (not "pages/": that name triggers Streamlit's legacy auto-navigation)
  components/
    data.py               demo vs real data, per-stage status (live / simulated / empty)
    nav.py                top bar (response timeline) and the options panel + diagnostics
    ui.py                 headings, chips, stat tiles, empty states, legend, footer
    illustrations.py      inline SVG art (embedded as data-URI images)
    maps.py, charts.py    Folium (dark basemap) and Plotly helpers
  services/
    files.py              tolerant JSON / GeoJSON / image readers, cached on mtime
    models.py             dataclasses the pages render
    detection_loader.py   -> DetectionData | None
    drift_loader.py       -> DriftData | None
    routing_loader.py     -> RoutingData | None
    mock_data.py          demo scenario (synthetic)
    geo.py, imaging.py    small helpers (no shapely/geopandas)
```

Loaders return `None` when none of their files exist (empty state). If files exist but are broken, they return a data object with `warnings`, which only the Diagnostics panel shows. To add a field: read it in the loader, add it to the dataclass in `models.py`, render it in the view, and document it in this README. Keep viewer-facing copy free of file names and paths.
