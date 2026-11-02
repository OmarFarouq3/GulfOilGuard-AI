# Drift prediction (Team B: Joud, Maqqavi)

Predicts where released oil goes in the next 24 hours, from ERA5 wind and Copernicus Marine currents, with OpenDrift (OpenOil). Every scenario here is **SYNTHETIC**: the release point and time are agreed test inputs, not a detection and not a measured spill.

## Files

| File | Owner | Purpose |
| --- | --- | --- |
| `environmental_data.py` | Joud | Cleans the raw ERA5 and Copernicus Marine files into OpenDrift-ready `wind_clean.nc` and `currents_clean.nc` |
| `DATA_SOURCES.md` | Joud | Where the data comes from, region, time window |
| `simulate_drift.py` | Maqqavi | `run_oil_drift()` runs the model and returns the particles at every hour; `simulate_drift()` returns the hourly centre of the oil as the shared `DriftOutput` |
| `export_outputs.py` | Maqqavi | Writes `outputs/drift/drift.geojson` and `meta.json` for routing and the dashboard |
| `run_gulf_demo.py` | Maqqavi | One command for the agreed Gulf scenario |
| `MAQQAVI_PROGRESS.md` | Maqqavi | Progress note |

## Run it

From the repository root, with OpenDrift installed (conda environment) and the data files in place:

```bash
python -m drift.run_gulf_demo                    # writes outputs/drift/drift.geojson and meta.json
python -m optimization.run_drift_plan            # routing reads those files (Team C)
python -m unittest discover -s tests -p "test_drift_simulation.py"
```

Options: `--start 2026-10-23T12:00:00Z` (UTC, must include the Z), `--hours 24`, `--lat`, `--lon`, `--particles`, `--volume`, `--diffusivity`, `--data-dir`, `--out-dir`. A run outside the data window, or with a current file that is not the cleaned one, is refused.

## Data (not in Git)

Data files never go to Git (`data/` and `outputs/` are ignored); the team shares them through the team SharePoint folder (link in the group chat).

```text
data/raw/        era5_wind_gulf_2026-10-19_26.nc, cmems_currents_gulf_2026-10-19_26.nc   (as downloaded)
data/processed/  wind_clean.nc, currents_clean.nc                                         (made by environmental_data.py)
```

SHA-256, to check that everyone has the same files:

```text
a0591025c1d52101008df4b6bcca0ff0f7b8bc6a51c361b75d7f8338d54629a5  era5_wind_gulf_2026-10-19_26.nc
751c8a481169de871f806ee12bd6ad30709074931484b81fd25e1e5ce20aadf9  cmems_currents_gulf_2026-10-19_26.nc
46806a04b2a353c4a0fa55d97399560338c855e01a95faa2a6c35462957a5940  wind_clean.nc
1b3155b00325b1d82dd1708286f686b53d876dfb9ce5b234f5bbd470927b4a38  currents_clean.nc
```

The cleaned files were reproduced from the raw ones with `environmental_data.py` and are identical in content and attributes.

**Wave drift is counted once.** The current is `uo + utide`; wave (Stokes) drift is a separate variable and OpenDrift's Stokes drift is on. `utotal`/`vtotal` already contain the wave drift and are never used. `run_oil_drift` refuses a current file that still has them (or has no wave-drift variables).

## The agreed scenario

| Input | Value | Where it comes from |
| --- | --- | --- |
| Release point | 25.85 N, 55.65 E | Joud (`DATA_SOURCES.md`), agreed with Omar |
| Duration, outputs | 24 h, one output per hour (0 to 24 h) | Omar; routing needs hourly steps |
| Oil | Generic Medium Crude | Omar, routing README |
| Release | instantaneous, 300 m3, 1000 particles in a circle of radius 500 m | 300 m3 is routing's placeholder (`DriftTargetConfig`); the rest is our choice |
| Release time | 2026-10-23 12:00 UTC | our choice, inside the data window (19 Oct 00:00 to 26 Oct 23:00 UTC); nobody specified one |

**Assumptions, not data** (also written into `meta.json`): water temperature 28 C and salinity 40 (the data files have neither; OpenDrift's own fallbacks, 10 C and 34, are wrong for the Gulf), horizontal diffusivity 10 m2/s (gives the cloud a realistic width; with 0 the cloud stays under 1 km wide), vertical mixing off (surface oil only), fixed random seed 42, wind drift factor 3 % (OpenDrift default for oil), time step 15 min.

## Result of the agreed run

| Hour | Oil afloat (m3) | Centre east / north of release (km) | Cloud width, 1 sd (km) | Water in the oil |
| ---: | ---: | --- | --- | ---: |
| 0 | 300.0 | 0.0 / 0.0 | 0.5 | 0 % |
| 6 | 204.1 | 7.7 / 0.5 | 0.8 | 47 % |
| 12 | 196.9 | 10.3 / 0.9 | 1.1 | 54 % |
| 18 | 190.1 | 9.0 / 0.4 | 1.3 | 62 % |
| 24 | 183.6 | 12.0 / 0.6 | 1.7 | 70 % |

All 1000 particles stay afloat: the nearest coast is about 28 km away, so nothing strands in 24 hours. The oil mass adds up (afloat + evaporated + dispersed = released). The centre moves out and back because tidal currents dominate. At the dispatch hour (6 h) routing's 3 km cells cut the oil into 2 large patches (72 % and 22 %) and a few small ones.

## Output format

`outputs/drift/drift.geojson` and `meta.json` follow `optimization/README.md` section 3.1 (what routing needs) and `dashboard/README.md`, "Drift module" (what the dashboard draws):

- one `MultiPoint` feature of particles per hour, with `hours`, `timestamp` (UTC), `status`, `particle_ids` (the same particle keeps its id at every hour), `oil_volume_m3`, `kind: "particles"` and `synthetic: true`;
- one `Polygon` outline (convex hull of the oil afloat) per hour, `kind: "envelope"`, for the dashboard;
- `meta.json`: the hourly centre path (the shared `DriftOutput`), release time, particle count, `release_volume_m3`, wind and current summary, and the assumptions above.

`oil_volume_m3` is pure oil (mass / density). Oil that has taken up water (emulsion) takes more room, by 1 / (1 - water fraction), so recovered volume would be larger than the oil volume.

Checked with: the shared contract test (`tests/contract_checks.py`), the dashboard's own loader (no warnings), routing's loader (particles followed by id, 6 patches at 6 h) and `tests/check_outputs.py --gulf`.

## Limits

- Synthetic release, no detection or georeferencing behind it.
- Surface oil only; no stranding or shoreline processes were exercised in 24 hours.
- The weathering (evaporation, water uptake) depends on the assumed temperature and salinity; the cloud width depends on the assumed diffusivity. Neither is calibrated against observations.
- The currents file ends at 56.917 E (the wind goes to 57.0 E); particles leaving the data area are removed by OpenDrift as "missing data". This did not happen in the agreed run.
- Output step is 1 h, so anything faster (tidal turning within an hour) is not resolved.
