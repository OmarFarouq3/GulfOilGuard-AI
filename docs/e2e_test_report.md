# End-to-end integration test report

Tested by Maria on 3 Nov 2026 on a Windows laptop (Python 3.14, with internet), on `main` as of 3 Nov 2026, set up from `requirements.txt` and `dashboard/requirements.txt`. Every result below comes from a command run or a file opened on that laptop; the commands are in section 10.

**Inputs.** The team outputs shared on SharePoint on 3 Nov, copied into `outputs/`: `detection/metrics.json` (Team A); `drift/drift.geojson` and `meta.json` from `Gulf drift 24h - 2026-10-23` (Team B), the run for demo site S1 at 25.85°N, 55.65°E; `routing/` with the optimized `routes.geojson`, `summary.json`, `targets.geojson` and `comparison.json`, and `routing/baseline/` with the baseline plan (Team C).

**Priority scale.** **P1** blocks the Detect → Predict → Respond demo. **P2** shows a wrong number or a misleading claim on stage. **P3** is cleanup that does not change what the audience sees.

## Omar's checklist

| Task | Where |
| --- | --- |
| Run the existing contract and integration tests against the updated project | Section 2 (unit and contract tests), section 3 (output checker) |
| Validate detection outputs, drift predictions and routing exports | Section 3 |
| Check that file paths, schemas, timestamps and coordinates are consistent | Sections 3 and 4 |
| Verify that the dashboard handles missing files or incomplete outputs | Section 5 |
| Check that simulated locations and sample SAR images are not presented as geographically linked | Section 6 |
| Document integration issues and assign them to the component owner | Section 8 |
| Final test of the Detect → Predict → Respond demonstration | Section 7 |

## 1. Summary

| Area | Result |
| --- | --- |
| Tests | 109 pass, 14 skipped (drift tests, OpenDrift not installed), after installing `pytest`; before that, none of the routing tests loaded (E4) |
| Detection outputs | Scores shown on the dashboard; **no mask or scene image (E1)** |
| Drift outputs | Pass the checker; release 23 Oct 2026 12:00 UTC, which matches D3 |
| Routing outputs | Pass the checker; built from the same drift run |
| Dashboard | No error with all files, with the detection folder missing, or with a cut-off `metrics.json` |
| Labelling | Predict and Respond marked "Simulated scenario"; **the Overview presents detection and drift as one incident (E3)** |
| Demo | Runs Detect → Predict → Respond; **the response time shown is sailing time only (E2)** |

## 2. Tests

1. `py -m unittest discover -s tests`: 6 errors and 14 skipped. All six `test_optimization_phase*.py` files import `pytest`, which `requirements.txt` does not list, so none of the routing tests ran (E4). The 14 skipped tests are the drift tests in `test_drift_simulation.py`, which skip themselves when OpenDrift is not installed.
2. After `py -m pip install pytest`: 109 tests, all pass, 14 skipped.

## 3. Outputs

`py tests/check_outputs.py outputs --gulf`:

| Module | Result |
| --- | --- |
| Detection | 1 problem: no predicted mask (`mask.png` or `<image_id>_mask.png`). Note: no `spill.geojson`, so the detected oil has no map location |
| Drift | OK: 1,000 particles at each hour from 0 to 24 h; labelled synthetic |
| Routing | OK. Notes: the dashboard's response time is the longest sailing time (2.70 h), while the last vessel finishes at 7.54 h including cleanup (`finish_hours`); 1 target not served (`T06`), which the dashboard does not list; labelled synthetic |

The checker builds the shared dataclasses from each file and runs the contract checks in `tests/contract_checks.py`, so passing means the files follow `shared/schemas.py` and the dashboard's file format. For drift it also checks that every feature's `timestamp` equals the release time plus its `hours`, and for routing that every route's targets exist and come from one drift hour that the drift file contains. `--gulf` also checks that every point lies in the Gulf, which catches swapped latitude and longitude. All of these passed.

## 4. Times and links between teams

| Check | Result |
| --- | --- |
| Drift release time (`meta.json`, `start_time`) | `2026-10-23T12:00:00Z`. D3 was first agreed as 20 Oct 12:00 UTC; Omar moved it to 23 Oct on 3 Nov, so the run matches D3 |
| Routing built from this drift run (`summary.json`, `scenario_id`) | `openoil-25.85N-55.65E-20261023T1200Z@dispatch6h`: the drift run's ID, release point and release time, plus a dispatch 6 h after the release |
| File locations | All files load from `outputs/detection/`, `outputs/drift/` and `outputs/routing/`, the folders the dashboard reads |

## 5. Dashboard with missing or broken files

