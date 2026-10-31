# Drift prediction (members 4-5)

Collect ERA5 winds and Copernicus Marine currents, align variables/units/time/coverage, and implement OpenDrift oil simulations for 6, 12, and 24 hours. Export `DriftOutput` with timestamped WGS84 positions.

`environmental_data.py` and `simulate_drift.py` raise `NotImplementedError`. Provider credentials remain local. Agree on oil properties, release time, seeding and uncertainty before physical simulation. Start independently with explicitly synthetic geographic inputs; these are test fixtures, never detection or simulation results.
