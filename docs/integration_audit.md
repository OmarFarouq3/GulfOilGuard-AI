# Integration audit: real team outputs → dashboard (Task 2)

Read-only audit, 3 Nov 2026, on branch `dashboard` at `4b6d9c7` after `git fetch --all` and `git pull --ff-only` ("Already up to date"). `dashboard` contains all of `main` (`712323a`); it is 8 commits ahead with the dashboard work. Nothing was run against team data except reading files and code. This page lists what exists, what is missing, where formats differ from what the dashboard reads, and the order to connect them.

**Team activity (recent, remote branches).**

| Team | Branch | Latest | Merged into `main`? |
| --- | --- | --- | --- |
| A, Detection (Ayham, Yara, Sumaia) | `prediction-review` (Yara) | 3 Nov: prediction review update, `docs/prediction_review.md` | 1 commit not merged |
| A | `main` (Sumaia) | 2 Nov: `docs/detection_evaluation.md` | yes |
| B, Drift (Joud, Maqqavi) | `main` (PR #19, Maqqavi) | 3 Nov: 24 h Gulf OpenDrift run and exporter (`drift/simulate_drift.py`, `export_outputs.py`, `run_gulf_demo.py`) | yes |
| B | `revert-6-joud-drift-data` (Omar) | 2 Nov: reverts Joud's PR #6 | not merged; `main` keeps PR #6 |
| C, Cleanup (Haris, Nihal) | `routing-model` (Haris) | 3 Nov: "Tested using team B data", full-run setup guide in `optimization/README.md` | 1 commit not merged |
| C | `main` (PR #18, #20; Haris, Nihal) | 2 to 3 Nov: moving-oil planning, return to port, T+12 h scenario | yes |
| Integration (Maria) | `main` (PR #17) | 2 Nov: `tests/check_outputs.py`, `docs/integration_plan.md` | yes |
| Dashboard (Obeid) | `dashboard` | 3 Nov: report loader, per-image scores, error messages | 8 commits ahead of `main` |

---

## Available

### Contracts, checks and integration docs

| Where | What it defines |
| --- | --- |
| `shared/schemas.py` | Dataclasses `GeoCoordinate` (lat, lon), `DetectionOutput`, `DriftOutput` (`positions`: timestamped centre path), `EnvironmentalData`, `Vessel`, `ResponseTarget`, `VesselRoute`, `OptimizationOutput`. WGS84 degrees, timezone-aware UTC, km, hours, m/s. |
| `dashboard/README.md`, "Data contract" | The files under `outputs/` and their fields: `outputs/detection/`, `outputs/report/`, `outputs/drift/` (`drift.geojson`, `meta.json`), `outputs/routing/` (`routes.geojson`, `summary.json`, `targets.geojson`). GeoJSON is `[longitude, latitude]`. `"synthetic": true` labels a page simulated. |
| `optimization/README.md` §3 | What routing needs from drift (§3.1: `hours`, `particle_ids`, `status`, `oil_volume_m3`, `synthetic`; `meta.json` `release_volume_m3`) and what it writes for the dashboard. |
| `drift/README.md` | The agreed run and its output format (one `MultiPoint` per hour and status, plus one `Polygon` envelope per hour). |
| `docs/integration_plan.md` | Handoffs H1 to H7, open issues I1 to I10, decisions D1 to D3 (2 Nov). I1, I2 (detection metrics) are solved on the dashboard side; I4 (particles) was settled as option A; I6, I7 (response time, unserved targets) are still open. |
| `tests/contract_checks.py`, `tests/check_outputs.py` | Contract checks and a file checker: `python tests/check_outputs.py outputs --gulf` reads all three output folders, builds the dataclasses and checks the links between teams (route targets exist, targets come from a drift hour, timestamps = release + `hours`, Gulf box). |
| `dashboard/check_schema.py` | Validates the dashboard's demo and sample files against `shared/schemas.py`. |

### How each dashboard section loads data today

| Page | Loader | Real files it reads | Simulated / placeholder parts |
| --- | --- | --- | --- |
| Overview | `services/spill_loader.py` | `outputs/spills.geojson` (optional) | Without it, four simulated spill sites (`mock_data.MOCK_SPILL_SITES`, GOG-SIM-01 = 25.85 N, 55.65 E, the drift release point). The headline numbers are labelled simulated if any stage is. |
| 01 Detect | `services/detection_loader.py`, `report_loader.py`, `inference.py` | `outputs/detection/metrics.json` (or `summary.json`), `outputs/report/` (per-image CSV, galleries), `<image_id>_{image,mask,overlay}.png` from a real U-Net run in a subprocess | The incident location and the slick outline on the map are always simulated (the images are not georeferenced). The simulated fallback when no model is available is the demo scene. |
| 02 Predict | `services/drift_loader.py` | `outputs/drift/drift.geojson`, `meta.json` | With a spill selected, the drift is moved so its release point sits on that spill (`scenario.selected_drift`) and is always labelled simulated. Without `outputs/drift/`, the demo scenario. |
| 03 Respond | `services/routing_loader.py` | `outputs/routing/routes.geojson`, `summary.json`, `targets.geojson` | With a spill selected, the plan is moved with the drift and labelled simulated. Without `outputs/routing/`, the demo plan. |

### Real outputs on this machine

**Detection (Team A).**

| Item | Path | Format |
| --- | --- | --- |
| U-Net checkpoint | `checkpoints/unet_best.pth` (31.4 MB, git-ignored) | PyTorch; SHA-256 `f6ee7c36…939b`, matches `docs/detection_model_card.md` |
| Overall metrics | `outputs/detection/metrics.json` | Flat JSON: `model` ("U-Net (unet_refined_sar)"), `split` ("val"), `n_images` (1615), `threshold` (0.5), `dice` 0.8689, `iou` 0.7682, `precision` 0.8459, `recall` 0.8932 |
| Report summary | `outputs/report/summary.json` | `threshold`, `n_images`, `n_with_oil` (1539), `n_empty_reference` (76), `micro` {4 scores}, `macro_images_with_oil` {4 scores}, `threshold_sweep` {"0.10".."0.90": {4 scores}} |
| Per-image metrics | `outputs/report/per_image_metrics.csv` | Columns `file, ref_oil_pixels, dice, iou, precision, recall`; 1,615 rows (validation split), no NaN, no duplicates |
| Galleries | `outputs/report/gallery_{best,median,worst}.png` | 1024 × 1134 RGB; 4 rows of input, reference, prediction, errors (green TP, red FP, blue FN) |
| Prediction examples | `outputs/detection/<image_id>_{image,mask,overlay}.png` + `_run.json` | Written by the dashboard's real model runs (`detection/predict_cli.py`); mask = 8-bit grey PNG at the input size, values {0, 255}, white = oil |
| Radar images | `assets/images/train/` (6,455 PNG), `assets/images/val/` (1,615 PNG) | 256 × 256 Refined Deep-SAR SOS crops; `sentinel_*` / `palsar_*`. Only `train/palsar_0..9.png` are tracked in Git |
| Docs | `docs/detection_model_card.md`, `detection_evaluation.md`, `prediction_review.md` | Text; the unmerged `prediction-review` branch adds findings on the galleries |

**Drift (Team B).** No result files on this machine (see Missing). From the code merged on `main` and `drift/README.md`, Maqqavi's run `openoil-25.85N-55.65E-20261023T1200Z` exists on the team SharePoint (`Team B - Drift / Gulf drift 24h - 2026-10-23`: `drift.geojson`, `meta.json`, `drift_snapshots_0_6_12_24h.png`) with:
- `drift.geojson`: per hour 0 to 24 (25 steps), one `MultiPoint` feature per status with properties `hours` (int), `timestamp` ("2026-10-23T12:00:00Z" style), `kind: "particles"`, `status`, `particle_ids`, `oil_volume_m3` (pure oil), `synthetic: true`; plus one `Polygon` per hour with `kind: "envelope"`, `status: "active"`. Coordinates `[lon, lat]`, 5 decimals; 1,000 particles.
- `meta.json`: `simulation_id`, `synthetic`, `note`, `initial_location` {latitude, longitude}, `positions` [{timestamp, coordinate{latitude, longitude}}] (hourly centre of the oil afloat), `duration_hours`, `start_time`, `model` ("OpenDrift 1.14.12 OpenOil"), `oil_type`, `n_particles`, `release_volume_m3` (300), `oil_volume_basis`, `wind_source`, `current_source`, `wind_speed_m_per_s`, `wind_from_deg`, `current_speed_m_per_s`, `current_to_deg`, `assumptions` {object}, `oil_afloat_m3_at_end`, `summary_by_hour` [list].
- Forcing (documented, SHA-256 in `drift/README.md`): `data/raw/era5_wind_gulf_2026-10-19_26.nc` (ERA5 `u10`, `v10`, 0.25°, time `valid_time`), `data/raw/cmems_currents_gulf_2026-10-19_26.nc` (Copernicus `uo, vo, utide, vtide, vsdx, vsdy, utotal, vtotal`, 1/12°), cleaned to `data/processed/wind_clean.nc` and `currents_clean.nc` (CF names `x_sea_water_velocity`, ..., Stokes drift kept). Region lon 55.0 to 57.0 (currents to 56.917), lat 24.75 to 27.0; 19 to 26 Oct 2026 UTC, hourly.

**Cleanup (Team C).** No result files on this machine. From the code on `main`:
- `optimization/run_drift_plan.py` reads `outputs/drift/`, plans for moving oil and the nearest-interception baseline, and writes `outputs/routing/routes.geojson`, `targets.geojson`, `summary.json`, `comparison.json` and `outputs/routing/baseline/` (same three files). The unmerged `routing-model` branch says it was run on Maqqavi's files ("patches followed by their particle ids").
- `optimization/run_demo.py` writes the same files from a fixture (`optimization/fixtures/gulf_standard.json`, `gulf_drift_t12.json`, `constrained_triage.json`, `smoke_test.json`); these are labelled synthetic.
- Field names: routes `vessel_id`, `assigned_target_ids`, `estimated_distance_km`, `estimated_travel_hours`, `oil_collected_m3`, `cleanup_hours`, `finish_hours`, `speed_m_per_s`, `capacity_m3`, `available_hours`, optional `sea_path`; targets `target_id`, `oil_volume_m3`, `served_by`, `source_hours`, plus `meet_hours` etc. for moving oil; summary `status`, `message`, `synthetic`, `scenario_id`, `idle_vessel_ids`, `unserved_target_ids`, `source_hours`; `comparison.json` `optimized` / `baseline` {status, message, assignments, rule_violations} and `metrics` (`baseline_distance_km`, `baseline_travel_hours`, `baseline_targets_covered`, `baseline_oil_recovered_m3`, `baseline_response_hours`, ... and the optimized counterparts).

### How simulated data is labelled in the UI

- One status per page, wording in `dashboard/components/labels.py` (`STAGE_STATUS`): **"Live data"**, **"Simulated scenario"** (demo on, or any file with `"synthetic": true`), **"Real detection, simulated location"** (Detect only: a real U-Net mask on a real image, location and outline simulated), **"No data yet"**. The chip is next to each page title, and the top-bar timeline dot uses the same states.
- Overview: a "Simulated scenario" chip on the hero and on the headline numbers ("These numbers come from a simulated scenario, not from observations") when any stage is simulated; spill sites are "Simulated spill site" in the legend.
- Detect: a Real / Simulated box lists which parts are real (radar image, U-Net mask, per-image score) and which are simulated (location, outline on the map); "Simulated outline at the selected spill" above the map.
- Predict: tile "Simulated particles"; "How to read this" says the dots are simulated oil parcels. Respond: a status chip from `summary.json`.
- With a spill selected, Predict and Respond are always "Simulated scenario" (moved results).

---

## Missing

| Team | Missing on this machine / in the repo | Effect |
| --- | --- | --- |
| Drift | `outputs/drift/drift.geojson`, `meta.json` (only on SharePoint, which this audit could not open) | Predict shows the demo scenario; the drift integration cannot be tested here yet |
| Drift | `data/raw/*.nc`, `data/processed/wind_clean.nc`, `currents_clean.nc` | Not needed by the dashboard (it never runs OpenDrift); needed only to re-run the simulation |
| Drift | `drift_snapshots_0_6_12_24h.png` | Optional; the dashboard draws the snapshots itself |
| Drift | Real release point and time from a detection | Expected: images are not georeferenced, so the release stays synthetic (25.85 N, 55.65 E, 2026-10-23 12:00 UTC) |
| Cleanup | `outputs/routing/` (all files, incl. `comparison.json`, `baseline/`) | Respond shows the demo plan; needs `run_drift_plan` with OR-Tools on the real drift files (Haris has run it) |
| Cleanup | `data/land/ne_10m_land.shp` (Natural Earth) | Without it routes are straight lines that may cross land, and every plan's message says so |
| Detection | Ground-truth masks on disk (`detection/masks/val` per `report.py`) | Only visible inside the galleries; no per-image reference mask can be shown next to the prediction |
| Detection | `spill.geojson` / `oil_coordinates` | No georeferencing: the slick on the map is a simulated placeholder |
| Detection | `checkpoint_sha256`, `created`, `split` in `summary.json`, a `split` column in the CSV | The dashboard can't verify which checkpoint was scored ("The report doesn't say which checkpoint was scored"); per-image scores rely on `metrics.json`'s `split` |
| All | `outputs/spills.geojson` | Overview uses the four simulated sites (by design until real incidents exist) |

---

## Format Mismatches

Read from the merged code and the files on this machine; drift and routing items are from the exporters' code because their result files are not here. "Effect" is what a viewer would see today if the real files were copied into `outputs/`.

### Detection → Detect page

| # | Dashboard expects | Real files provide | Effect | Fix (owner) |
| --- | --- | --- | --- | --- |
| A1 | Oil polygons in WGS84 (`spill.geojson`, `DetectionOutput.oil_coordinates`) | Pixel masks only, no CRS or transform | Map outline is a simulated placeholder; labelled "Real detection, simulated location". Correct as labelled | None until georeferenced scenes exist (Team A) |
| A2 | Per-image rows that say their split (`split` column or `val/x.png`) | `file` is a bare name; `train/` and `val/` reuse names | Works only because `metrics.json` has `"split": "val"`; with `summary.json` alone, no image gets a score | Add `split` to the CSV (Team A) |
| A3 | `checkpoint_sha256`, `created` in `metrics.json` / `summary.json` | Neither; `metrics.json` is hand-written (flat), not `evaluate.py` output; `model` is a run name | "The report doesn't say which checkpoint was scored" | Add the hash and date (Team A) |
| A4 | `split` in `summary.json` | Missing | If `summary.json` is the only file: "The report doesn't say which images were scored" | Add `split` (Team A) |
| A5 | Precision for an image with no prediction | `0` (0/0 written as 0) | Shown as "—" with "precision is undefined" (handled) | — |
| — | Mask encoding and size | 8-bit PNG, {0, 255}, input size (256 × 256); model resizes to `image_size` 256 and back | Compatible (`> 127` = oil) | — |

### Drift → Predict page

| # | Dashboard expects | Real files provide | Effect | Fix (owner) |
| --- | --- | --- | --- | --- |
| B1 | Every `Point` / `MultiPoint` is oil on the water | One feature per `status` per hour (`active`, and `stranded`, `evaporated`, ... when they occur) | Non-active particles would be drawn and counted as oil. No effect on the agreed run (all 1,000 stay afloat), wrong for any run with stranding | Dashboard: draw / count only `status: "active"` (Obeid) |
| B2 | A few forecast steps (`DRIFT_HORIZONS_HOURS` = 6, 12, 24 as defaults) | 25 hourly steps, 0 to 24 h | The "Forecast time" selector becomes a row of 25 buttons (layout), default 6 h | Dashboard: offer 0 / 6 / 12 / 24 by default, the rest on demand (Obeid) |
| B3 | `synthetic: true` = "Simulated scenario" | `synthetic: true` because the **release** is synthetic, while the forecast is a real OpenDrift run on real ERA5 + Copernicus forcing | Page says "Simulated scenario", the same as the hand-made demo; the real model run is not distinguished | Dashboard: a "Real model, synthetic release" state like Detect's mixed state (Obeid; wording to agree) |
| B4 | Selected-spill flow moves the drift to the chosen site | A forecast valid only for its release point and forcing | GOG-SIM-01 coincides with the release (no shift); GOG-SIM-02 to 04 would show the real forecast moved 20+ km, under different currents | Dashboard: don't move a real forecast; offer it only for its own release site (Obeid) |
| B5 | `meta.json` descriptive fields | Extra `note`, `assumptions` {…}, `summary_by_hour`, `release_volume_m3`, `oil_volume_basis`, `oil_afloat_m3_at_end` | Ignored: the assumptions (28 °C, salinity 40, diffusivity 10 m²/s, seed) and oil afloat are not shown | Dashboard: show assumptions and oil afloat per hour (Obeid) |
| B6 | — | `oil_volume_m3` is pure oil; emulsion is about 3× larger at 24 h | Not shown today; any volume shown must say "pure oil" | Wording when added (Obeid) |
| — | `hours` numeric, `timestamp` UTC "…Z" = start + hours, `[lon, lat]`, `positions` strictly increasing | Same | Compatible (Maqqavi checked with the dashboard loader: no warnings) | — |

### Cleanup → Respond page

| # | Dashboard expects | Real files provide | Effect | Fix (owner) |
| --- | --- | --- | --- | --- |
| C1 | `LineString` = start, then stops in order (`dashboard/README.md`) | Start, stops, then **back to the start port** | The home port gets a stop marker at both ends; the visiting order looks one stop longer | Dashboard: drop a final point equal to the start (Obeid) |
| C2 | "Response time" = max `estimated_travel_hours`, tooltip "Until the last vessel completes its route" | `estimated_travel_hours` = sailing only, return trip included; `finish_hours` = sailing + cleanup | Headline number and tooltip disagree (open issue I6 / decision D2) | Decide D2 (Omar), then read `finish_hours` or reword (Obeid) |
| C3 | Straight segments between stops | `sea_path` [[lon, lat], …] around land, when land data was used | Routes drawn through land | Dashboard: draw `sea_path` when present (Obeid) |
| C4 | — | `unserved_target_ids`, `idle_vessel_ids` (summary), `served_by` (targets) | Unserved oil is invisible (I7) | Dashboard: show unserved targets and which vessel serves each (Obeid) |
| C5 | — | `comparison.json` (optimized vs nearest-interception baseline: distance, hours, targets covered, oil recovered, response hours) and `baseline/` | The baseline comparison, the key result of Team C, is not shown anywhere | Dashboard: comparison panel, optional baseline map toggle (Obeid) |
| C6 | — | `summary.json` `message` lists every assumption in plain words (dispatch 6 h, straight lines, placeholder volume) | Only the status chip is shown | Dashboard: show the message (Obeid) |
| C7 | `targets.geojson` at fixed positions, `source_hours` | Targets at the **meeting** positions, `meet_hours`, `source_hours` | `source_hours` is used to pick the oil layer (compatible); `meet_hours` ignored | Optional: show meeting time (Obeid) |
| — | `status` in the five schema values, `[lon, lat]`, km, h, m³ | Same | Compatible (verified in `docs/integration_plan.md` §3) | — |

---

## Recommended Integration Order

1. **Drift files into `outputs/drift/` (no code).** Copy Maqqavi's `drift.geojson` and `meta.json` from SharePoint. Check with `python tests/check_outputs.py outputs --gulf` and the dashboard's Diagnostics (no loader warnings expected). Drift comes first because routing is planned from it and because B1, B3 and B4 change what the Predict page claims.
2. **Dashboard: Predict fixes B1, B3, B4, then B2, B5.** Active particles only; a label that tells a real OpenDrift run with a synthetic release apart from the demo; no moving a real forecast to other sites; fewer default steps; assumptions shown. Ask before choosing the wording for B3.
3. **Routing files into `outputs/routing/` (Haris runs `python -m optimization.run_drift_plan` on the same drift files, with the Natural Earth land file).** Check with `check_outputs.py --gulf`. The unmerged `routing-model` branch has the setup steps; merging it first keeps the docs in line.
4. **Dashboard: Respond fixes C1, C3, C4, C6, then C5.** Return-to-port stops, sea paths, unserved targets, the plan's message, then the optimized-vs-baseline comparison from `comparison.json`. C2 waits for decision D2.
5. **Detection metadata from Team A (A2, A3, A4).** A `split` column in the CSV, `checkpoint_sha256` and `created` in `metrics.json`, `split` in `summary.json`. The Detect page already shows real results; these only remove caveats. Optional: a few reference masks next to the predictions.
6. **End-to-end check.** `python -m unittest discover -s tests`, `python tests/check_outputs.py outputs --gulf`, `python dashboard/check_schema.py`, the dashboard tests, then one walk through Overview → Detect → Predict → Respond with the real files, checking that every page's label matches what is real.

Open decisions that block parts of this: **D2** response-time definition (Omar), the wording for a real forecast from a synthetic release (B3), and whether Overview should offer only the real release site while the forecast is real (B4).
