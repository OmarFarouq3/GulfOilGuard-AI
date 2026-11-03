# Cleanup scenario validation: real Gulf drift → routing

Nihal, 3 Nov 2026. A check of Haris's cleanup plan built from Maqqavi's OpenDrift run, and of the fleet it uses. Coordinated with Haris (routing), Maqqavi (drift) and Maria (integration checks).

Everything here is **SYNTHETIC**: the release (300 m³ Generic Medium Crude at 25.85 N, 55.65 E, 2026-10-23 12:00 UTC) is an agreed test input, not a detected spill.

## Inputs checked

| Input | From | Content |
| --- | --- | --- |
| `drift.geojson`, `meta.json` | Maqqavi, `openoil-25.85N-55.65E-20261023T1200Z` | 1,000 particles, hourly 0 to 24 h, OpenDrift 1.14.11 OpenOil |
| `Optimized/` and `Baseline/` (`routes.geojson`, `targets.geojson`, `summary.json`), `comparison.json` | Haris, `run_drift_plan` with sea-grid distances | dispatch 6 h after release, fleet `gulf_standard` |
| `optimization/fixtures/gulf_standard.json` | Nihal | 3 vessels: 2 at Port Saqr, 1 at Hamriyah |
| `optimization/fixtures/gulf_drift_t12.json` | Nihal | the earlier synthetic T+12h fixture, for comparison |

The data files are shared through the team OneDrive (Team C folder) and are not in Git. Haris's run used the fleet with the old depot points (`Team C/Fleet/gulf_standard_old_depots.json` on OneDrive), so pass that fleet to re-run every check:

```bash
python -m optimization.validate_cleanup --drift-dir outputs/maqqavi --routing-dir outputs/haris \
    --fleet gulf_standard_old_depots.json --json validation.json > validation_report.txt
```

`validate_cleanup.py` needs no OR-Tools. It rebuilds the patches from the raw drift file and checks the plan against them. It accepts both the layout `run_drift_plan` writes (plan in the folder, `baseline/` inside it) and the hand-shared one (`Optimized/`, `Baseline/`).

**Latest result, on Haris's emulsion run with the harbour-entrance depots: 85 OK, 5 WARN, 0 FAIL** (section 8). Sections 1 to 7 describe his earlier pure-oil run.

**Result of the earlier run: 52 OK, 7 WARN, 0 FAIL.** No rule is broken. The warnings are assumptions, listed under "Issues" below. Re-run after the depot move (issue 2), the same files give 49 OK, 10 WARN, 0 FAIL. The 3 extra warnings only say that the fleet file Haris used is older than the current `GULF_DEPOTS`.

## 1. Drift input

| Check | Result |
| --- | --- |
| Steps 0, 6, 12, 24 h present | OK: 25 hourly steps, 0 to 24 h |
| Each particle once per step (no oil counted twice) | OK |
| All 1,000 particles accounted for at every step | OK: all active, none stranded (nearest coast about 28 km) |
| Timestamps = start time + hours | OK |
| Oil afloat per step equals `meta.json` `summary_by_hour` | OK |
| Oil afloat only goes down | OK: 300.0 → 204.1 (6 h) → 196.9 (12 h) → 183.6 m³ (24 h) |

## 2. Cleanup targets

At dispatch (6 h, 18:00 UTC) the 204.05 m³ afloat is cut into ~3 km cells. Each cell is followed by its particle ids (`follow = particle_id`, so the targets move).

| Target | Oil at dispatch (m³) | Oil when met (m³) | Particles | Met at (h after release) | Drifted before meeting (km) | 90 % of its oil within (km) | Served by |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| T01 | 147.12 | 145.30 | 721 | 7.39 | 0.60 | 1.45 | RAK-OSRV-SAQR |
| T02 | 44.07 | 43.66 | 216 | 7.01 | 0.52 | 1.37 | RAK-FRV-FALCON |
| T03 | 5.51 | 5.39 | 27 | 8.80 | 0.93 | 1.17 | RAK-FRV-FALCON |
| T04 | 4.29 | 4.20 | 21 | 8.54 | 0.96 | 1.70 | RAK-FRV-FALCON |
| T05 | 2.65 | 2.63 | 13 | 6.87 | 0.42 | 0.65 | RAK-FRV-FALCON |
| T06 | 0.41 | 0.41 | 2 | — | 0 | 0.11 | unserved |

