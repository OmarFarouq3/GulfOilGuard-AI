# Integration plan

Status on 3 Nov 2026, checked against `main` at `712323a` in the end-to-end test (`docs/e2e_test_report.md`), with the real team outputs for demo site S1. Decisions D1–D3 were agreed with Omar on 3 Nov 2026 (section 5). This page describes the formats the teams actually use, how to check a handoff before opening a PR, and the open compatibility issues.

Sources of truth:
- `shared/schemas.py` defines the shared dataclasses, coordinate order, UTC timestamps and units.
- `dashboard/README.md` ("Data contract") defines the result files under `outputs/` and their fields.
- This page does not repeat those field lists. It records who writes which file, what has been verified, and what is still open.

## 1. Pipeline as built

```text
SAR image ──► detection.evaluate / detection.report ──► outputs/detection/   ──► Detect page
                     │
                     └─ no georeferencing yet: no spill.geojson, no oil coordinates
                                  ⋮ (gap: drift starts from a synthetic release point)
ERA5 + Copernicus files ──► drift.environmental_data ──► wind_clean.nc, currents_clean.nc
                                                              │
synthetic release 25.85°N 55.65°E, 23 Oct 2026 12:00 UTC ──► drift.run_gulf_demo (OpenDrift) ──► outputs/drift/ ──► Predict page
                                                              │
                     optimization.drift_targets: particles cut into patches at dispatch, followed by particle id
                                                              │
vessels (optimization/fixtures/gulf_standard.json) ──► optimization.run_drift_plan ──► outputs/routing/ ──► Respond page
```

The dashboard only reads files; it never runs a model, simulation or solver. Every result file may carry `"synthetic": true`, and the dashboard then labels that page "Simulated scenario".

## 2. Handoffs