| Case | Result |
| --- | --- |
| Real outputs, which are incomplete: scores but no mask or radar image | Detect shows the scores with no error; the checker reports the missing mask (E1) |
| All files | Every page loads with no error box; the maps show on Predict and Respond |
| `outputs/detection/` renamed (missing) | Detect shows "No satellite scene analysed yet"; the Detect dot in the top bar turns grey ("No data yet"); the Predict and Respond dots stay violet |
| `metrics.json` cut off mid-file | Detect shows "Part of this result couldn't be displayed. The rest of the analysis is shown below." and no crash |

## 6. Labelling and geographic claims

| Page | Text | Assessment |
| --- | --- | --- |
| Overview | Detect marked "Live data"; Predict and Respond marked "Simulated scenario" | The labels are correct |
| Overview | "Incident response flow: Follow one incident through the three stages of the response", above Detect marked "Live data" and Predict and Respond marked "Simulated scenario" | **Misleading (E3):** the detected scene has no location and the drift starts from a synthetic release point, so the radar image on Detect and the oil on Predict are not the same incident |
| Detect | "Scores from 0 to 1 on images the model never saw in training" | **Overstated (E5):** the same validation images were used to choose the checkpoint; `detection/evaluate.py` records: "Provider validation split used for model selection; not an independent test set." |
| Detect | "A U-Net model reads SAR imagery imagery ..." | Typo (E6) |

## 7. Detect → Predict → Respond demonstration

- **Overview:** response time tile 2.7 h, "Until the last vessel completes its route".
- **Detect:** Dice 0.87, IoU 0.77, precision 0.85, recall 0.89; the checker reports no mask (E1).
- **Predict:** stepping through Now, +6 h, +12 h and +24 h, the oil moves.
- **Respond:** 2 vessels. RAK-FRV-FALCON visits T05 → T02 → T04 → T03 and RAK-OSRV-SAQR visits T01; recovered oil 55.9 + 145.3 = 201 m³. The "Time to finish (h)" column shows 2.01 and 2.70, the sailing times; the checker reports that the last vessel finishes at 7.54 h including cleanup (E2).

## 8. Issues

| ID | P | Owner | Issue | Evidence | Suggested fix |
| --- | --- | --- | --- | --- | --- |
| E1 | P1 | Ayham | No mask or radar image in `outputs/detection/`, so the Detect page shows scores without a picture. The shared `prediction_comparisons/*.png` and report galleries put the radar image, reference mask and prediction in one picture, which the dashboard cannot read | Checker problem, section 3; Team A SharePoint folder | For each demo scene: `python -m detection.evaluate --checkpoint best.pth --image <scene>.png --output-dir outputs/detection` (writes `<scene>_mask.png`), and copy the scene to `outputs/detection/<scene>_image.png` |
| E2 | P2 | Obeid | Response time shows 2.7 h (sailing only) on the Overview and Respond pages, and the "Time to finish (h)" column shows sailing times; D2 says the headline is completion including cleanup (7.54 h) | Sections 3 and 7 | Read `finish_hours`; show completion time as the headline and sailing time separately, both labelled |
| E3 | P2 | Obeid | The Overview presents detection and drift as one incident | Section 6 | When there is no `spill.geojson`, say that the radar scene has no location yet and the forecast starts from a synthetic release point |
| E4 | P3 | Omar | `pytest` is not in `requirements.txt`, so after a normal setup none of the routing tests run | Section 2 | Add `pytest` to `requirements.txt` |
| E5 | P3 | Obeid, Ayham | "Images the model never saw in training" overstates independence | Section 6 | "Validation images (also used to choose the checkpoint)" |
| E6 | P3 | Obeid | Typo "SAR imagery imagery" on the Detect page | Section 6 | Remove the repeated word |
| E7 | P3 | Obeid | Unserved targets are not shown on the Respond page (`T06` in this plan) | Checker note, section 3 | List `unserved_target_ids` from `summary.json` on the Respond page |

## 9. Not tested

- Demo sites S2, S3 and S4 (`outputs/sites/S2` to `S4`), which Team B will share after Nihal's validation; this test used S1. At S3, 444 of the 1,000 particles are stranded on the coast by 24 h, a case not covered here.
- The 14 drift tests, because OpenDrift is not installed on the laptop.
- The dashboard's built-in demo scenario (gear menu → Demo scenario).
- The dashboard without internet, or on the venue network.
- Other screen sizes, such as a projector.
- Broken drift or routing files, and drift and detection without routing.

## 10. How to reproduce

```powershell
py -m pip install pytest
py -m unittest discover -s tests
py tests/check_outputs.py outputs --gulf
py -m pip install -r dashboard/requirements.txt
py -m streamlit run dashboard/app.py
```

`outputs/` holds the SharePoint files listed under **Inputs**.
