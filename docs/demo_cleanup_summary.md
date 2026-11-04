# Cleanup results and limitations, for the demo (Nihal)

DRAFT, 4 Nov 2026. The per-site numbers are filled in from Haris's final runs once he shares them (`python -m optimization.validate_sites --write` makes the table). The full checks are in `docs/cleanup_scenario_validation.md`.

Everything shown is a **synthetic scenario**: 300 m³ of Generic Medium Crude released at four agreed test points on 23 Oct 2026, 12:00 UTC. It is not a detected spill.

## What the cleanup step does

1. **Targets.** When the vessels leave port (6 h after the release), the oil still afloat is grouped into patches of about 3 km. Each patch then moves with its own OpenDrift particles, so a vessel sails to where the patch *will be*, not where it was.
2. **Fleet.** Three made-up demo vessels: FALCON (60 m³, 22 kn) and SAQR (250 m³, 15 kn) at Port Saqr, and a reserve vessel (300 m³, 14 kn) at Hamriyah.
3. **Plan.** OR-Tools assigns patches to vessels to clean the most oil, then to finish soonest. It respects each vessel's tank (counted as the oil-and-water emulsion it really picks up), its working hours, and its return to port.
4. **Baseline.** The comparison is with "each vessel goes to the nearest patch first", under the same rules.

## Results per site

| Site | Afloat at dispatch (m³) | Stranded by 24 h (m³) | Vessels used | Oil cleaned, optimized / baseline (m³) | Back in port, optimized / baseline (h) | Distance change |
| --- | ---: | ---: | --- | --- | --- | ---: |
| S1, off Ras Al Khaimah | | | | | | |
| S2, off Umm Al Quwain | | | | | | |
| S3, off Sharjah / Hamriyah | | | | | | |
| S4, off Ras Al Khaimah near Dhayah | | | | | | |

For reference, S1 with the current fleet (my local re-run, to be replaced by Haris's final run): 204 m³ afloat at dispatch, cleaned by SAQR and the Hamriyah reserve. 199 m³ cleaned by both plans; the last vessel is back 10.5 h after dispatch in both. The optimized plan sails **28 % less** distance and keeps FALCON in port.

## Main messages

- **The plan is checked independently.** A separate validator rebuilds every patch from the raw OpenDrift particles. It recalculates every volume, tank, time and comparison figure. Nothing is double-counted, and no vessel goes over its tank or its hours.
- **On the real drift, the optimizer's gain is efficiency, not more oil.** Both plans reach almost all the oil. The optimized plan sails less and keeps a vessel free. One large patch decides the response time.
- **Moving targets matter.** Patches drift about 1.5 km (up to 3 km) between dispatch and the vessel's arrival. A plan aimed at where the oil was would miss them.
- **Emulsion matters.** Weathered oil takes up about 50 % water, so 1 m³ of oil fills about 2 m³ of tank. Counting that changes which vessels are needed.

## Limitations to state

| Limitation | What it means |
| --- | --- |
| Cleanup at 30 m³/h, 100 % efficient, for every vessel | The oil cleaned is an upper bound ("oil the fleet can reach and clean"), not a forecast of recovery. Real at-sea recovery gets back much less. |
| Each patch is cleaned from one point | A patch is up to about 2.4 km wide. Sweeping across it is not modelled. |
| Oil keeps weathering while it is cleaned, but the plan counts it as found on arrival | The oil cleaned is slightly overstated. |
| Water content is the slick average per hour | Every patch gets the same water fraction at the same hour. |
| Vessels leave 6 h after the release and can work around the clock | Both are demo assumptions. Operating hours are the response team's decision. |
| Routes use a 2.2 km sea grid | Distances are approximate, not navigation routes. The Port Saqr base is a staging point 1.4 km out on its approach. |
| Oil that reaches the coast is not a cleanup target | At S3, part of the oil strands on the Ajman–Hamriyah coast from hour 20. Shoreline cleanup is outside this plan. |
| Vessels and depots are illustrative | Not real vessel specifications. |
