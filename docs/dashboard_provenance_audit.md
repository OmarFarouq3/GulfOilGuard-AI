# Dashboard provenance audit: what are sites S1–S4?

Question (team captain): *Is the dashboard displaying four real, precomputed simulations, or illustrative/repositioned scenarios?*

Answered from the files and the repo, not from the dashboard's labels. Read-only audit of branch `fix/e2e-report-issues` (commit d32ac8e), 4 Nov 2026. Every number below comes from `outputs/sites/<id>/` and `outputs/fleet/` alone (see the last section).

## For the captain

All four sites (S1–S4) are separate, real OpenDrift runs. They were precomputed, each from its own hypothetical release point, and none is a copy of S1 moved to another place. They share the same settings: release on 23 Oct 2026 at 12:00 UTC, 300 m³ of Generic Medium Crude, 1,000 particles, 24 hours, random seed 42. Those settings, and the release points, are assumptions; no real spill or detection is behind them. The wind and currents are recorded as ERA5 and Copernicus Marine data for that week, which the drift files report differently at each site. S2–S4's particles move differently from S1's, by 0.15 to 5.6 km on average depending on site and hour. At S3, 444 of 1,000 particles strand on the Ajman–Hamriyah coast, as a real run that close to shore would. Each site's cleanup plan is its own optimisation, built from that site's oil, but all four use the same assumed fleet and home ports. The radar image on Detect is an unrelated dataset sample with no location. Only the demo mode (off by default) shows an illustrative scenario that is moved onto a spill.

## Provenance table

| Site | Drift origin | Routing origin | Forcing | Evidence | Classification |
|---|---|---|---|---|---|
| S1 (25.85° N, 55.65° E) | Own OpenDrift 1.14.11 OpenOil run, `openoil-25.85N-55.65E-20261023T1200Z`, the "day 2" run. `outputs/drift/` is a byte-identical copy (same MD5). | Own plan, `…@dispatch6h`. 6 targets: all within 0.13 km of S1's own particles at their meeting hour, and at least 19.6 km from any other site's. FALCON and SAQR from the Port Saqr staging point. | ERA5 10 m wind + Copernicus Marine currents, tide and Stokes drift, as recorded in `meta.json`. Mean along the particles: wind 3.59 m/s from 242°, current 0.21 m/s to 127°. | `meta.json` fields; particle files (table below); `drift/MAQQAVI_PROGRESS.md` day 2; `routing.txt` | **Real precomputed run at a hypothetical release point** |
| S2 (25.70° N, 55.40° E) | Own run, `openoil-25.70N-55.40E-…`. Its particle paths differ from S1's by 0.15 km on average at 1 h and 2.27 km at 24 h. It ends 10.0 km out, heading 82°. | Own plan. 5 targets within 0.30 km of S2's particles, at least 24.2 km from the others'. Uses the SAQR and Hamriyah reserve vessels. | Same sources. Wind 3.73 m/s from 250°, current 0.21 m/s to 99°. | as above; day 3 table in the progress note | **Real precomputed run at a hypothetical release point** |
| S3 (25.45° N, 55.35° E) | Own run, `openoil-25.45N-55.35E-…`. The first particle strands at 11 h, 4 by 18 h, and 444 by 24 h, centred on 25.436° N, 55.461° E, which is the Ajman–Hamriyah shoreline about 11 km east of the release. 101.6 m³ is still afloat at 24 h, against 177–189 m³ at the other sites. | Own plan. 6 targets within 0.09 km of S3's particles, at least 24.7 km from the others'. Uses only the Hamriyah reserve vessel, 31 km in total. | Same sources. Wind 3.39 m/s from 264°, current 0.16 m/s to 87°. | as above; OpenDrift's status `stranded` in `drift.geojson` | **Real precomputed run at a hypothetical release point** |
| S4 (25.98° N, 55.85° E) | Own run, `openoil-25.98N-55.85E-…`. It differs most from S1: 5.59 km on average at 24 h, ending 15.1 km out, heading 67° (north-east). | Own plan. 6 targets within 0.29 km of S4's particles, at least 20.8 km from the others'. FALCON and SAQR, 60 km in total. | Same sources. Wind 3.04 m/s from 240°, current 0.21 m/s to 67°. | as above | **Real precomputed run at a hypothetical release point** |
| Demo mode (toggle, off by default) | `services/mock_data.py`: an illustrative scenario that the dashboard translates rigidly onto the chosen demo spill (`scenario.anchor_drift`). | The demo plan, moved by the same offset (`scenario.anchor_routing`). | None | `dashboard/services/scenario.py` | **Illustrative/mock** (already labelled "Simulated scenario") |

### Drift outputs compared numerically

