# Cleanup Optimization (Team C)

Optimizes vessel routes and resource allocation to respond to marine oil spills. Consumes `Vessel` and `ResponseTarget` dataclasses, and exports `OptimizationOutput` (routes, feasibility status, metrics).

---

## 1. Modules & Architecture

```text
Team B (OpenDrift) ───► trajectory_to_targets() ──┐
                                                  ▼
Scenarios & Fixtures (scenario.py) ──► Routing Model (OR-Tools) ──► Plan & Evaluator
(Nihal: RAK Demo & Gulf Depots)        (Haris: Capacity, Shift)    (evaluate_routes.py)
                                                  │                          │
                                    Sea Grid Navigation (A*)                 ▼
                                    (sea_grid.py: Water routing)    Dashboard Export (Streamlit)
```

### Module Breakdown:

* **`scenario.py` (Nihal)**:
  * **Arabian Gulf Infrastructure**: Regional port depots (`GULF_DEPOTS`) covering Port Saqr (RAK), RAK Maritime City, Hamriyah (Sharjah), Jebel Ali (Dubai), Mina Zayed (Abu Dhabi), Ras Laffan (Qatar), and Jubail / Ras Tanura (Saudi Arabia).
  * **Demonstration Scenarios**: Staged in **Ras Al Khaimah (RAK)** coastal waters to directly match Joud & Maqqavi's OpenDrift spill simulation.
  * **Marine Navigation Math**: Haversine distance (`haversine_distance_km`), speed/travel time calculator (`compute_travel_time_hours`), and distance/time matrix builders (`build_distance_matrix`, `build_time_matrix`).
  * **Drift Translation Bridge**: `trajectory_to_targets()` aggregates oil patches at a specific forecast timestamp (defaulting to the latest forecast horizon) into discrete, cleanable targets with estimated volumes ($m^3$), ensuring the same moving slick is not double-counted across different time steps.
  * **JSON Serialization**: `export_scenario_to_json()` and `load_scenario_from_json()`.

* **`fixtures/` (Ras Al Khaimah Demonstration Files)**:
  * `smoke_test.json`: 2 vessels at Port Saqr (RAK), 4 targets offshore RAK (fast debug).
  * `gulf_standard.json`: 3 vessels (Port Saqr & Hamriyah reserve), 10 targets along the RAK drift path (main demo fixture).
  * `constrained_triage.json`: 2 vessels vs 4 high-volume targets, testing solver drop penalties and coastal prioritization.

* **`routing_model.py` & `vessel_routing.py` (Haris)**:
  * Google OR-Tools Vehicle Routing Problem (VRP) solver.
  * Enforces vessel capacity ($m^3$), maximum shift duration (`available_hours`), service/skimming time, and **open routes** (vessels finish at their last assigned target without returning to depot, matching the current problem formulation).

* **`sea_grid.py` & `sea_distance.py`**:
  * A* shortest-path router on a water/land raster grid, guaranteeing vessels navigate around landmasses, islands, and peninsulas.
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

---

## 2. Quickstart & Usage

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
    create_gulf_wide_scenario,        # Regional UAE / Qatar / Saudi scenario
    create_constrained_triage_scenario # Overcapacity triage test
)

vessels, targets = create_rak_standard_scenario()
```

### C. Run the End-to-End Demo CLI

```bash
# Run solver on our RAK standard scenario
python -m optimization.run_demo --scenario optimization/fixtures/gulf_standard.json

# Run sea water check
python -m optimization.sea_check --scenario optimization/fixtures/smoke_test.json
```

### D. Run Unit Tests

```bash
python3 -m unittest tests/test_scenario.py
```