- **Locations and volumes:** every target in `targets.geojson` matches the patch rebuilt from `drift.geojson` (positions within 2 m, volumes within 0.005 m³). The targets are 6 to 10 km east of the release and at most 4.8 km apart.
- **Grouping, no double-counting:** each particle belongs to exactly one patch. Targeted 204.05 + untargeted 0.00 = 204.05 m³ afloat at dispatch. At every meeting hour the targets together hold no more than the oil afloat. Only 6 cells hold oil, fewer than the 15-target limit, so nothing is left out. No patch is larger than the biggest tank (300 m³), so none was split.
- **Weathering is carried through:** each target is valued at its meeting time, about 1 % less than at dispatch.

## 3. Fleet

| Vessel | Base | Speed | Tank | Shift | Straight line to release |
| --- | --- | ---: | ---: | ---: | ---: |
| RAK-FRV-FALCON | Port Saqr (RAK) | 22.0 kn | 60 m³ | 10 h | 42.8 km |
| RAK-OSRV-SAQR | Port Saqr (RAK) | 15.0 kn | 250 m³ | 16 h | 42.8 km |
| HAMRIYAH-OSRV-RESERVE | Hamriyah (Sharjah) | 14.0 kn | 300 m³ | 20 h | 45.9 km |

These are the depot points Haris's run used. They have since moved (issue 2): Port Saqr to a staging point on its harbour approach, now 41.3 km from the release, and Hamriyah to its harbour entrance, 44.8 km.

Each vessel sits on its depot point in `GULF_DEPOTS`, and both Port Saqr and Hamriyah are in the fleet. All three are fixtures (made-up vessels), not real vessel specifications.

## 4. Routes: capacity, hours, cleanup time, return to port

| Plan | Vessel | Stops | Oil (m³) | Tank used | Sailing (h) | Cleanup (h) | Total / shift (h) | Distance (km) |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Optimized | RAK-FRV-FALCON | T05 → T02 → T04 → T03 | 55.9 | 93 % | 2.01 | 1.86 | 3.87 / 10 | 82.0 |
| Optimized | RAK-OSRV-SAQR | T01 | 145.3 | 58 % | 2.70 | 4.84 | 7.54 / 16 | 75.0 |
| Optimized | HAMRIYAH-OSRV-RESERVE | idle | | | | | | |
| Baseline | RAK-FRV-FALCON | T05 → T02 → T03 → T04 | 55.9 | 93 % | 2.11 | 1.86 | 3.97 / 10 | 86.0 |
| Baseline | RAK-OSRV-SAQR | T01 | 145.3 | 58 % | 2.70 | 4.84 | 7.54 / 16 | 75.0 |

- Every route starts and ends at its vessel's port, and the trip back is counted in distance and hours.
- Cleanup time = oil / 30 m³/h on every route.
- No target is served twice, and `served_by` in `targets.geojson` agrees with the routes.
- Every vessel either has a route or is listed as idle.
- `comparison.json` has no rule violations for either plan.
- **Unserved:** T06 (0.41 m³, 0.2 % of the oil). It is under the 0.5 m³ "not worth a trip" threshold. That is correct behaviour, not a missed target.

**Optimized vs baseline on this run:** both recover 201.2 m³ (98.6 % of the oil afloat at dispatch) and both finish in 7.54 h. The only difference is FALCON's last two stops, which saves 4.0 km (2.5 %). One large patch decides the response time, and the other patches are small and close together, so there is little left to optimize. **For the presentation: on the real drift, the optimizer equals the baseline; it does not beat it.** The larger gains seen earlier came from the synthetic stand-in and fixtures.

## 5. Issues and unrealistic assumptions

