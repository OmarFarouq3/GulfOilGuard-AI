# Integration plan

Status checked against `main` at `b55431a` on 2 Nov 2026 and updated after the end-to-end test on 3 Nov 2026 (`docs/e2e_test_report.md`); decisions D1–D3 agreed with Omar on 3 Nov 2026 (section 5). This page describes the formats the teams actually use, how to check a handoff before opening a PR, and the open compatibility issues.

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
| H7 | Scenario files → routing | `optimization.scenario_io.load_scenario` reads both `optimization/fixtures/` and `tests/scenarios/` formats | Verified on all three files below |

Coverage rule for routing (answers the open question from day 1): when some targets cannot be served, the solver returns `feasible`, lists the skipped targets in `message`, and `dashboard_export` writes them to `unserved_target_ids` in `summary.json`. Full coverage is therefore not required, and `check_optimization(..., require_full_coverage=False)` stays the default.

## 3. How to check a handoff before a PR

From the repository root:

```powershell
python -m unittest discover -s tests -v            # all unit and contract tests
python tests/check_outputs.py outputs --gulf       # your result files, against both contracts
python dashboard/check_schema.py                   # dashboard demo and sample files
```

`tests/check_outputs.py` reads `outputs/detection`, `outputs/drift` and `outputs/routing`, builds the shared dataclasses from them, and runs `tests/contract_checks.py`. It also checks the links between teams: route targets exist in `targets.geojson`, targets come from a forecast hour present in `drift.geojson`, and drift timestamps equal release time + `hours`. A **problem** breaks a contract or makes the dashboard show nothing or a wrong value (exit code 1). A **note** is worth knowing before the demo. `--gulf` adds the regional box, which is the only check that catches a swapped `[longitude, latitude]` pair in GeoJSON. It needs the standard library only.

