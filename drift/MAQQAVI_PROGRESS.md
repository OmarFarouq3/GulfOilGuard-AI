# Team B – Maqqavi: progress so far

Last updated: 4 Nov 2026 (final four-site outputs). Day 1 task from Omar: install OpenDrift and run one official example. Day 2 task: the first 24-hour Gulf oil-drift simulation with Joud's data, in the format routing and the dashboard read. Day 3 task: backend integration: drift runs for the four demo locations, connected to Harris's routing and Nihal's validation, in the files Obeid's dashboard reads.

## Status

| Item | Status |
|---|---|
| Install OpenDrift | Done |
| Run one official OpenDrift example | Done |
| Share example results with the team (plots and animation) | Done, in the team SharePoint folder |
| Review Joud's data approach (wind and currents) | Done |
| Check OpenDrift can read Joud's cleaned files, and that they reproduce from the raw ones | Done (Joud confirmed the four files are final) |
| First 24-hour Gulf simulation | Done (see "Day 2" below) |
| `simulate_drift()`, output files for routing and the dashboard, tests, README | Done, merged into `main` (pull request #19, approved by Omar) |
| Output files and a particle-distribution picture shared with the team | Done, in the team SharePoint folder (see "Day 2") |
| Integration checks with Harris, Obeid and Maria's checker | Done (see "Day 2" and "Day 3") |
| Drift, routing and validation for the four demo locations | Done (see "Day 3"); files in the team SharePoint folder |
| Dashboard reads the four locations | Obeid's loaders (his `dashboard` branch, not merged yet) read all four sites with no warnings; his full page test is still to come |

## What was done

**1. OpenDrift installed.** OpenDrift (its main branch, 66 commits after the v1.14.12 release; the package itself reports version 1.14.11, which is what `meta.json` records) is installed in its own conda environment (Python 3.14), created from OpenDrift's own `environment.yml`. The OpenDrift code and the environment are kept outside this repository, so nothing from them is committed here.

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

**Output files** (`drift.geojson` and `meta.json`, not in Git; since day 3 in `outputs/sites/S1/drift/`): one particle feature per hour with stable `particle_ids`, `status` and `oil_volume_m3`, plus an outline polygon per hour for the dashboard, in the formats of `optimization/README.md` section 3.1 and `dashboard/README.md`.

**Shared with the team** (not in Git) in the SharePoint folder `Team B - Drift / Gulf drift 24h - 2026-10-23`: `drift.geojson`, `meta.json` and `drift_snapshots_0_6_12_24h.png`, a picture of the particle positions at 0, 6, 12 and 24 h (one dot per particle, the outline of the oil afloat, and the path of the cloud centre).

**Checks done on my side:**
- 17 tests in `tests/test_drift_simulation.py` pass (oil moves with the current, wave drift is added once, a raw file with `utotal` is refused, output format, shared-contract check).
- Harris's loader (from his branch) reads the files, follows the particles by id and makes 6 patches at his 6 h dispatch (two large: 147 and 44 m³).
- The dashboard's own drift loader reads them with no warnings.
- Maria's `tests/check_outputs.py outputs --gulf` reports the drift files as OK on the merged `main` (1,000 particles at each of the 25 hourly steps, labelled synthetic).

## Day 3: four demo locations, routing and validation

The demo uses four fixed locations (coordinates from Joud, agreed with Omar and the team). Omar approved the same settings as the first run for all four: release 2026-10-23 12:00 UTC, 300 m³ Generic Medium Crude, 1,000 particles, 24 h.

| Site | Location | After 24 h | Oil afloat at 24 h (m³) |
|---|---|---|---:|
| S1 | 25.85°N, 55.65°E, off Ras Al Khaimah (primary; the day 2 run) | about 12 km east, all at sea | 183.6 |
| S2 | 25.70°N, 55.40°E, off Umm Al Quwain | about 10 km east, all at sea | 176.5 |
| S3 | 25.45°N, 55.35°E, off Sharjah / Hamriyah | 444 of 1,000 particles (81.8 m³) stranded on the Ajman–Hamriyah coast: the first at hour 11, most after hour 20 | 101.6 |
| S4 | 25.98°N, 55.85°E, off Ras Al Khaimah near Dhayah | about 15 km north-east, all at sea | 188.8 |

All four points lie inside Joud's data (24.75–27.0°N, 55.0–56.92°E), with current and wave data at every hour, so no new data was needed. The S3 particles are stranded on OpenDrift's coastline, not dropped for missing data.

**Checks on the drift inputs (asked by Joud).** All four runs read `data/processed/wind_clean.nc` and `currents_clean.nc`. Stokes drift is on and comes from `currents_clean.nc`, whose Stokes variables equal the raw `vsdx`/`vsdy` exactly. OpenDrift showed no warnings, and wind, currents and Stokes came from the files for every particle at every step, with no fallback values.

**Limit near the coast.** The current file has gaps next to the coast, and OpenDrift fills them from neighbouring cells without a warning. This barely touches S1, S2 and S4 (0, 0 and 3 of 25,000 samples), but 68 % of S3's samples are next to a gap and 2.3 % are inside one. So S3's stranding time and place rely partly on filled-in currents.

**Cleanup routing and validation.** Harris's `run_drift_plan` (vessels leave 6 h after the release; tank use and cleanup time counted as emulsion) with Nihal's fleet (Port Saqr staging point 25.985°N, 56.035°E; Hamriyah harbour entrance 25.4773°N, 55.4798°E), then Nihal's `validate_sites`:

| Site | Oil afloat when vessels leave (m³) | Vessels used (optimized plan) | Oil cleaned, optimized / baseline (m³) | Last vessel back in port, h after dispatch: optimized / baseline | Distance vs baseline | Validation |
|---|---:|---|---|---|---:|---|
| S1 | 204.0 | SAQR, Hamriyah reserve | 199.2 / 199.6 | 10.50 / 10.59 | −28.0 % | 129 OK, 3 WARN, 0 FAIL |
| S2 | 194.3 | SAQR, Hamriyah reserve | 188.4 / 188.5 | 11.82 / 11.85 | 0.0 % | 115 OK, 3 WARN, 0 FAIL |
| S3 | 200.3 | SAQR, Hamriyah reserve | 196.1 / 195.6 | 11.48 / 11.48 | +3.7 % | 117 OK, 4 WARN, 0 FAIL |
| S4 | 208.6 | SAQR, Hamriyah reserve | 204.3 / 204.5 | 11.40 / 12.56 | +1.9 % | 113 OK, 3 WARN, 0 FAIL |

- The optimized plan cleans about the same oil as the baseline at every site. Its gains are 28 % less distance at S1 and the last vessel back 1.2 h sooner at S4; S2 and S3 are ties on time.
- The warnings are stated limits: a wide patch is cleaned from one point, each site leaves one patch under 0.5 m³ unserved in both plans, and at S3 the oil on the coast is outside the cleanup plan.
- Harris's fix matters at S3. Before it, a patch that outgrew the tank as it took up water was skipped, and the optimized plan cleaned only 129 m³.
- At S3 one patch (T03) is close enough to the coast that its planning point falls in a land cell of the 2.2 km grid and is moved 2.0 km to water, so distances there are approximate.
- Maria's `tests/check_outputs.py` reports that all four sites follow the contract, drift and routing.
- Obeid's loaders read all four sites with no warnings, each forecast at its own marker (0 km moved).

**Files** (not in Git): one folder per location, with the same layout as `outputs/`, shared in the team SharePoint folder (`outputs/` at its top level). Obeid's `dashboard` branch reads this layout: one marker per site folder, showing that site's own files.

```text
outputs/sites/S1 … S4/
  drift/                            drift.geojson, meta.json
  routing/                          routes.geojson, targets.geojson, summary.json, comparison.json, baseline/
  routing.txt                       printout of the routing run
  validation.txt, validation.json   Nihal's validation report
outputs/sites/sites_summary.md, .json   the results table for the demo
outputs/fleet/gulf_standard.json        the fleet the routes were planned with
```

**How these outputs were made** (repository root, OpenDrift environment with OR-Tools, land file in `data/land/`). `validate_sites` covers all four sites at once; the other commands run once per site (S2 shown).

```bash
python -m drift.run_gulf_demo --lat 25.70 --lon 55.40 --out-dir outputs/sites/S2/drift
python -m optimization.run_drift_plan --drift-dir outputs/sites/S2/drift --dashboard-dir outputs/sites/S2/routing --fleet outputs/fleet/gulf_standard.json
python -m optimization.validate_sites --sites-dir outputs/sites --fleet outputs/fleet/gulf_standard.json --write
python tests/check_outputs.py outputs/sites/S2 --gulf
```

Harris's fix and Nihal's newest validator are not in `main` yet, so drift and routing ran on `routing-model` at `1567f55`, and validation and the checker on `feature/final-scenario-validation` at `a237099`. A trial merge of both branches is clean, and the same steps on it give byte-identical outputs (all 51 files).

**Release date.** All runs use 23 Oct 2026 12:00 UTC, as Omar decided. Maria's integration plan (decision D3) now says the same.

## Next steps

1. When Omar merges Harris's and Nihal's branches: pull `main` and compare the merged code with the versions above. Re-run only if the routing or validator code changed.
2. Obeid: merge the `dashboard` branch and test Detect → Predict → Respond for the four locations.

## Open questions

- **Windage:** the usual "3 % of wind speed" rule partly includes wave effects, so check it is not partly counted twice now that wave drift is added separately (OpenDrift's default is kept for now).
- **Random seed label:** `meta.json` and `drift/README.md` record seed 42, but OpenDrift resets the seed to 0 when the model starts, so 42 is not used. The runs are repeatable and the results are unaffected; only the recorded number is wrong.
- **Georeferencing:** drift needs a verified release point and time. Detection output has no coordinates yet, so the release is a synthetic point.
