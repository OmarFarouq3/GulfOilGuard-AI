# Final system test report

Tested by Maria on 5 Nov 2026 on a Windows laptop (Python 3.14). Every result below comes from a command I ran or a page I opened on that laptop; the commands are in section 10.

## 1. What was tested

**Code.** `main` at `5ae8da0` (PR #27, Obeid's dashboard fixes) is the latest integrated branch. Two finished branches are not in `main` yet:

| Branch | Owner | Commits not in main | Content |
| --- | --- | --- | --- |
| `routing-model` | Haris | `2e8415a` | S3 fix: plans again when a patch has grown past the tank space left |
| `feature/final-scenario-validation` | Nihal | `61fd6c1`, `c6a93e1`, `d97b65a`, `a237099` | Four-site validator, validator tests, demo summary |

`git branch -r --no-merged origin/main` still listed both branches at 15:00 on 5 Nov. I merged both into a local branch, `test/final-system` (main + Nihal + Haris), with no conflicts. `git diff test/final-system origin/main --stat` shows that this branch differs from `main` only in those seven files, so these results apply to `main` once the two branches are merged. The local branch was not pushed.

**Setup.** Python packages from `requirements.txt` and `dashboard/requirements.txt`, with `packaging` installed in the main Python folder (one dashboard test starts Python in isolated mode, which does not read per-user packages). Team A's trained model, `best.pth` from the shared drive, copied to `checkpoints/unet_best.pth` (ignored by git).

**Outputs.** The final four-site outputs shared on 5 Nov (`outputs/sites/S1` to `S4` and `outputs/fleet`). S3 is the re-run after Haris's fix: `T01-1` is no longer unserved. `outputs/detection` is the copy from 3 Nov.

**Priority scale.** **P1** blocks the demo or gives a wrong result if the pipeline is re-run. **P2** leaves the project in a state the team should not present (for example, a failing test suite). **P3** is cleanup.

## 2. Summary

| Area | Result |
| --- | --- |
| Test suite | 949 tests: 909 passed, 22 failed, 18 skipped. All 22 failures are in one dashboard test file and come from expected values written for older outputs (section 3) |
| Four sites, contract checker | S1 to S4: drift, routing and files OK. 1 problem, in detection: no predicted mask (open since 3 Nov) |
| Four sites, Nihal's validator | 0 FAIL at every site (474 checks OK, 13 warnings). Each site has its own OpenDrift run |
| Detection, prediction and routing consistency | Consistent at all four sites (section 5) |
| Obeid's corrections | Response time and scenario isolation confirmed at all four sites (section 6) |
| Warnings | None critical for the code. The S3 coastline warning must be stated in the pitch (section 7) |
| Integration | **Haris's S3 fix and Nihal's validator are not in `main`** (P1 and P2, section 8) |

## 3. Test suite

`py -m pytest tests -q -rfs` on `test/final-system`, with the final outputs and the setup in section 1:

| Result | Count |
| --- | ---: |
| Passed | 909 |
| Failed | 22 |
| Skipped | 18 |
| Total | 949 |
| Subtests passed | 61 |

The two test files that depend on the setup, `tests/dashboard/test_import_guard.py` and `tests/dashboard/test_inference_e2e.py`, were run on their own once it was in place, and the counts include those runs. `test_inference_e2e.py` passes a real radar image from `assets/images` through the trained U-Net with PyTorch, so the dashboard's live detection works end to end on this laptop.

**Failed (22), all in `tests/dashboard/test_respond_page.py`.** The tests compare the Respond page with numbers taken from older outputs. The page itself shows the values in the final files (section 6). Examples:

| Test | Test expects | Final outputs give |
| --- | --- | --- |
| `test_response_time_is_completion_with_sailing_separately[S1]` | 7.6 h | 10.5 h |
| `test_overview_headline_uses_the_completion_time` | 7.6 h | 10.5 h |
| `test_oil_layer_slider_opens_at_the_plans_layer_hour[S1]` | +8 h | +10 h |
| `test_unserved_patch_is_flagged_with_its_volume[S1]` | "1 of 6 oil patches" | "1 of 7 oil patches" |

The other failures in the file have the same cause: plan labels, patch tooltips, map extent, comparison table, share captions, baseline routes, per-vessel comparison, idle vessels and plan assumptions.

**Skipped (18).**

| Tests | Reason |
| --- | --- |
| 14 in `test_drift_simulation.py` | OpenDrift is not installed on the laptop |
| 4 in `test_unet_inference.py` | The two validation images and their reference masks (`assets/images/val/palsar_0.png`, `sentinel_12.png`, `detection/masks/val/...`) are not in the project or on the shared drive; they come from the dataset download |

All optimization tests (`test_optimization_phase1` to `phase6`, `test_optimization_emulsion.py`, including Haris's new S3 test) and Nihal's `test_validate_cleanup.py` passed.

## 4. Four Gulf scenarios

**Contract checker** (`tests/check_outputs.py outputs --sites --gulf --release 2026-10-23T12:00:00Z`):

| Site | Drift | Routing | Files |
| --- | --- | --- | --- |
| S1 | OK | OK | OK |
| S2 | OK | OK | OK |
| S3 | OK | OK | OK |
| S4 | OK | OK | OK |

The one problem reported is in detection: no predicted mask in `outputs/detection` (E1 in the 3 Nov report).

**Nihal's validator** (`optimization.validate_sites --details`, without `--write`):

| Site | Afloat at dispatch (m³) | Stranded by 24 h (m³) | Oil cleaned, optimized / baseline (m³) | Back in port, optimized / baseline (h after dispatch) | Distance change | Checks |
| --- | ---: | ---: | --- | --- | ---: | --- |
| S1 off Ras Al Khaimah | 204.0 | 0.0 | 199.2 / 199.6 | 10.50 / 10.59 | −28.0 % | 129 OK, 3 WARN, 0 FAIL |
| S2 off Umm Al Quwain | 194.3 | 0.0 | 188.4 / 188.5 | 11.82 / 11.85 | 0.0 % | 115 OK, 3 WARN, 0 FAIL |
| S3 off Sharjah / Hamriyah | 200.3 | 81.8 | 196.1 / 195.6 | 11.48 / 11.48 | +3.7 % | 117 OK, 4 WARN, 0 FAIL |
| S4 off Ras Al Khaimah near Dhayah | 208.6 | 0.0 | 204.3 / 204.5 | 11.40 / 12.56 | +1.9 % | 113 OK, 3 WARN, 0 FAIL |

"Own drift run per site: yes. The most similar pair, S1-S3, still differs by 2.14 km (median)." No site is a moved copy of another site's forecast.

The S3 optimized plan cleans 196.1 m³, against 129 m³ before Haris's fix.

## 5. Consistency between detection, prediction and routing

| Check | Result |
| --- | --- |
| Each routing plan comes from its own site's drift run | The contract checker's FILES check passed at all four sites; the Respond page shows each site's own scenario ID (for example `openoil-25.45N-55.35E-20261023T1200Z@dispatch6h` at S3) |
| Release time | 23 Oct 2026 12:00 UTC at all four sites (checker, `--release`) |
| Release points | S1 25.85, 55.65; S2 25.70, 55.40; S3 25.45, 55.35; S4 25.98, 55.85, shown on the Overview and checked by the validator |
| Forecast timestamps | Predict at +6 h shows 23 Oct 18:00 UTC, at +12 h shows 24 Oct 00:00 UTC |
| Dispatch | +6 h after the release (23 Oct 18:00 UTC) on every Respond page |
| Detection and drift | Not linked geographically, and the dashboard says so: "the radar image assigned to it is a sample from the dataset, not taken at that point" |

## 6. Obeid's corrections

Checked in the running dashboard on `test/final-system`, going through Detect → Predict → Respond for each site.

**Response time.** The Response time tile is the completion time (sailing out, cleanup and the trip back to port), and sailing time is shown separately:

| Site | Response time | Sailing time | Distance | Oil recovered | Not served | Matches the files |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| S1 | 10.5 h | 4.4 h | 184.6 km | 199 m³ | T06, 0.4 m³ | Yes |
| S2 | 11.8 h | 4.9 h | 191.4 km | 188 m³ | T05, 0.4 m³ | Yes |
| S3 | 11.5 h | 6.5 h | 206.6 km | 196 m³ | T06, 0.2 m³ | Yes |
| S4 | 11.4 h | 6.2 h | 187.6 km | 204 m³ | T06, 0.4 m³ | Yes |

**Scenario isolation.** With S1's Predict slider at +12 h, I selected S3 and opened Predict: it opened at +6 h (23 Oct 18:00 UTC), not at S1's +12 h. Each Respond page shows its own site's plan, scenario ID and unserved patch, and says it is "optimised on this site's own drift run (not moved from another site)".

**Live detection.** With the trained model in place, the Detect page for S2 ran the real U-Net on `palsar_3.png`: it is labelled "Real detection, simulated location", reports "checkpoint unet_best.pth · threshold 0.5 · 0.8% of the image predicted as oil", and shows the radar image, the predicted mask and the overlay, with the mask and overlay in the same place. Because this image was part of the training data, the page shows no score for it and says why.

**Issues from the 3 Nov report:**

| ID | Issue | Status |
| --- | --- | --- |
| E1 | No mask in `outputs/detection` | Open (contract checker) |
| E2 | Response time showed sailing only | Fixed |
| E3 | Overview presented detection and drift as one incident | Fixed |
| E4 | `pytest` missing from `requirements.txt` | Fixed (`requirements.txt`, line 12) |
| E5 | "Images the model never saw in training" | Fixed: the phrase is gone; `views/detection.py` and `components/flow.py` say the validation split was "also used to choose the checkpoint" |
| E6 | Typo "SAR imagery imagery" | Fixed: no longer in the dashboard code |
| E7 | Unserved targets not shown | Fixed |

## 7. Validation warnings

The validator gave 13 warnings across the four sites and 0 failures. There is no tank or emulsion-capacity warning at any site, so no plan over its tank space is presented as feasible.

| Warning | Sites | Count | Critical? |
| --- | --- | ---: | --- |
| A patch with less than 0.5 m³ left is not served (listed once for the optimized plan, once for the baseline) | All four | 8 | No. The amount is 0.2 to 0.4 m³, and the Respond page lists it |
| Some patches are wider than 1.5 km, so "one skimming position" per patch is an assumption | All four | 4 | No. It is a model limitation, already in `docs/demo_cleanup_summary.md` |
| At S3, 81.8 m³ (444 particles) reaches the coast by 24 h, the first at 11 h; shoreline oil is outside the cleanup plan | S3 | 1 | Not for the code. It must be said in the pitch, so that no one claims the vessels collect all the oil |

## 8. Issues

| ID | P | Owner | Issue | Evidence | Suggested fix |
| --- | --- | --- | --- | --- | --- |
| F1 | P1 | Haris, Omar | Haris's S3 fix (`2e8415a`) is not in `main`. Re-running S3 from `main` would bring back the plan that cleans 129 m³ | `git branch -r --no-merged origin/main`; section 4 | Merge `routing-model` into `main` |
| F2 | P2 | Nihal, Omar | The four-site validator, its tests and the demo summary are not in `main` | Same | Merge `feature/final-scenario-validation` into `main` |
| F3 | P2 | Obeid | 22 tests in `test_respond_page.py` expect numbers from older outputs, so the suite fails with the final outputs | Section 3 | Update the expected values to the final outputs (response time, layer hour, unserved patches, routes) |
| F4 | P3 | Ayham | No predicted mask in `outputs/detection` (E1). The dashboard now runs detection live and saves to `runs/dashboard/`, so this may no longer be needed | Section 4 | Confirm whether a saved mask is still needed for the demo |

## 9. Not tested

- The 14 drift simulation tests (OpenDrift is not installed on the laptop).
- The 4 U-Net tests against reference masks (the validation images and masks are not on the shared drive).
- `main` after the merge of F1 and F2. Once merged, `git diff test/final-system origin/main --stat` should print nothing.
- The dashboard without internet, on the venue network, or on a projector.

## 10. How to reproduce

```powershell
git checkout main
git checkout -b test/final-system
git merge --no-edit origin/feature/final-scenario-validation
git merge --no-edit origin/routing-model
py -m pytest tests -q -rfs -p no:cacheprovider
py -m pytest tests/dashboard/test_inference_e2e.py tests/test_unet_inference.py -q -rs -p no:cacheprovider
py tests/check_outputs.py outputs --sites --gulf --release 2026-10-23T12:00:00Z
py -m optimization.validate_sites --sites-dir outputs/sites --fleet outputs/fleet/gulf_standard.json --details
py -m streamlit run dashboard/app.py
```

`outputs/sites` and `outputs/fleet` hold the final four-site outputs shared on 5 Nov. `checkpoints/unet_best.pth` is Team A's `best.pth` from the shared drive.