What was run on 2 Nov:

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests` on `main` (PyTorch, OR-Tools installed) | 63 tests pass |
| `python -m optimization.run_demo` on `gulf_standard`, `constrained_triage`, `abu_dhabi_offshore` | All `feasible`, rule check passed. Straight-line distances (no land file), labelled synthetic |
| Those routing files read back with `dashboard/services/routing_loader.py` | No loader warnings, no contract problems |
| `check_outputs.py --gulf` on the same routing files | No problems; notes I6, I7 |
| `check_outputs.py --gulf` on `dashboard/make_sample_outputs.py` output | No problems |
| Detection files in the format written by `evaluate.py` and `report.py`, read with `dashboard/services/detection_loader.py` | No metrics shown, no warning (I1) |
| `trajectory_to_targets` on a contract-valid `DriftOutput` (0/6/12/24 h) | 1 target at 12 h (I4) |

## 4. Compatibility issues

Status on 3 Nov 2026 (end-to-end test, `docs/e2e_test_report.md`): **resolved** I1 (`metrics.json` shared in the dashboard format), I4 (particles in `drift.geojson`, Team C clusters one forecast hour), I5 (`source_hours` written), I8 (drift and routing use the northern UAE region), I9 (D3 moved to 23 Oct 12:00 UTC, the time the drift run uses), I10 (drift README updated). **Still open:** I2 (report E1), I6 (report E2), I7 (report E7). The report lists the issues found in the test (E1–E7) with owners and priorities.

| ID | Between | What happens | Evidence | Proposed fix | Owner | Blocks today's milestone |
| --- | --- | --- | --- | --- | --- | --- |
| I1 | Detection → dashboard | Metric tiles stay empty and no warning appears. `evaluate.py` writes the scores under `"metrics"` and `report.py` under `"micro"`; the dashboard reads `dice`, `iou`, `precision`, `recall` at the top level only | Section 3 | Write `outputs/detection/metrics.json` with the four scores at the top level, plus `"split": "val"` and the limitations text. Keep the existing reports as they are | Ayham, with Obeid | Yes: "masks and metrics for the dashboard" |
| I2 | Detection → dashboard | No detection code writes to `outputs/detection/`. `evaluate.py` defaults to `outputs/unet_validation/`, `report.py` to `outputs/report/`. `predict --output-dir outputs/detection` writes `<id>_mask.png` but not the input scene, so the page shows the mask without the radar image | Code review | Export step that writes `<id>_mask.png` and `<id>_image.png` (the overlay is built from these) to `outputs/detection/` | Ayham | Yes |
| I3 | Detection → drift | No oil coordinates, so drift cannot start from a detection | `docs/literature_review.md` §2; `shared/README.md` | Expected. Drift `meta.json` must carry `"synthetic": true` while the release point is synthetic; `check_outputs.py` adds a note if not | Maqqavi | No |
| I4 | Drift → routing | `DriftOutput` holds one track with strictly increasing timestamps, so it cannot hold a particle distribution at one hour. On a valid `DriftOutput`, `trajectory_to_targets` returns 1 target per forecast time. The dashboard validator and `contract_checks` also differ: the dashboard accepts equal timestamps, the contract checks do not | Section 3 | **Agreed (D1):** particles in a separate file, `DriftOutput` unchanged; Team C clusters the particles of one forecast hour into targets. The timestamp rule stays strictly increasing, so particles never go into `DriftOutput.positions` | Maqqavi (particle file), Nihal (clustering) | Yes, until both parts exist |
| I5 | Routing → dashboard | `targets.geojson` has no `source_hours`, so the Respond page assumes the 12 h drift layer under the routes | `dashboard_export.py` | Once targets come from drift, write `source_hours` = the forecast hour used | Harris, Nihal | No |
| I6 | Routing → dashboard | "Response time" (Overview and Respond) is the longest `estimated_travel_hours`, which is sailing only. `dashboard_export` also writes `finish_hours` (sailing + cleanup) | `gulf_standard`: 2.85 h shown, last vessel finishes at 8.69 h | **Agreed (D2):** the main metric is the largest `finish_hours` (8.69 h on `gulf_standard`); sailing time is shown separately (2.85 h), each with a clear label | Obeid | No, but it changes a headline number in the pitch |
| I7 | Routing → dashboard | Unserved targets are not shown. `constrained_triage` serves 2 of 4 targets with status `feasible`; `summary.json` lists the other two in `unserved_target_ids`, which the dashboard does not read | Section 3 | Show unserved targets (and `served_by` on the target markers) on the Respond page | Obeid | No |
| I8 | Scenarios ↔ forcing region | The environmental data covers lon 55.0–57.0. `tests/scenarios/abu_dhabi_offshore.json` (lon 52.7–54.7) and the dashboard demo scenario (map centre 24.5°N, 54.0°E) lie outside it, so they cannot be driven by real forcing. Team C fixtures and the drift release point are in the covered northern UAE / RAK area | `drift/environmental_data.py`, `dashboard/config.py` | Use the RAK area for the end-to-end demo. Add a RAK scenario to `tests/scenarios/` once the drift run exists | Maria, Obeid | No |
| I9 | Environmental data → drift | Release time needed inside the data window (19 Oct 00:00 – 26 Oct 23:00 UTC) | `drift/DATA_SOURCES.md` | **Resolved (D3):** 23 Oct 2026 12:00 UTC, used by the drift run and inside the data window | Joud, Maqqavi | No |
| I10 | Docs | `drift/README.md` still says `environmental_data.py` raises `NotImplementedError`; it is implemented | Code review | Update the README | Joud | No |

## 5. Decisions (agreed 3 Nov 2026)

**D1. Particle distribution (I4).** Keep the oil particle positions for each forecast timestamp in a separate output file, and keep `DriftOutput` as it is in `shared/schemas.py`. Team C builds cleanup targets by clustering the particles from one selected forecast time, and records that hour as `source_hours` in `targets.geojson`.
- The dashboard already reads particles from `outputs/drift/drift.geojson` (`MultiPoint` features with `hours`, `timestamp` and `"kind": "particles"`), so that file is the proposed home for them. `check_outputs.py` reports the particle count per hour.
- `meta.json` keeps the single centre track as `DriftOutput`; its timestamps stay strictly increasing.

**D2. Response time (I6).** The main response metric is the estimated cleanup completion time: sailing plus cleanup, the largest `finish_hours` over all vessels (8.69 h on `gulf_standard`). Sailing time is shown separately (2.85 h on `gulf_standard`), and both carry clear labels. The pitch quotes the completion time.

**D3. Release time (I9).** The first 24-hour Gulf simulation starts on **23 Oct 2026 at 12:00 UTC** from the synthetic point 25.85°N, 55.65°E, so the forecast steps are 23 Oct 12:00, 23 Oct 18:00, 24 Oct 00:00 and 24 Oct 12:00 UTC. Omar first agreed 20 Oct 12:00 UTC and changed it to 23 Oct on 3 Nov, because the drift run, the routing plan and its validation already used 23 Oct. Both are synthetic test dates inside the data window (19 Oct 00:00 – 26 Oct 23:00 UTC).

To check a drift output against D3: `python tests/check_outputs.py outputs --gulf --release 2026-10-23T12:00:00Z`.

## 6. Rules that still apply

- Synthetic inputs and fixture outputs are labelled (`"synthetic": true`) and never presented as real detection, drift or optimization results.
- A real pipeline run stops at detection while `oil_coordinates` is `None`. The release point and UTC release time come from a verified source or are labelled synthetic.
- Do not change shared fields without coordinating every consumer; `dashboard/README.md` lists fields that are dashboard-only extensions.
- Never commit imagery, masks, checkpoints, NetCDF files, credentials or generated `outputs/`.
- Workflow: work on your own branch, merge the latest `main` into it and resolve conflicts locally, run the checks in section 3, then open a PR for Omar to review. Record tested package versions after a successful setup; OpenDrift may need its own conda environment.
