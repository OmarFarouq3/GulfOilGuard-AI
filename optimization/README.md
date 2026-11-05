# Cleanup Optimization (Team C)

Optimizes vessel routes and resource allocation to respond to marine oil spills. Consumes `Vessel` and `ResponseTarget` dataclasses, and exports `OptimizationOutput` (routes, feasibility status, metrics).

---

## 1. Modules & Architecture

```text
Team B (OpenDrift, Maqqavi)                 Scenarios & Fixtures (scenario.py, Nihal)
outputs/drift/  ──► drift_targets.py              │  vessels (fleet)
                    patches followed in time      │
                           │                      ▼
                           └──────► moving_targets.py ──► Routing Model (OR-Tools, Haris)
                                    re-plan loop for      routing_model.py
                                    MOVING oil + moving   capacity, shift, cleanup time
                                    baseline                     │
                                           │      Sea Grid Navigation (Dijkstra, sea_grid.py)
                                           ▼
                         evaluate_routes.py ──► dashboard_export.py ──► outputs/routing/ (Obeid)
```

Two entry points: `run_demo.py` (a scenario file with fixed targets) and `run_drift_plan.py`
(a drift forecast: the targets move with the oil). Section 3 lists exactly what each team
must provide or can read.

### Module Breakdown:

* **`scenario.py` (Nihal)**:
  * **Arabian Gulf Infrastructure**: Regional port depots (`GULF_DEPOTS`) covering Port Saqr (RAK), RAK Maritime City, Hamriyah (Sharjah), Jebel Ali (Dubai), Mina Zayed (Abu Dhabi), Ras Laffan (Qatar), and Jubail / Ras Tanura (Saudi Arabia).
  * **Demonstration Scenarios**: Staged in **Ras Al Khaimah (RAK)** coastal waters to directly match Joud & Maqqavi's OpenDrift spill simulation.
  * **Marine Navigation Math**: Haversine distance (`haversine_distance_km`), speed/travel time calculator (`compute_travel_time_hours`), and distance/time matrix builders (`build_distance_matrix`, `build_time_matrix`).
  * **Drift Translation Bridge**: `create_synthetic_gulf_drift()` generates a 24-hour simulation at agreed coordinates (25.85° N, 55.65° E) across 0, 6, 12, and 24 h. `trajectory_to_targets()` aggregates oil patches at a specific forecast timestamp into discrete cleanup targets with estimated volumes ($m^3$), ensuring the same moving slick is not double-counted across different time steps. `create_gulf_drift_scenario()` pairs the T+12h targets with the RAK fleet.
  * **JSON Serialization**: `export_scenario_to_json()` and `load_scenario_from_json()`.

* **`fixtures/` (Ras Al Khaimah Demonstration Files)**:
  * `smoke_test.json`: 2 vessels at Port Saqr (RAK), 4 targets offshore RAK (fast debug).
  * `gulf_standard.json`: 3 vessels (Port Saqr & Hamriyah reserve), 10 targets along the RAK drift path (main demo fixture).
  * `gulf_drift_t12.json`: 3 vessels, 8 targets derived from the 24-hour Gulf drift simulation at T+12h (25.85° N, 55.65° E release).
  * `constrained_triage.json`: 2 vessels vs 4 high-volume targets, testing solver drop penalties and coastal prioritization.

* **`routing_model.py` (Haris)**:
  * Google OR-Tools Vehicle Routing Problem (VRP) solver.
  * Enforces vessel capacity ($m^3$, counted as **emulsion** for drift targets: weathered oil takes up sea water, so a tank fills with oil / (1 − water fraction), see 3.1), maximum shift duration (`available_hours`), service/skimming time, and **return to port**: every vessel sails back to the position it started from, which is taken as its home port because the shared schema has none (agreed with the team lead). The trip back counts for distance, sailing time and the shift limit. **One trip per vessel**: a vessel fills its tank at most once (no unloading and going out again).

* **`drift_targets.py`, `moving_targets.py`, `run_drift_plan.py` (Haris)**: planning for oil that drifts:
  * `drift_targets.py` reads Maqqavi's `outputs/drift/` files, cuts the oil into patches when the vessels leave (the dispatch hour) and follows each patch through every later forecast step (`PatchTrack`).
  * `moving_targets.py` sails each leg to where the patch **will be** when the vessel arrives (interception), wraps OR-Tools in a re-planning loop, and runs the baseline against the same moving oil.
  * `run_drift_plan.py` is the one command for all of it; `drift_standin.py` writes a clearly synthetic stand-in forecast for testing.