| # | From → to | What is handed over | Status on 3 Nov |
| --- | --- | --- | --- |
| H1 | Detection → dashboard | `outputs/detection/metrics.json`, `<image_id>_mask.png`, optional `<image_id>_image.png` | `metrics.json` shared in the right format; no mask or scene image, and no code in the repo writes `outputs/detection/` (report E1) |
| H2 | Detection → drift | `spill.geojson` polygons, read as `DetectionOutput` with `oil_coordinates` | **Not possible yet**: the dataset crops have no CRS or transform. Drift uses a synthetic release point (I3) |
| H3 | Environmental data → drift | `wind_clean.nc`, `currents_clean.nc`, from `drift.environmental_data` | Done (PR #6, #15). Region lon 55.0–57.0, lat 24.75–27.0; 19–26 Oct 2026 UTC, hourly. Read by OpenDrift in the 23 Oct run |
| H4 | Drift → dashboard | `outputs/drift/drift.geojson` (particles per hour, D1) and `meta.json` (`DriftOutput`) | Done (PR #19): 1,000 particles, hourly 0–24 h, outline polygons; passes the checker and the dashboard loader |
| H5 | Drift → routing | `ResponseTarget` list: patches of the particles at one forecast hour (D1) | Done (PR #20): `optimization.drift_targets` and `run_drift_plan`; verified on the 23 Oct run |
| H6 | Routing → dashboard | `outputs/routing/routes.geojson`, `summary.json`, `targets.geojson`, `comparison.json`, `baseline/` | **Compatible**, verified. Display gaps: response time (report E2) and unserved targets (I7, report E7) |
| H7 | Scenario files → routing | `optimization.scenario_io.load_scenario` reads both `optimization/fixtures/` and `tests/scenarios/` formats | Verified on 2 Nov on `optimization/fixtures/` and `tests/scenarios/` |
| H8 | Drift and routing → dashboard, per demo site | `outputs/sites/S1` to `S4`, each with `drift/` and `routing/` in the formats above | Team B has run all four sites (S1 25.85°N 55.65°E, S2 25.70°N 55.40°E, S3 25.45°N 55.35°E, S4 25.98°N 55.85°E); shared after Nihal's validation. The dashboard reads only `outputs/drift` and `outputs/routing` today, so it needs to read the selected site's folder (Obeid). At S3, 444 of 1,000 particles are stranded by 24 h |

Coverage rule for routing (answers the open question from day 1): when some targets cannot be served, the solver returns `feasible`, lists the skipped targets in `message`, and `dashboard_export` writes them to `unserved_target_ids` in `summary.json`. Full coverage is therefore not required, and `check_optimization(..., require_full_coverage=False)` stays the default.

## 3. How to produce and check the outputs

From the repository root. Each command writes the folder the next one reads:

```powershell
python -m detection.evaluate --checkpoint <best.pth> --image <scene>.png --output-dir outputs/detection   # <scene>_mask.png; copy the scene to <scene>_image.png
python -m drift.run_gulf_demo                      # outputs/drift/ (OpenDrift environment; cleaned data in data/processed/)
python -m optimization.run_drift_plan              # reads outputs/drift/, writes outputs/routing/ and comparison.json
python -m unittest discover -s tests -v            # unit and contract tests (needs pytest; drift tests need OpenDrift)
python tests/check_outputs.py outputs --gulf --release 2026-10-23T12:00:00Z
python tests/check_outputs.py outputs/sites/S3 --gulf --release 2026-10-23T12:00:00Z   # one demo site
```

`tests/check_outputs.py` reads the `detection`, `drift` and `routing` folders under the folder it is given, builds the shared dataclasses from them, and runs `tests/contract_checks.py`. It also checks the links between teams: route targets exist in `targets.geojson`, targets come from one forecast hour present in `drift.geojson`, and drift timestamps equal release time + `hours`. A **problem** breaks a contract or makes the dashboard show nothing or a wrong value (exit code 1); a **note** is worth knowing before the demo. `--gulf` adds the regional box, the only check that catches a swapped `[longitude, latitude]` pair in GeoJSON. `--release` checks the drift run against the agreed release time (D3). It needs the standard library only.

Results on 3 Nov, on a Windows laptop with the real outputs for site S1 (details in `docs/e2e_test_report.md`):

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests` | `main`: 109 pass, 14 drift tests skipped (no OpenDrift), after installing `pytest`. This branch: 115 pass, 14 skipped |
| `check_outputs.py outputs --gulf --release 2026-10-23T12:00:00Z` | Detection: no mask (E1). Drift: OK, release 23 Oct 12:00 UTC. Routing: OK; response time 2.70 h sailing vs 7.54 h with cleanup (E2); `T06` not served (E7) |
| Routing built from the same drift run | `scenario_id` `openoil-25.85N-55.65E-20261023T1200Z@dispatch6h` |
| Dashboard with the real outputs | All pages load; maps show; Detect shows Dice 0.87, IoU 0.77, precision 0.85, recall 0.89 |
| Dashboard with `outputs/detection/` missing, or `metrics.json` cut off | Empty state or a notice; no crash |

## 4. Compatibility issues

Summary of the table below (end-to-end test, `docs/e2e_test_report.md`): **resolved** I1 (`metrics.json` shared in the dashboard format), I4 (particles in `drift.geojson`, Team C clusters one forecast hour), I5 (`source_hours` written), I8 (drift and routing use the northern UAE region), I9 (D3 moved to 23 Oct 12:00 UTC, the time the drift run uses), I10 (drift README updated). **Still open:** I2 (report E1), I6 (report E2), I7 (report E7). The report lists the issues found in the test (E1–E7) with owners and priorities.

| ID | Between | Issue (found 2 Nov) | Status on 3 Nov | Owner |
| --- | --- | --- | --- | --- |
| I1 | Detection → dashboard | Scores nested in `metrics.json`, so the dashboard showed none | **Resolved:** the shared `metrics.json` has the four scores at the top level and the Detect page shows them | Ayham |
| I2 | Detection → dashboard | No code writes `outputs/detection/`; no mask or scene image | **Open** (report E1): export command in section 3 | Ayham |
| I3 | Detection → drift | Dataset scenes have no location, so drift cannot start from a detection | **Open, expected:** drift starts from a labelled synthetic point. Ayham is looking for georeferenced SAR scenes of the four demo sites | Ayham, Maqqavi |
| I4 | Drift → routing | `DriftOutput` cannot hold a particle distribution | **Resolved (D1, PR #19, #20):** particles in `drift.geojson`; `optimization.drift_targets` cuts them into patches at dispatch | Maqqavi, Nihal |
| I5 | Routing → dashboard | `targets.geojson` had no `source_hours` | **Resolved:** written (8 h in the S1 plan) | Harris |
| I6 | Routing → dashboard | Response time shows sailing time only | **Open** (report E2): decision D2 agreed, not yet on the dashboard; S1 shows 2.70 h, completion is 7.54 h | Obeid |
| I7 | Routing → dashboard | Unserved targets not shown | **Open** (report E7): `T06` in the S1 plan | Obeid |
| I8 | Scenarios ↔ forcing region | Some scenarios lay outside the wind and current data | **Resolved:** drift and routing use the northern UAE demo sites, inside the data | Maria, Obeid |
| I9 | Environmental data → drift | Release time needed inside the data window | **Resolved (D3):** 23 Oct 2026 12:00 UTC | Joud, Maqqavi |
| I10 | Docs | `drift/README.md` said the drift code was not implemented | **Resolved:** README rewritten with PR #19 | Maqqavi |

## 5. Decisions (agreed 3 Nov 2026)

**D1. Particle distribution (I4).** Keep the oil particle positions for each forecast timestamp in a separate output file, and keep `DriftOutput` as it is in `shared/schemas.py`. Team C builds cleanup targets by clustering the particles from one selected forecast time, and records that hour as `source_hours` in `targets.geojson`.
- Implemented in PR #19 and #20: the particles are in `outputs/drift/drift.geojson` (`MultiPoint` features with `hours`, `timestamp`, `particle_ids` and `"kind": "particles"`), which the dashboard already reads, and Team C builds the targets from them. `check_outputs.py` reports the particle count per hour.
- `meta.json` keeps the single centre track as `DriftOutput`; its timestamps stay strictly increasing.

**D2. Response time (I6).** The main response metric is the estimated cleanup completion time: sailing out, cleanup and the trip back to port (from dispatch), the largest `finish_hours` over all vessels (7.54 h in the S1 plan). Sailing time is shown separately (2.70 h in the S1 plan), and both carry clear labels. The pitch quotes the completion time.

**D3. Release time (I9).** The first 24-hour Gulf simulation starts on **23 Oct 2026 at 12:00 UTC** from the synthetic point 25.85°N, 55.65°E, so the forecast steps are 23 Oct 12:00, 23 Oct 18:00, 24 Oct 00:00 and 24 Oct 12:00 UTC. Omar first agreed 20 Oct 12:00 UTC and changed it to 23 Oct on 3 Nov, because the drift run, the routing plan and its validation already used 23 Oct. Both are synthetic test dates inside the data window (19 Oct 00:00 – 26 Oct 23:00 UTC).

To check a drift output against D3: `python tests/check_outputs.py outputs --gulf --release 2026-10-23T12:00:00Z`.

## 6. Rules that still apply

- Synthetic inputs and fixture outputs are labelled (`"synthetic": true`) and never presented as real detection, drift or optimization results.
- A real pipeline run stops at detection while `oil_coordinates` is `None`. The release point and UTC release time come from a verified source or are labelled synthetic.
- Do not change shared fields without coordinating every consumer; `dashboard/README.md` lists fields that are dashboard-only extensions.
- Never commit imagery, masks, checkpoints, NetCDF files, credentials or generated `outputs/`.
- Workflow: work on your own branch, merge the latest `main` into it and resolve conflicts locally, run the checks in section 3, then open a PR for Omar to review. Record tested package versions after a successful setup; OpenDrift may need its own conda environment.
