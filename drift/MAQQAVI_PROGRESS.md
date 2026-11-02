# Team B – Maqqavi: progress so far

Last updated: 2 Nov 2026. Task from Omar: install OpenDrift and run one official example simulation.

## Status

| Item | Status |
|---|---|
| Install OpenDrift | Done |
| Run one official OpenDrift example | Done |
| Share example results with the team (plots and animation) | Done, in the team SharePoint folder |
| Review Joud's data approach (wind and currents) | Done |
| Check OpenDrift can read Joud's cleaned files | Waiting for her raw data files |
| First Gulf simulation | Not started |
| `simulate_drift()` and dashboard output files | Not started |

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
- The oil database includes generic oils such as `GENERIC MEDIUM CRUDE`. The oil type for the Gulf demo is still to be agreed.
- The example uses Norwegian data, so nothing in it is a Gulf result.

**4. Joud's data approach reviewed** (`DATA_SOURCES.md` and `environmental_data.py`, merged into `main` in PR #6). Current = `uo + utide`, wave drift from `vsdx`/`vsdy` (OpenDrift's Stokes drift stays on), wind = ERA5 `u10`/`v10`. `utotal`/`vtotal` are not used, to avoid counting tides and wave drift twice. I agree with this approach. One wording point: the last note in `DATA_SOURCES.md` says "don't add wave drift again", but the code keeps wave drift on separately and drops only `utotal`. The code is the intended choice, so the note could be reworded.

## Next steps

1. Get Joud's two raw files (`era5_wind_gulf_2026-10-19_26.nc`, `cmems_currents_gulf_2026-10-19_26.nc`, kept out of Git), run her cleaning script (`python -m drift.environmental_data`), and check that OpenDrift reads the cleaned files. Reply to Joud with the result.
2. First Gulf run from the synthetic test point (25.85°N, 55.65°E, not a detection result) inside 19–26 Oct 2026.
3. Implement `simulate_drift()` and export `DriftOutput` plus the files the dashboard reads (`outputs/drift/drift.geojson` and `meta.json`).

## Open questions

- **Oil type** for the Gulf demo (`GENERIC MEDIUM CRUDE` or another)?
- **Windage:** the usual "3% of wind speed" rule partly includes wave effects, so check it is not partly counted twice now that wave drift is added separately.
- **Hand-off to routing (Nihal):** targets should be separate oil patches at the same forecast hour (for example +12 h), not the slick centre at different times. Agree how particles become targets.
- **Georeferencing:** drift needs a verified release point and time. Detection output has no coordinates yet.