* **`sea_grid.py` & `sea_distance.py`**:
  * Dijkstra shortest-path router on a water/land raster grid, guaranteeing vessels navigate around landmasses, islands, and peninsulas.
  * Defaults to straight-line Haversine distance when sea raster data is unavailable.

* **`sea_check.py`**:
  * Visual diagnostic tool to verify all vessel and target coordinates lie in open sea and check water path feasibility.

* **`baseline.py` & `evaluate_routes.py`**:
  * Greedy nearest-neighbor heuristic baseline running under identical operational constraints.
  * Evaluates travel distance saved, operating hours saved, and cleanup coverage percentage.

* **`scenario_io.py` & `dashboard_export.py`**:
  * Interoperable loaders for both Nihal's (`fixtures/`) and Maria's (`tests/scenarios/`) JSON formats.
  * Formats GeoJSON route linestrings and cleanup timelines for Obeid's Streamlit dashboard.

* **`run_demo.py`**:
  * One-command CLI pipeline to solve a scenario, run baseline evaluation, and export the plan.

* **`validate_cleanup.py` (Nihal)**:
  * Checks a finished drift plan again from the raw files, with no OR-Tools needed: drift consistency, no oil counted twice, targets match the drift, fleet depots, tank and cleanup time (on the plan's `tank_basis`: emulsion, or pure oil for older plans), sailing time (distance / speed), `finish_hours` (sailing + cleanup), working hours, meeting times in order, return to port, every target either served or listed unserved, and every metric in `comparison.json` recalculated from the route and target files. Every line is OK, WARN or FAIL. See section 2F; the results are in `docs/cleanup_scenario_validation.md`.

---

## 2. Quickstart & Usage

### 0. Setup and the full Gulf run (start here)

Every command runs from the **repository root**. Needs Python 3.10 or newer.

**Step 1: environment (once).** `optimization/requirements.txt` is enough for routing; the root `requirements.txt` (torch, OpenDrift) is not needed. OR-Tools has no package for Python 3.15 yet, so use Python 3.10 to 3.13 for the venv (on macOS with Homebrew: `brew install python@3.13`, then `python3.13 -m venv .venv`).

```bash
python3 -m venv .venv
source .venv/bin/activate                 # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r optimization/requirements.txt
```

**Step 2: land data (once, recommended).** Download [`ne_10m_land.zip`](https://www.naturalearthdata.com/http//www.naturalearthdata.com/download/10m/physical/ne_10m_land.zip) (Natural Earth, public domain) and unzip it so that `data/land/ne_10m_land.shp` exists. Without it, routing still runs but uses straight lines that may cross land, and says so in every plan's message. The first run builds the sea grid (cached in `data/cache/`); later runs start fast. `data/` is not committed.

**Step 3: drift forecast.** Put the drift module's two files (Maqqavi's OpenDrift run, section 3.1) into `outputs/drift/`:

```text
outputs/drift/drift.geojson
outputs/drift/meta.json
```

`outputs/` is not committed, so get these from the drift module or the team. No drift files yet? Use the synthetic stand-in: `python -m optimization.drift_standin`, then add `--drift-dir optimization/examples/drift_standin` to step 4.

**Step 4: plan the cleanup.**

```bash
python -m optimization.run_drift_plan --fleet outputs/fleet/gulf_standard.json | tee outputs/part3_gulf_run.txt
```

`--fleet` is the vessel file the team shares (in `outputs/fleet/`, with the depots at the Port Saqr and Hamriyah harbour entrances); without it, `optimization/fixtures/gulf_standard.json` is used.

This reads the drift files, cuts the oil into patches when the vessels leave (6 h after release), follows each patch as it drifts, plans the vessel routes with OR-Tools and builds the nearest-first baseline against the same moving oil. It prints both plans and a comparison table. Check two printed lines:
- the third line must say `followed by their particle ids` (moving targets), not `STATIC`;
- an `emulsion:` line must show the water fraction (for example `46% at dispatch, 70% at 24 h`). Tanks and cleanup time are then counted as emulsion (oil plus the water it took up), and each route prints `tank <emulsion> / <capacity> m3`. If it says `tank use counted as pure oil` instead, `meta.json` has no `summary_by_hour` water fraction.

It writes (`outputs/routing/` is what the dashboard's Respond page reads):

| File | Content |
| --- | --- |
| `outputs/routing/routes.geojson` | one route per working vessel: port, stops in order, back to port |
| `outputs/routing/targets.geojson` | the oil patches, placed where each vessel meets its patch |
| `outputs/routing/summary.json` | status, every assumption in plain words, idle vessels, unserved targets |
| `outputs/routing/comparison.json` | optimized vs baseline: assignments, rule violations, metrics, drift details |
| `outputs/routing/baseline/` | the baseline plan as the same three files |

**Step 5 (optional): other dispatch times.** When the vessels leave is an assumption (6 h). To see how the comparison changes, write each run to its own folder so `outputs/routing/` stays the main plan:

```bash
python -m optimization.run_drift_plan --dispatch-hours 0  --dashboard-dir outputs/routing_d0
python -m optimization.run_drift_plan --dispatch-hours 12 --dashboard-dir outputs/routing_d12
```

Other options: `--drift-dir <folder>`, and `--pure-oil` to count tanks and cleanup as pure oil (the old behaviour, only to show the difference: that plan overfills the tanks once the water is counted). `python -m optimization.run_drift_plan --help` lists them all.

**The four demo sites.** Maqqavi's runs for the four locations (coordinates from Joud: S1 25.85 N 55.65 E, S2 25.70 N 55.40 E, S3 25.45 N 55.35 E, S4 25.98 N 55.85 E) come from the team SharePoint in `outputs/sites/S1 … S4/drift/`. Plan each one into its own `routing/` folder:

```bash
for s in S1 S2 S3 S4; do
  python -m optimization.run_drift_plan --drift-dir outputs/sites/$s/drift \
      --dashboard-dir outputs/sites/$s/routing --fleet outputs/fleet/gulf_standard.json \
      | tee outputs/sites/$s/routing.txt
done
```

(Windows PowerShell: `foreach ($s in "S1","S2","S3","S4") { python -m optimization.run_drift_plan --drift-dir outputs/sites/$s/drift --dashboard-dir outputs/sites/$s/routing --fleet outputs/fleet/gulf_standard.json | Tee-Object outputs/sites/$s/routing.txt }`)

**Step 6: tests.**

```bash
python -m pytest tests/test_scenario.py tests/test_optimization_*.py -q
```

These are the routing tests only (`tests/test_model.py` is the detection model and needs torch). They run on built-in and stand-in data, so they pass without the drift files or the land data; they take about 2 minutes.

**Step 7: see it in the dashboard.** The dashboard has its own light requirements:

```bash
python -m pip install -r dashboard/requirements.txt
python dashboard/check_schema.py
streamlit run dashboard/app.py            # then open 03 Respond
```

### A. Load a Scenario in Python

```python
from optimization.scenario import build_distance_matrix, load_scenario_from_json

# Load the Ras Al Khaimah operational scenario
vessels, targets = load_scenario_from_json("optimization/fixtures/gulf_standard.json")

# Build NxN distance matrix for routing
all_coords = [v.location for v in vessels] + [t.location for t in targets]
dist_matrix_km = build_distance_matrix(all_coords)
```

### B. Generate Python Scenario Objects

```python
from optimization.scenario import (
    create_smoke_test_scenario,      # 2 vessels, 4 targets in RAK
    create_rak_standard_scenario,    # 3 vessels, 10 targets in RAK (aliased as create_gulf_standard_scenario)
    create_gulf_drift_scenario,       # 3 vessels, 8 targets derived at T+12h from 24h drift simulation
    create_gulf_wide_scenario,        # Regional UAE / Qatar / Saudi scenario
    create_constrained_triage_scenario # Overcapacity triage test
)

vessels, targets = create_rak_standard_scenario()
# Or for the T+12h drift-derived scenario:
# vessels, targets = create_gulf_drift_scenario()
```

### C. Run the End-to-End Demo CLI

```bash
# Run solver on our RAK standard scenario
python -m optimization.run_demo --scenario optimization/fixtures/gulf_standard.json

# Run solver on the T+12h drift-derived scenario
python -m optimization.run_demo --scenario optimization/fixtures/gulf_drift_t12.json

# Run sea water check
python -m optimization.sea_check --scenario optimization/fixtures/smoke_test.json
```

### D. Plan from a Drift Forecast: Moving Oil (Phase 6)

```bash
# Real OpenDrift output (Maqqavi's drift.geojson + meta.json in outputs/drift/, see section 3.1)
python -m optimization.run_drift_plan --dispatch-hours 6

# For tests: a SYNTHETIC stand-in at the agreed start point 25.85 N, 55.65 E (not a simulation result)
python -m optimization.drift_standin
python -m optimization.run_drift_plan --drift-dir optimization/examples/drift_standin
```

What happens, in order:
1. **Patches at dispatch.** At `--dispatch-hours` (when the vessels leave port; default 6 h after the release, an ASSUMPTION in `config.py`), the oil is cut into patches: the drift module's `patch_id`, or ~3 km cells. The 15 largest become targets. Oil in the rest is reported as `untargeted_oil_m3`, never dropped silently.
2. **Patches move.** Each patch is followed through every later forecast step (same `patch_id`, or the same particle ids): its place is the oil-weighted centre and its oil is the sum of its particles. Between steps it moves in a straight line.
3. **Interception.** A vessel sails to where the patch **will be when it arrives**, not to where it is now. While it cleans, it drifts with the patch. A patch is only taken if the vessel can still sail back to its start port inside its shift afterwards; after its last patch it sails home.
4. **Re-planning.** OR-Tools only knows fixed points, so it plans to where each patch is at the guessed meeting time. The plan is then sailed against the moving oil, the guesses are updated, and it plans again until the solver aims within 2 km (about one sea-grid cell) of every real meeting place. At most 4 rounds; the best sailed round is kept. The kept plan always follows the rules **as sailed**.
5. **Baseline.** Nearest **interception** first, against the same moving oil, distances and rules.

Outputs in `outputs/routing/`: the usual three files (targets placed where each vessel meets its patch, with `meet_hours`), `comparison.json` and `baseline/`. See section 3.4.

If the drift files carry neither `patch_id` nor particle ids, the patches cannot be followed and stay where they were at dispatch. The run then prints and records **STATIC**.

### E. Run Unit Tests

```bash
python3 -m unittest tests/test_scenario.py
python -m pytest tests/test_optimization_phase1.py tests/test_optimization_phase2.py tests/test_optimization_phase3.py tests/test_optimization_phase4.py tests/test_optimization_phase5.py tests/test_optimization_phase6.py
```

### F. Validate a Cleanup Plan, and Re-run After a Change (Nihal)

`validate_cleanup.py` needs only the files: the drift run, the routing outputs and the fleet. No OR-Tools.

```bash
# the folders run_drift_plan writes (plan in outputs/routing/, baseline in outputs/routing/baseline/)
python -m optimization.validate_cleanup --json outputs/validation.json | tee outputs/validation.txt

# files shared by hand, e.g. from the OneDrive Team C folder (Optimized/, Baseline/, comparison.json)
python -m optimization.validate_cleanup --drift-dir outputs/maqqavi --routing-dir outputs/haris \
    --json outputs/validation.json | tee outputs/validation.txt
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--drift-dir` | `outputs/drift` | folder with `drift.geojson` and `meta.json` |
| `--routing-dir` | `outputs/routing` | the plan (`routes.geojson`, `targets.geojson`, `summary.json`) or `Optimized/`, plus optional `comparison.json` and `baseline/` or `Baseline/` |
| `--fleet` | `optimization/fixtures/gulf_standard.json` | the vessels **the plan was made with**. A plan made before the fleet changed needs that older file (on OneDrive: `Team C/Fleet/gulf_standard_old_depots.json`), otherwise its routes do not start at the vessels' ports and the check fails |
| `--synthetic-fixture` | `optimization/fixtures/gulf_drift_t12.json` | summarised in the JSON for the synthetic vs real comparison |
| `--json` | none | also write every check and number to this file |

**How to read it.** `OK` = the rule holds. `WARN` = allowed, but an assumption to state (for example the emulsion load of an older pure-oil plan, a patch wider than 1.5 km, an unserved target, a missing `comparison.json`). `FAIL` = a broken rule (oil counted twice, over a tank, over a shift, not back in port, a target served twice). The command exits with code 1 if anything fails.

**Change the depots or the fleet.** Edit `GULF_DEPOTS` or the scenario functions in `scenario.py`, then regenerate all four fixtures and check that every vessel is on water (needs the land file from step 0.2):

```bash
python -m optimization.scenario
python -m optimization.sea_check --scenario optimization/fixtures/gulf_standard.json --plot outputs/fleet_check.png
```

`sea_check` must not report any vessel as `on land ... moved`. If it does, move that depot further out along its harbour approach.

**Re-run everything after a new drift run or new coordinates** (for example a new release point or time, or new depots). Each step reads what the one before wrote:

| Step | Who | Command | Writes |
| --- | --- | --- | --- |
| 1. Drift | Maqqavi | `python -m drift.run_gulf_demo --lat <lat> --lon <lon> --start <UTC time>Z` | `outputs/drift/drift.geojson`, `meta.json` |
| 2. Fleet (only if depots or vessels changed) | Nihal | `python -m optimization.scenario` | `optimization/fixtures/*.json` |
| 3. Routing | Haris | `python -m optimization.run_drift_plan` | `outputs/routing/` (plan, `baseline/`, `comparison.json`) |
| 4. Validation | Nihal | `python -m optimization.validate_cleanup --json outputs/validation.json \| tee outputs/validation.txt` | `outputs/validation.json`, `outputs/validation.txt` |

The drift run needs OpenDrift and Joud's data files (see `drift/README.md`). Steps 2 to 4 only need `optimization/requirements.txt`. Then share the new `outputs/` files in the team OneDrive, because `outputs/` is not committed.

---

## 3. Interfaces with Other Teams (contracts)

This section is the source of truth for what the routing module **needs from** and **gives to** each team. It is written to be handed to a teammate or their coding agent as is. Paths are relative to the repository root. Coordinates are WGS84 degrees. Times are hours since the release, and timestamps are UTC with a `Z`. GeoJSON coordinates are `[longitude, latitude]`.

Status today: Maqqavi's OpenDrift run (`openoil-25.85N-55.65E-20261023T1200Z`: 1000 particles, hourly 0 to 24 h, release 2026-10-23 12:00 UTC) is delivered and meets 3.1. Copy its `drift.geojson` and `meta.json` into `outputs/drift/` and `run_drift_plan` uses it with no code change; the patches are followed by their particle ids. The synthetic stand-in (`optimization/examples/drift_standin/`) is kept for tests.

### 3.1 Maqqavi: drift simulation (OpenDrift) → `outputs/drift/`

Write the two files the dashboard already reads (`dashboard/README.md`, "Drift module"), **plus the routing fields marked below**. Extra properties are ignored by the dashboard, so they are safe to add.

**Run settings agreed with the team** (check with Joud, `drift/DATA_SOURCES.md`):
- release point **25.85 N, 55.65 E** (synthetic test point, not a detection result), Generic Medium Crude
- release time inside Joud's data window (2026-10-19 00:00 to 2026-10-26 23:00 UTC)
- duration at least **24 h**

**`outputs/drift/drift.geojson`**: a `FeatureCollection`. Each feature is the oil at one output time: a `MultiPoint` of particles (recommended) or one `Point` per particle. `Polygon` envelopes may be added for the dashboard; routing ignores them.

| Property | Needed by routing | Meaning |
| --- | --- | --- |
| `hours` | **required** | hours since release. **Output every 1 h** (OpenDrift `time_step_output` = 1 h) from 0 to 24 h. Any interval works, but between steps routing moves a patch in a straight line, so finer is better. 0, 6, 12 and 24 must be there for the dashboard. |
| `timestamp` | recommended | UTC, e.g. `"2026-10-19T06:00:00Z"`; must equal release time + `hours` |
| `particle_ids` (MultiPoint) / `particle_id` (Point) | **required for moving targets** (or `patch_id`) | the OpenDrift element number, **the same particle keeps the same id at every step**. One id per point, same order as the coordinates. |
| `patch_id` | optional, replaces the ids above | if you group particles into patches yourself: the id of the patch these points belong to, **stable across steps** (patch `"A"` at 6 h is the same oil as patch `"A"` at 7 h). Routing then uses your patches as the targets. |
| `status` | recommended | `"active"` = oil on the water. Anything else (`"stranded"`, `"evaporated"`, `"dispersed"` ...) is left out. One feature per status per step works well. Leaving non-active particles out of the file has the same effect. |
| `oil_volume_m3` | recommended | oil the feature holds at that step, in m³ (OpenDrift oil mass / oil density). Carries evaporation and dispersion into the plan. A MultiPoint's volume is shared equally between its points. |
| `kind` | optional | `"particles"` or `"envelope"` (dashboard) |
| `synthetic` | **required while the start point is synthetic** | `true` |

**`outputs/drift/meta.json`**:

| Field | Needed by routing | Meaning |
| --- | --- | --- |
| `simulation_id` | recommended | used in the plan's `scenario_id` |
| `start_time` | recommended | release time, UTC |
| `release_volume_m3` | **required if features have no `oil_volume_m3`** | total oil released. Without it, routing uses a 300 m³ placeholder and says so in the plan. |
| `n_particles` | recommended | particles released (for the per-particle share) |
| `summary_by_hour[].hours`, `summary_by_hour[].mean_water_fraction` | **recommended (emulsion)** | the slick-average water content of the oil at each output hour (OpenOil `water_fraction`, 0 to below 1). Needed for **every** drift step. Routing then fills tanks and times cleanup with the emulsion, oil / (1 − water fraction), at the hour the vessel meets the patch. Without it, tanks are counted as pure oil and the plan says so. |
| `oil_type`, `model`, `wind_source`, `current_source` | optional | descriptive (dashboard) |
| `synthetic` | **required** | `true` |

Smallest valid example (two steps, two particles, one stranding):

```json
{"type": "FeatureCollection", "features": [
  {"type": "Feature", "geometry": {"type": "MultiPoint", "coordinates": [[55.65, 25.85], [55.651, 25.851]]},
   "properties": {"hours": 6, "timestamp": "2026-10-19T06:00:00Z", "kind": "particles", "status": "active",
                  "particle_ids": [0, 1], "oil_volume_m3": 2.4, "synthetic": true}},
  {"type": "Feature", "geometry": {"type": "MultiPoint", "coordinates": [[55.66, 25.84]]},
   "properties": {"hours": 7, "timestamp": "2026-10-19T07:00:00Z", "kind": "particles", "status": "active",
                  "particle_ids": [0], "oil_volume_m3": 1.1, "synthetic": true}},
  {"type": "Feature", "geometry": {"type": "MultiPoint", "coordinates": [[55.70, 25.80]]},
   "properties": {"hours": 7, "timestamp": "2026-10-19T07:00:00Z", "kind": "particles", "status": "stranded",
                  "particle_ids": [1], "oil_volume_m3": 1.2, "synthetic": true}}
]}
```

How to get these from OpenDrift (check the names against your OpenDrift version): for each output time, take the particles' `lon`, `lat`, `status` and oil mass. The particle index (the trajectory number) is the `particle_id`. OpenDrift status `0` means active; `o.status_categories` names the others. Volume = oil mass (kg) / oil density (kg/m³).

**How to check your files work for routing:**
```bash
python -m optimization.run_drift_plan
```
The third line must say `followed by their particle ids` or `followed by the drift module's patch_id`. If it says `STATIC`, the ids are missing. The plan's `summary.json` message lists every assumption that had to be made, for example a missing `release_volume_m3`.

### 3.2 Joud: environmental data

Nothing extra is needed. Routing only relies on `drift/DATA_SOURCES.md` for the release point (25.85 N, 55.65 E) and the time window. Please tell Haris and Maqqavi if either changes.

### 3.3 Nihal: fleet and scenarios

`run_drift_plan.py` takes the **vessels** from a scenario file (`--fleet`, default `optimization/fixtures/gulf_standard.json`). Its `targets` are ignored, because the targets come from the drift. Each vessel needs:

| Field | Unit | Note |
| --- | --- | --- |
| `vessel_id` | | unique |
| `location` `{latitude, longitude}` | degrees | the port or staging point. **The vessel also returns here at the end** (taken as its home port). Use a point in water that the 2.2 km sea grid also counts as water (check with `sea_check`), not a point on the quay: Port Saqr 25.9850 N, 56.0350 E (a staging point on the approach, because its entrance falls in a land cell) and Hamriyah 25.4773 N, 55.4798 E (its harbour entrance, from OpenStreetMap), see `GULF_DEPOTS`. A point on land is moved to the nearest water if that is within 15 km, and the plan's message says so |
| `speed_m_per_s` | m/s | transit speed |
| `capacity_m3` | m³ | recovered-oil tank |
| `available_hours` | h | shift, counted from dispatch: sailing out + cleanup + sailing back to `location` must fit |

Keep `"synthetic"` absent or `true` for made-up fleets (the dashboard then labels the plan "Simulated scenario"). Open questions for Nihal: (a) the dispatch delay (now 6 h after release, `DriftTargetConfig.dispatch_hours` in `config.py`); (b) a real per-vessel skimming rate (now 30 m³/h for every vessel, `recovery_rate_m3_per_hour`).

### 3.4 Obeid: dashboard ← `outputs/routing/`

**Nothing is required**: the Respond page already works with these files (checked with `dashboard/services/routing_loader.py`, no warnings). The fields below are **optional upgrades** the dashboard can pick up.

`targets.geojson`: each target is placed **where its vessel meets the patch** (unserved ones: where they were at dispatch).

| Property | Meaning |
| --- | --- |
| `source_hours` | the drift step whose oil layer fits these targets best (the step nearest the average meeting time). Already read by the dashboard. |
| `served_by` | vessel id, or `null` |
| `meet_hours`, `meet_time` | when the vessel reaches the patch (hours since release; UTC). `null` if unserved. |
| `drifted_km` | how far the patch moved between dispatch and that meeting |
| `position_hours` | the time the point's position is for |
| `emulsion_m3`, `water_fraction` | the patch as emulsion when it is met (`oil_volume_m3` stays pure oil). Only when the drift gives the water fraction. |

`routes.geojson` (per vessel): the `LineString` is the start, the stops in visiting order, then **the start again** (the vessel sails back to its port), so a working route has `len(assigned_target_ids) + 2` points and its last point equals its first. The Respond page currently draws a small "stop N" dot on that last point, on top of the base marker; to hide it, skip the last point when it equals the first. Distances and times include the trip back. Properties: `oil_collected_m3` (pure oil recovered), `emulsion_collected_m3` and `tank_used_percent` (what is in the tank: oil plus water; only when the drift gives the water fraction), `cleanup_hours` (skimming the emulsion when known), `finish_hours` (sailing + cleanup = when the vessel is back in port; **the response time is the largest `finish_hours`**, not the largest `estimated_travel_hours`), `sea_path` (`[[lon, lat], ...]` through water, for drawing around land, the trip back included).

`summary.json`: `status`, `message` (every assumption in plain words), `synthetic`, `scenario_id`, `idle_vessel_ids`, `unserved_target_ids`, `source_hours`.

`comparison.json`, for a "optimized vs nearest-first" panel:
```text
{ scenario_id, synthetic,
  optimized: { status, message, assignments: {vessel_id: [target_id, ...]}, rule_violations: [] },
  baseline:  { ...same... },
  metrics: { optimized_/baseline_ + oil_recovered_m3, response_hours, targets_covered, distance_km,
             travel_hours, longest_route_hours, distance_km_per_target;
             *_change_percent; total_oil_m3; same_targets_covered } | null,
  metrics_error (only when metrics is null),
  drift: { simulation_id, follow, dispatch_hours, dispatch_time, forecast_steps_hours,
           oil_afloat_at_dispatch_m3, targeted_oil_at_dispatch_m3, untargeted_oil_m3,
           tank_basis ("emulsion" | "pure oil"), water_fraction_by_hour | null, assumptions },
  replan_rounds, patch_drift_before_meeting_km: { optimized: {mean_km, max_km}, baseline: {...} },
  last_patch_cleaned_hours_after_dispatch: { optimized, baseline } }
```
`metrics.*response_hours` is the time until the last vessel is **back in port**. `last_patch_cleaned_hours_after_dispatch` is when the last patch is clean (the response time without the trip home). `drift`, `replan_rounds`, `patch_drift_before_meeting_km` and `last_patch_cleaned_hours_after_dispatch` appear only for drift runs (`run_drift_plan`).

`baseline/`: the baseline plan as the same three files, for a toggle on the map.

### 3.5 Maria: test scenarios

Nothing needed. Scenario files in `tests/scenarios/` (flat `latitude`/`longitude`) already load with `run_demo`.