| # | Issue | Effect on this run | Suggested fix | Owner |
| --- | --- | --- | --- | --- |
| 1 | **Tank capacity is checked against pure oil, but recovered oil is emulsion.** `meta.json` gives about 49 to 52 % water at the meeting times, so recovered volume is about 2× the oil volume. | Emulsion would be about 111 m³ in FALCON's 60 m³ tank (185 %) and about 285 m³ in SAQR's 250 m³ tank (114 %). The plan is not feasible as emulsion. Hamriyah's 300 m³ vessel is idle but would be needed. With emulsion counted, Hamriyah takes T01 (about 285 to 296 m³, depending on when it arrives, so only just fits) and SAQR takes T02 to T05 (about 111 m³). | Count tank use as `oil / (1 - water fraction)` at the meeting hour, or state clearly that capacity is in pure oil. | **Done by Haris** (`e247eed`, on `routing-model`): tanks and cleanup time are now counted as emulsion, see section 8. Haris (routing), Maqqavi (water fraction) |
| 2 | **All three depot points are on land** in the routing land data. Port Saqr is moved 2.6 km and Hamriyah 1.6 km to the nearest water. OpenStreetMap shows why: both points were on roads in the port areas (Saqr Port, and the southern edge of Hamriya Port, Sharjah), not on the water. | About 5 km and about 0.2 h of sailing per Port Saqr round trip are approximate. The dashboard draws the port on land. | **Done on this branch:** `GULF_DEPOTS` now uses the harbour entrances from OpenStreetMap, the gap between the breakwaters: Port Saqr 25.9810 N, 56.0482 E (0.95 km from the old point), Hamriyah 25.4773 N, 55.4798 E (1.46 km). All four fixtures are regenerated. Checked with `optimization.sea_check` on the Natural Earth land file: Hamriyah's entrance is water on the 2.2 km grid, but Port Saqr's entrance falls in a land cell (moved 2.1 km in Haris's run, although Natural Earth puts the real coastline about 0.4 km further east). So Port Saqr is now a staging point 1.4 km out on the approach, **25.9850 N, 56.0350 E**, in open water and inside a water cell. `sea_check` gives no warnings for any of the four fixtures. | Nihal (done), Joud to confirm, Haris to re-run with the new fleet |
| 3 | **The whole operation is at night.** Release 12:00 UTC (16:00 local, UTC+4), dispatch 22:00 local, first patch reached 22:52, last patch cleaned about 04:14, SAQR back in port about 05:32. Sunset in RAK in late October is about 17:50 and sunrise about 06:15 (approximate). | None on the plan's rules. In a real response, skimming in the dark is usually limited. | **Accepted, no change:** this is a demo, and when vessels can work (daylight, crew shifts) is the responsibility of the response and logistics team, not this model (agreed with Maqqavi). Stated as an assumption: vessels can work around the clock at the same cleanup rate. | Accepted (Maqqavi) |
| 4 | **Recovery: 30 m³/h for every vessel, 100 % efficient.** The plan "recovers" 98.6 % of the oil afloat at dispatch (67 % of the 300 m³ released). | At-sea mechanical recovery in practice gets back a much smaller share of a spill, so these numbers are an upper bound, not a forecast. | Present as "oil the fleet can reach and clean", not "oil recovered". Add a per-vessel rate and an efficiency factor when the schema allows. | Haris, Nihal (vessel data) |
| 5 | **Each patch is one point.** T01 (72 % of the oil) is worked from one moving point for 4.8 h, but 90 % of its oil lies within 1.45 km of that point (a slick about 3 km wide). T04's oil lies within 1.7 km. | Sweeping time across the slick is not modelled; FALCON's hops between small patches are fine. | Acceptable for the demo; mention it in the limits. | Haris |
| 6 | **Dispatch at 6 h is an assumption.** | Fixes the patch layout and all times. | Show the `--dispatch-hours 0` and `12` runs as sensitivity cases. | Haris |
| 7 | Minor: `meta.json` says OpenDrift 1.14.11, `drift/MAQQAVI_PROGRESS.md` says 1.14.12. | None. | Align the note. | Maqqavi |

## 6. Synthetic T+12h fixture vs the real OpenDrift-derived targets

`gulf_drift_t12.json` was made on day 2 from Maqqavi's summary table (cloud centre and width at 0, 6, 12, 24 h), before the particle file existed.

| | Synthetic `gulf_drift_t12.json` | Real (from `drift.geojson`) |
| --- | --- | --- |
| Source | 12 points on a ring around the reported cloud centre, built from the table | 1,000 OpenDrift particles, hourly |
| Time | One frozen snapshot at T+12h | Cut at dispatch (6 h), followed as they drift, met 6.9 to 8.8 h |
| Targets | 8 | 6 (5 served) |
| Oil per target | 8 × 24.61 m³, all equal | 145.3, 43.7, 5.4, 4.2, 2.6, 0.4 m³: one patch holds 72 % |
| Total oil in targets | 196.88 m³ (oil afloat at 12 h) | 201.6 m³ when met (204.05 at dispatch) |
| Grouping | Each target is one ring point, at most 1.8 km apart. In effect, one patch cut into eight. | ~3 km cells, each particle in exactly one patch |
| Distance from release | 9.9 to 11.3 km east | 6.3 to 10.2 km east |
| Movement | None (static targets) | 0.4 to 1.0 km drift before the vessel arrives; vessels intercept |
| Weathering | One fixed total at 12 h | Per patch, at each meeting time |
| Routing result | All 3 vessels used (Hamriyah takes 2 targets); optimizer 5.65 h vs baseline 7.41 h response (−24 %). Straight-line distances, `run_demo`. | Hamriyah idle; optimizer = baseline (7.54 h both, 2.5 % less distance). Sea-grid distances, `run_drift_plan`. |

What the difference means:
- **Equal-sized synthetic targets made the optimizer look better than it is.** Eight 24.6 m³ targets let the solver spread the work over three vessels. The real oil is one large patch plus small ones, so one big vessel has to take the large patch and the response time is set by that single job.
- **The synthetic fixture over-split one slick.** Its targets were less than 2 km apart, smaller than one 3 km routing cell, so they would have formed one or two patches under the real grouping.
- **The real targets are earlier and closer** (met 7 to 9 h after release, 6 to 10 km out) than the fixture's T+12h snapshot (10 to 11 km out).
- The fixture stays useful as a quick, OR-Tools-only test case. For the demo and the Respond page, the real plan should be used, labelled synthetic like everything else.

## 7. Status

- Targets, volumes, grouping, fleet, capacity, working hours, cleanup time and return to port are all **verified against the real files**.
- Issue 1 (emulsion vs tank) is fixed in Haris's routing (`e247eed`). The validator now checks the tank and cleanup time on the same basis as the plan (section 8). The numbers in sections 3 and 4 are from his earlier pure-oil run.
- Issue 3 (night operations) is accepted as a stated assumption: a demo, and operating hours are the logistics team's responsibility.
- Issue 2: the depot points are moved to the harbour entrances on this branch. Next, Haris runs `sea_check` on the land file, re-runs `run_drift_plan` with the updated `gulf_standard.json`, and `validate_cleanup.py` is rerun on his new outputs. The numbers in sections 3 and 4 come from the run with the old depot points.
- Shared on OneDrive in `Team C/Validation/`: `validation_report.txt` (the printed report), `validation.json` (every check and number) and this write-up. The fleet files are in `Team C/Fleet/`.

## 8. Re-check after Haris's emulsion update (3 Nov)

Haris's commit `e247eed` counts what a vessel takes on as emulsion, `oil / (1 - water fraction)`, using the hourly water fraction in `meta.json` at the meeting time. Oil recovered is still pure oil. `comparison.json` now says which basis the plan used (`drift.tank_basis`), and `validate_cleanup.py` follows it:

- **`tank_basis: emulsion`:** patches are rebuilt with emulsion counted. Each target's `emulsion_m3`, each vessel's `emulsion_collected_m3`, the tank (FAIL if over) and the cleanup time (emulsion / 30 m³/h) are rechecked.
- **No `tank_basis`** (a plan made before the change, such as the run in sections 3 and 4): checked as pure oil, with the emulsion load as a WARN, as before. That run still gives 0 FAIL.

**Haris's sea-grid run** (3 Nov, new code, harbour-entrance depots, fleet = the current `gulf_standard.json`), shared in `Team C` as `Optimized/`, `Baseline/` and `comparison.json`.

**Validated: 85 OK, 5 WARN, 0 FAIL.** His run used the Port Saqr entrance point, since replaced (below), so rerun with the fleet he used (`Team C/Fleet/gulf_standard_entrance.json` on OneDrive):

```bash
python -m optimization.validate_cleanup --drift-dir outputs/maqqavi --routing-dir outputs/haris \
    --fleet gulf_standard_entrance.json --json validation.json > validation_report.txt
```

Every target's position, oil and emulsion matches the drift. Each vessel's emulsion total, tank, cleanup time (emulsion / 30 m³/h), shift and return to port are rechecked, and no target is served twice. The 5 warnings: the two Port Saqr vessels start from a port the routing grid counts as land (below), one patch wider than 1.5 km (as before), and T06 unserved in both plans (0.4 m³, below the 0.5 m³ threshold). The validator now reads the plan's message and warns when the router had to move a port off land.

| | Optimized | Baseline |
| --- | --- | --- |
| Water fraction | 46 % at dispatch, about 50 to 57 % when met (1 m³ oil ≈ 2 m³ in the tank) | same |
| Targets | 7: T01 (145 m³) is now split into two 72 m³ parts, because as emulsion it would overfill the 300 m³ tank | same |
| FALCON (60 m³) | idle | T05, T03, T04: 24.4 m³ emulsion, 83.2 km |
| SAQR (250 m³) | T01-2, T02: 238.8 m³ emulsion (96 %), 75.2 km | T02, T01-1: 240.1 m³, 76.3 km |
| Hamriyah (300 m³) | T03, T05, T01-1, T04: 176.2 m³ (59 %), 113.5 km | T01-2: 147.6 m³, 105.3 km |
| Unserved | T06 (0.4 m³, below the threshold) | T06 |
| Oil recovered | 199 m³ | 200 m³ |
| Response time (last vessel back in port) | 10.67 h | 10.75 h |
| Distance, all vessels | 188.7 km | 264.8 km |
| Sailing time, all vessels | 7.09 h | 8.85 h |

What changed:
- The emulsion plan is feasible: no tank is over. Hamriyah now does real work. This matches the expectation in issue 1.
- **Optimized vs baseline:** the same oil (199 vs 200 m³) and the same response time (10.67 vs 10.75 h), but **28.7 % less distance and 19.9 % less sailing time**, with FALCON kept in port. The baseline sends all three vessels, including FALCON on an 83 km round trip for about 12 m³ of oil. For the presentation, the gain is efficiency and a vessel kept free, not more oil recovered. This replaces the "optimizer equals baseline" result in section 4.
- My earlier local preview with straight-line distances showed the baseline recovering only 128 m³. That came from the straight-line distances and does not hold on the sea grid.
- Cleanup time is now about twice as long (the skimmer pumps the emulsion), which makes the night-time assumption (issue 3) cover more hours.
- **Port Saqr's harbour entrance (25.981 N, 56.048 E) was land on the 2.2 km routing grid**, so both Port Saqr vessels were moved 2.1 km in this run. Since fixed: Port Saqr is now the approach point 25.9850 N, 56.0350 E (issue 2). My sea-grid re-run with it (same code and drift, local land file): **87 OK, 3 WARN, 0 FAIL**. No port is moved, and the result is the same plan: 199 vs 200 m³, 10.50 vs 10.59 h, **28.0 % less distance** (184.6 vs 256.5 km) and **19.3 % less sailing**. Haris's shared run in this section is still validated with the fleet he used (the entrance point).
