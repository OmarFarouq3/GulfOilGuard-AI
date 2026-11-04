# Cleanup results and limitations, for the demo (Nihal)

4 Nov 2026. These are the final runs of the four demo sites: Maqqavi's drift, Haris's routing with emulsion counted, and the current fleet (`outputs/sites/S1` to `S4`, shared by Maqqavi). Each run is checked with `python -m optimization.validate_sites --write`. The full checks are in each site's `validation.txt`, and the method in `docs/cleanup_scenario_validation.md`.

Everything shown is a **synthetic scenario**: 300 m³ of Generic Medium Crude released at four agreed test points on 23 Oct 2026, 12:00 UTC. It is not a detected spill.

**S3 is not final:** its optimized plan cleans less oil than the baseline (see below). Haris is looking at it. Until it is fixed, show the baseline plan for S3.

## What the cleanup step does

1. **Targets.** When the vessels leave port (6 h after the release), the oil still afloat is grouped into patches of about 3 km. Each patch then moves with its own OpenDrift particles, so a vessel sails to where the patch *will be*, not where it was.
2. **Fleet.** Three made-up demo vessels: FALCON (60 m³, 22 kn) and SAQR (250 m³, 15 kn) at Port Saqr, and a reserve vessel (300 m³, 14 kn) at Hamriyah.
3. **Plan.** OR-Tools assigns patches to vessels to clean the most oil, then to finish soonest. It respects each vessel's tank (counted as the oil-and-water emulsion it really picks up), its working hours, and its return to port.
4. **Baseline.** The comparison is with "each vessel goes to the nearest patch first", under the same rules.

## Results per site

| Site | Oil afloat when vessels leave (m³) | Oil reaching the coast by 24 h (m³) | Vessels used (optimized) | Oil cleaned, optimized / baseline (m³) | Last vessel back in port, optimized / baseline (h after leaving) | Distance, optimized vs baseline |
| --- | ---: | ---: | --- | --- | --- | ---: |
| S1, off Ras Al Khaimah | 204.0 | 0 | SAQR, Hamriyah | 199.2 / 199.6 | 10.50 / 10.59 | **−28.0 %** |
| S2, off Umm Al Quwain | 194.3 | 0 | SAQR, Hamriyah | 188.4 / 188.5 | 11.82 / 11.85 | −0.0 % |
| S3, off Sharjah / Hamriyah | 200.3 | **81.8** | SAQR, Hamriyah | **129.0 / 195.6** | 10.76 / 11.48 | +6.0 % |
| S4, off Ras Al Khaimah near Dhayah | 208.6 | 0 | SAQR, Hamriyah | 204.3 / 204.5 | **11.40 / 12.56** | +1.9 % |

Validation: 0 FAIL at every site (S1 127 OK, 3 WARN; S2 113 OK, 3 WARN; S3 112 OK, 5 WARN; S4 111 OK, 3 WARN). Each site has its own OpenDrift run, not a copy of another site's: the most alike pair (S1 and S3) still ends up 2.1 km apart on average after 24 h.

What each site shows:
- **S1:** the same oil and time as the baseline, with **28 % less sailing distance**, and FALCON stays in port.
- **S2:** the optimized plan and the baseline are practically the same. When the patches line up along one route, nearest-first is already good.
- **S3:** the spill is close to the coast. Oil starts reaching the Ajman–Hamriyah shore 11 h after the release, and 82 m³ (444 of the 1,000 particles) is ashore by 24 h, outside any vessel cleanup. Here **the optimized plan cleans 129 m³ against the baseline's 196 m³**. It leaves half of the largest patch (69 m³) unserved, although both vessels had nearly enough tank room left. This is a known optimizer issue (Haris); show the baseline plan for S3.
- **S4:** about the same oil, and the last vessel is back **1.2 h sooner** than with the baseline.

## Main messages

- **The plan is checked independently.** A separate validator rebuilds every patch from the raw OpenDrift particles and recalculates every volume, tank, time and comparison figure. At all four sites nothing is double-counted, and no vessel goes over its tank, its hours or its meeting order.
- **The optimizer's gain is efficiency, not more oil.** At S1, S2 and S4 both plans reach almost all the oil afloat. The optimized plan sails up to 28 % less (S1) or finishes up to 1.2 h sooner (S4). At S3 it does worse, which the validation caught.
- **Moving targets matter.** Patches drift 1.1 to 1.7 km on average (up to 4.4 km at S4) between dispatch and the vessel's arrival. A plan aimed at where the oil was would miss them.
- **Emulsion matters.** Weathered oil takes up about 50 % water, so 1 m³ of oil fills about 2 m³ of tank. Counting that is why the largest patch is split between two vessels at S1, S2 and S3, and why the Hamriyah reserve is used at every site.
- **Near the coast, time matters most.** At S3, by 24 h, 82 m³ is ashore against 102 m³ still afloat. A vessel cleanup alone does not cover a near-shore spill.

## Limitations to state

| Limitation | What it means |
| --- | --- |
| Cleanup at 30 m³/h, 100 % efficient, for every vessel | The oil cleaned is an upper bound ("oil the fleet can reach and clean"), not a forecast of recovery. Real at-sea recovery gets back much less. |
| Each patch is cleaned from one point | A patch is up to about 2.4 km wide. Sweeping across it is not modelled. |
| Oil keeps weathering while it is cleaned, but the plan counts it as found on arrival | The oil cleaned is slightly overstated. |
| Water content is the slick average per hour | Every patch gets the same water fraction at the same hour. |
| Vessels leave 6 h after the release and can work around the clock | Both are demo assumptions. Operating hours are the response team's decision. |
| Routes use a 2.2 km sea grid | Distances are approximate, not navigation routes. The Port Saqr base is a staging point 1.4 km out on its approach. |
| Oil that reaches the coast is not a cleanup target | At S3, 82 m³ strands on the coast from hour 11. Shoreline cleanup is outside this plan. |
| The optimizer does not always beat nearest-first | At S3 it cleans 34 % less. The validator flags this, and the baseline should be shown there until it is fixed. |
| Vessels and depots are illustrative | Not real vessel specifications. |
