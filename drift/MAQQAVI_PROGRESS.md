# Team B – Maqqavi: progress so far

Last updated: 2 Nov 2026 (day 2). Day 1 task from Omar: install OpenDrift and run one official example. Day 2 task: the first 24-hour Gulf oil-drift simulation with Joud's data, in the format routing and the dashboard read.

## Status

| Item | Status |
|---|---|
| Install OpenDrift | Done |
| Run one official OpenDrift example | Done |
| Share example results with the team (plots and animation) | Done, in the team SharePoint folder |
| Review Joud's data approach (wind and currents) | Done |
| Check OpenDrift can read Joud's cleaned files, and that they reproduce from the raw ones | Done (Joud confirmed the four files are final) |
| First 24-hour Gulf simulation | Done (see "Day 2" below) |
| `simulate_drift()`, output files for routing and the dashboard, tests, README | Done, on branch `feature/drift-simulation` (pull request to follow) |
| Integration checks with Harris, Obeid and Maria's checker | Done on my side (see "Day 2"); waiting for their confirmation |

## What was done

**1. OpenDrift installed.** OpenDrift (current master, v1.14.12) is installed in its own conda environment (Python 3.14), created from OpenDrift's own `environment.yml`. The OpenDrift code and the environment are kept outside this repository, so nothing from them is committed here.

**2. Official example run.** I ran `examples/example_openoil.py` (the OpenOil model) on OpenDrift's bundled Norway test data. It needs no downloads.

| Setting | Value |
|---|---|
| Release | 2,000 particles within 3 km of 60.1°N, 4.9°E |
| Oil type | HEIDRUN AARE 2023 |
| Duration | 40 hours, 15-minute steps, hourly output |
| Result | 136 particles still at sea, 1,864 stranded on the coast |
| Run time | about 34 seconds (the animation takes about 3 more minutes to render) |

The drift map, oil budget, vertical mixing plots and an animation were produced and sent to Omar, with a screen recording.

**Result files (kept out of Git).** They are in the team SharePoint folder (the link is in the group chat), in the subfolder `Team B - Drift / OpenDrift official example`:

| File | What it shows |
|---|---|
| `drift_openoil_example_01_drift_map.jpg` | Particle drift over 40 h: 2,000 released, 136 active, 1,864 stranded |
| `drift_openoil_example_02_oil_budget.jpg` | Oil mass split over time (dispersed, submerged, surface, stranded, evaporated), with emulsion viscosity, water content, wind and current speed |
| `drift_openoil_example_03_vertical_distribution.jpg` | Number of particles by depth at hour 40 |
| `drift_openoil_example_04_water_fraction.jpg` | Water fraction of the oil over time (levels off at about 0.7) |
| `drift_openoil_example_05_particle_depth_over_time.jpg` | Depth of every particle over time (mixing down to about 50 m) |
| `drift_openoil_example_06_animation.mp4` | 14-second animation of the drift (screen recording) |

These are results from OpenDrift's bundled Norway test data, not Gulf results.

**3. What this showed that matters for our Gulf work.**
- OpenDrift has a built-in coastline (GSHHG). It stops particles on land and counts them as "stranded", so we can report which stretch of coast would be oiled.
- When a forcing variable has no data, OpenDrift uses a fallback value. In this example it set wave (Stokes) drift to 0, among others. Joud's current file contains wave drift, so this will matter for our runs.
- The oil database includes generic oils such as `GENERIC MEDIUM CRUDE`, the oil type agreed for the Gulf demo.
- The example uses Norwegian data, so nothing in it is a Gulf result.

**4. Joud's data approach reviewed** (`DATA_SOURCES.md` and `environmental_data.py`, merged into `main` in PR #6). Current = `uo + utide`, wave drift from `vsdx`/`vsdy` (OpenDrift's Stokes drift stays on), wind = ERA5 `u10`/`v10`. `utotal`/`vtotal` are not used, to avoid counting tides and wave drift twice. I agree with this approach. One wording point: the last note in `DATA_SOURCES.md` says "don't add wave drift again", but the code keeps wave drift on separately and drops only `utotal`. The code is the intended choice, so the note could be reworded.

## Day 2: first Gulf simulation (synthetic scenario)

Run with `python -m drift.run_gulf_demo` (details, assumptions and limits in `drift/README.md`).

| Setting | Value |
|---|---|
| Release | 25.85°N, 55.65°E (Joud's agreed test point), 300 m³ Generic Medium Crude, 1,000 particles, instantaneous |
| Time | 24 h from 2026-10-23 12:00 UTC (our choice inside Joud's data window; nobody specified a release time), output every hour |
| Forcing | Joud's cleaned ERA5 wind and Copernicus Marine currents (current = `uo + utide`, wave drift separate, OpenDrift's Stokes drift on, `utotal` not used) |

| Hour | Oil afloat (m³) | Centre east / north of release (km) | Cloud width, 1 sd (km) |
|---:|---:|---|---|
| 0 | 300.0 | 0.0 / 0.0 | 0.5 |
| 6 | 204.1 | 7.7 / 0.5 | 0.8 |
| 12 | 196.9 | 10.3 / 0.9 | 1.1 |
| 24 | 183.6 | 12.0 / 0.6 | 1.7 |

All 1,000 particles stay afloat (the nearest coast is about 28 km away); the oil budget adds up to 100 %. The centre moves out and back because tidal currents dominate.

**Assumptions I had to make** (no data for them, all written into `meta.json`): water temperature 28 °C and salinity 40 (OpenDrift's defaults of 10 °C and 34 are wrong for the Gulf), horizontal diffusivity 10 m²/s (with 0 the cloud stays under 1 km wide), vertical mixing off, fixed random seed. 300 m³ is routing's placeholder volume and 1,000 particles is our own choice.

**Output files** (`outputs/drift/drift.geojson`, `meta.json`; not in Git): one particle feature per hour with stable `particle_ids`, `status` and `oil_volume_m3`, plus an outline polygon per hour for the dashboard, in the formats of `optimization/README.md` section 3.1 and `dashboard/README.md`.

**Checks done on my side:**
- 17 tests in `tests/test_drift_simulation.py` pass (oil moves with the current, wave drift is added once, a raw file with `utotal` is refused, output format, shared-contract check).
- Harris's loader (from his branch) reads the files, follows the particles by id and makes 6 patches at his 6 h dispatch (two large: 147 and 44 m³).
- The dashboard's own drift loader reads them with no warnings.
- Maria's `tests/check_outputs.py --gulf` reports the drift files as OK.

## Next steps

1. Pull request for `feature/drift-simulation` (merge `main` into the branch first).
2. Share `outputs/drift/` through the team SharePoint folder, and tell Harris, Obeid and Nihal that the real files exist, so routing and the dashboard can switch from the stand-in to them.
3. Plots of the particle distribution at 0, 6, 12 and 24 h for the results.

## Open questions

- **Windage:** the usual "3 % of wind speed" rule partly includes wave effects, so check it is not partly counted twice now that wave drift is added separately (OpenDrift's default is kept for now).
- **Oil volume for vessel capacity:** the files give pure oil volume; recovered emulsion is larger by 1 / (1 - water fraction), about 3 times at 24 h. Routing may want to account for this.
- **Georeferencing:** drift needs a verified release point and time. Detection output has no coordinates yet, so the release is a synthetic point.
