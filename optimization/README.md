# Cleanup optimization (members 6-7)

Define vessels, locations, speeds, capacities, availability, response targets and operational constraints. Implement OR-Tools routing and compare with simple baseline methods using identical inputs and constraints.

Consume `Vessel` and `ResponseTarget`; export `OptimizationOutput`. `vessel_routing.py` and `evaluate_routes.py` raise `NotImplementedError`. Deriving targets from drift trajectories requires an explicit aggregation and volume-estimation policy: particle positions alone do not specify cleanup demand. Distances must respect navigable water; straight-line routes are not validated operational routes.
