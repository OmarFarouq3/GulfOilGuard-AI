# Cleanup optimization (members 6-7)

Define vessels, locations, speeds, capacities, availability, response targets and operational constraints. Implement OR-Tools routing and compare with simple baseline methods using identical inputs and constraints.

Consume `Vessel` and `ResponseTarget`; export `OptimizationOutput`.

## Modules & Work Distribution

- **`scenario.py` (Nihal)**:
  - Generates realistic Arabian Gulf spill response scenarios with real port depots (Abu Dhabi, Dubai, Qatar, Jubail, Ras Tanura).
  - Implements Haversine distance (`haversine_distance_km`), speed/travel time calculators (`compute_travel_time_hours`), and distance/time matrix builders (`build_distance_matrix`, `build_time_matrix`) for OR-Tools.
  - Converts OpenDrift trajectories into discrete cleanup targets (`trajectory_to_targets`).
  - Provides JSON serialization and loaders (`export_scenario_to_json`, `load_scenario_from_json`).
  - Pre-generated fixtures available in `optimization/fixtures/`:
    - `smoke_test.json`: 2 vessels, 4 targets (fast debug for routing model).
    - `gulf_standard.json`: 3 vessels, 10 targets (standard Arabian Gulf operational case for dashboard).
    - `constrained_triage.json`: 2 vessels, 4 targets where demand exceeds fleet capacity (tests triage & penalty slack).

- **`vessel_routing.py` (Harris)**:
  - Implements Google OR-Tools routing solver (`optimize_routes`) respecting capacity, speed, availability windows, and depot returns.

- **`evaluate_routes.py`**:
  - Compares OR-Tools solution against greedy/nearest-neighbor baselines under identical constraints.

## Quickstart for Harris & Dashboard

```python
from optimization.scenario import load_scenario_from_json, create_gulf_standard_scenario, build_distance_matrix

# Option 1: Load directly from JSON fixture
vessels, targets = load_scenario_from_json("optimization/fixtures/smoke_test.json")

# Option 2: Generate directly in Python
vessels, targets = create_gulf_standard_scenario()

# Extract coordinates and build distance matrix for OR-Tools
locations = [v.location for v in vessels] + [t.location for t in targets]
dist_matrix_km = build_distance_matrix(locations)
```