Computed from `drift.geojson` only (active particles; km east/north of each site's own release point):

| Hour | S1 centre, distance, spread (sd) | S2 | S3 | S4 |
|---:|---|---|---|---|
| 1 | 1.79 E / 0.54 N, 1.87 km, 0.55 / 0.58 | 1.71 / 0.67, 1.84 | 1.48 / 0.31, 1.51 | 1.80 / 0.86, 1.99 |
| 6 | 7.69 / 0.48, 7.70, 0.80 / 0.86 | 7.98 / 0.89, 8.03 | 6.59 / −0.16, 6.60 | 6.90 / 2.04, 7.20 |
| 12 | 10.25 / 0.88, 10.29, 1.06 / 1.07 | 10.44 / 0.66, 10.47 | 8.71 / −0.01, 8.71 (999 afloat) | 10.28 / 4.04, 11.05 |
| 24 | 11.95 / 0.62, 11.96, 1.67 / 1.59 | 9.88 / 1.32, 9.96, 1.37 / 1.37 | 11.46 / 0.73, 11.48 (556 afloat) | 13.95 / 5.83, 15.12, 1.63 / 1.79 |

**A translated copy would give zero difference here.** For the same particle id, the movement since hour 0 differs from S1's by these amounts (mean km):

| Site vs S1 | 1 h | 6 h | 12 h | 24 h |
|---|---:|---:|---:|---:|
| S2 | 0.15 | 0.52 | 0.41 | 2.27 |
| S3 | 0.38 | 1.27 | 1.84 | 1.82 |
| S4 | 0.32 | 1.75 | 3.16 | 5.59 |

- **The one thing that is identical** is the starting pattern: each particle's position at hour 0, relative to its site's release point, matches S1's to within 1.6 m. That is expected, because all runs use random seed 42 for the 500 m release circle.
- **Why the four runs look alike:** they all move roughly east (67–87°). They share the same week of mostly south-westerly wind and the same tidal regime, and they are only 25–60 km apart. The differences in direction, distance and spread, and S3's stranding, are what separate runs from a copy.
- **S3's stranding is consistent with a real run.** Its release point is about 11 km from the coast, the cloud moves about 9–11 km east in 12–24 h, and OpenDrift's built-in coastline stops particles on land. The progress note says the S3 particles strand "from hour 20". The file shows the first one at 11 h (1 particle) and 4 by 18 h, so the note is approximate.

## What is real data and what is assumed

| Part | Status | Source |
|---|---|---|
| Drift model | Real: OpenDrift 1.14.11 OpenOil, run outside this repo, in the drift owner's conda environment | `meta.json` `model`; progress note |
| Wind | Real gridded data, as recorded: ERA5 hourly 10 m wind, 0.25°, 19–26 Oct 2026, area 24.75–27.0° N, 55.0–57.0° E, from `era5_wind_gulf_2026-10-19_26.nc`. The most recent days are preliminary (ERA5T). | `meta.json` `wind_source`; `drift/DATA_SOURCES.md` |
| Currents | Real gridded data, as recorded: Copernicus Marine GLOBAL_ANALYSISFORECAST_PHY_001_024 (`uo`+`utide`, plus Stokes drift), 1/12°, same period and area, from `cmems_currents_gulf_2026-10-19_26.nc` | `meta.json` `current_source`; `drift/DATA_SOURCES.md` |
| Forcing covers the runs | All four release points lie inside 24.75–27.0° N, 55.0–57.0° E, and 23 Oct 12:00 – 24 Oct 12:00 UTC lies inside 19–26 Oct. Different wind and current values per site are consistent with gridded data, not a constant field. | `DATA_SOURCES.md`; `meta.json` |
| Release points | Assumed: four agreed demo locations ("coordinates from Joud, agreed with Omar"), not detections. All files carry `"synthetic": true`. | `meta.json` `note`; progress note day 3 |
| Release time, 23 Oct 2026 12:00 UTC | Assumed: chosen inside the data window ("nobody specified a release time"; D3 in `docs/integration_plan.md`). It is a real date with real forcing data, but no spill happened then at these points. | progress note; `integration_plan.md` D3 |
| Oil and amount | Assumed: Generic Medium Crude (agreed), 300 m³ (routing's placeholder), 1,000 particles, instantaneous surface release in a 500 m circle | `meta.json` |
| Other physics | Assumed: water 28 °C, salinity 40, diffusivity 10 m²/s, no vertical mixing, seed 42, 15-min step | `meta.json` `assumptions` |
| Routing | Real optimisation (OR-Tools) on each site's own drift. Assumed: fleet and home ports (`outputs/fleet/gulf_standard.json`, with 2 RAK vessels at one staging point and a Hamriyah reserve), dispatch 6 h after release, cleanup rate 30 m³/h, one trip each. Sea paths run on a 2.2 km grid around land, "approximate, not validated operational routes"; the Port Saqr point is moved 2.1 km off land. | `summary.json` `message`; `routing.txt` |
| Detection (radar image) | Real U-Net output on a real archive SAR image, but not linked to any site. There is no `outputs/detection/spill.geojson` and no `outputs/spills.geojson`. The image for a site is a random draw from the local dataset (`services/image_picker.py`) and has no geolocation (model card: `oil_coordinates` is `None`). | files; code |

## What could not be determined from the repo

1. **The forcing files themselves.** `data/raw` and `data/processed` are not on this machine or in Git, so I could not open the files, check their time and area coverage, or hash them. The coverage above comes from `DATA_SOURCES.md` and `meta.json`.
   - Ask **Joud** (data): *"Can you share the SHA-256 and `ncdump -h` time/lat/lon ranges of `era5_wind_gulf_2026-10-19_26.nc` and `cmems_currents_gulf_2026-10-19_26.nc` as used for the S1–S4 runs?"*
2. **That each site was a separate execution.** The numbers are only consistent with separate runs (see above); there is no run log in the repo.
   - Ask **Maqqavi** (drift): *"Were S2, S3 and S4 each produced by a separate `python -m drift.run_gulf_demo --lat … --lon …` run on the same forcing files as S1, with no post-processing of the outputs? Do you have the console logs or file hashes? Also, S3's note says stranding from hour 20, but `drift.geojson` has the first stranded particle at hour 11. Which is right?"*
3. **The background claim in `DATA_SOURCES.md`** ("the real oil slick from the Strait of Hormuz reached this coast in late October 2026"). Nothing in the repo supports it, and the dashboard does not repeat it.
   - Ask **Joud**: *"What is the source for that sentence?"*
4. **The fleet and home ports are an assumption**, but their origin isn't documented beyond "Nihal's fleet".
   - Ask **Nihal**: *"Are the vessel positions, speeds and capacities in `gulf_standard.json` real vessel data or placeholders?"*

## What the dashboard tells viewers (before Part 3), and whether it is accurate

| Where | Text | Verdict |
|---|---|---|
| Predict/Respond/Overview chip | "Real forecast, simulated release". Tooltip: "Real OpenDrift forecast on real wind and current data; the release point is simulated" | Accurate in substance. "Forecast" here means a model prediction for a past week, not a forecast of the future. It doesn't say the oil type and volume are assumed. |
| Predict note | "Real OpenDrift forecast for site S1, made for its release point. The release point and time are test inputs, not a detection." | Accurate. Doesn't mention the oil and volume assumption or the forcing sources. |
| Predict precomputed note | "Precomputed result from the saved drift run (run openoil-…, released 2026-10-23 12:00 UTC). Nothing is re-simulated here." | Accurate. |
| Predict subtitle | "Winds and ocean currents drive a drift simulation of oil released at the spill site over the next 24 hours." | Misleading: "next 24 hours" sounds like the future; the run covers 24 h from 23 Oct 2026 12:00 UTC. |
| Predict "What drives the forecast" | "Weather and ocean conditions used by the simulation." | Accurate (means along the particles, from `meta.json`). |
| Respond note | "Response plan for site S1: the optimiser's plan for this site's drift forecast, not moved. It starts from a test release point, not a detection." Simulated list: release point and time; fleet, cleanup rate and other assumptions | Accurate. |
| Respond precomputed note | "Precomputed result from the saved routing plan (scenario …, release …). Nothing is re-optimised here." | Accurate. |
| Overview map legend | "Forecast site (simulated release point)" | Accurate. |
| Overview tiles | "Release footprint, simulated … a test release, not a detected slick"; "These numbers come from a simulated scenario, not from observations." | Accurate. |
| Overview "Choose an incident" | "…start from a synthetic release point there; the radar image assigned to it is a sample from the dataset, not taken at that point." | Accurate. |
| Overview "Response flow" | "Not one incident yet: the radar scene on Detect has no location…" | Accurate. |
| Overview Detect card and Detect page, no site selected | Chip "Live data" | **Misleading.** These are saved model outputs on archive dataset images, not live data. |
| Overview Predict card | "…a drift simulation that forecasts where oil released at a synthetic point goes over 24 hours." | Accurate. |
| Detect | "Real detection, simulated location"; "Simulated outline at the selected spill…" | Accurate. |
| Demo mode | "Simulated scenario", "Precomputed demo scenario (simulated)…" | Accurate (illustrative and moved). |
| Overview "How far can you trust this?" | "Routes to predicted patches are approximate, not checked navigation" | Accurate. |

## How the numbers were produced

Two standalone scripts that read only `outputs/sites/<id>/` and `outputs/fleet/` with plain JSON and NumPy (no dashboard code): one for the drift comparison, one for the routing check. They were kept outside the repo; ask for them if needed.
