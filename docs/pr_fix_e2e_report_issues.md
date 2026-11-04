# Fix the dashboard issues from the end-to-end report (E1–E7) and finish integration

Branch `fix/e2e-report-issues` → `main`. This branch fixes the dashboard issues from the end-to-end report (`docs/e2e_test_report.md`) and finishes the integration items. It does not change `outputs/`, `shared/schemas.py`, `tests/check_outputs.py` or `tests/contract_checks.py`. `origin/main` (PR #25, cleanup validation) is merged in, with no conflicts.

## What changed

### End-to-end report (E1–E7)

| Item | Change |
|---|---|
| **E1** detection files | Filenames confirmed (`<scene>_image.png`, `_mask.png`, `_overlay.png`). When the mask isn't there yet, Detect says so plainly, with no error. |
| **E2** response time | The headline is the completion time, the largest `finish_hours`; sailing time is shown separately. A new "Time to finish (h)" column. Without `finish_hours`, the fallback is labelled "(sailing only)". The vessel table fits at 1,150 px. |
| **E3** one incident? | The radar scene is not georeferenced, so Overview and Predict say that it and the forecast are not one incident, and they name the synthetic release point. The Overview cards now match their pages. |
| **E4** test runner | `pytest` is now in `requirements.txt`. `tests/README.md` says the routing tests need pytest: `unittest discover` never collects them. |
| **E5** validation wording | Every per-image score on Detect is described as a validation score: those images were also used to choose the checkpoint, so it is not an independent test. |
| **E6** typos | A test scans every dashboard string and the README for repeated words. |
| **E7** unserved targets | Respond lists every unserved patch with its volume, e.g. "Not served: 1 of 6 oil patches: T06 (0.4 m³)". |

### Integration and follow-up

| Item | Change |
|---|---|
| **P1** unreadable drift file | A broken site `drift.geojson` now shows "could not be read" on Predict, with the reason under Diagnostics. |
| **A1** `finish_hours` | Defined as sailing out, between patches and back to port, plus cleanup, counted from dispatch (checked in `optimization/`). The tile, caption, column tooltips, comparison rows, README and `docs/integration_plan.md` D2 all use this wording. |
| **A2** precomputed results | Predict and Respond say they show precomputed results ("… Nothing is re-simulated here", "… Nothing is re-optimised here"; the exact wording is under P3). The buttons now read "Show the drift forecast" and "Show the response plan". "Run detection" keeps its name, because it does run the U-Net. |
| **B1** | The simulated-detection caption is cleaned up. The README says to launch from the repo root. |
| **B2** | `tests/verify_metrics.py` recomputes the dashboard's numbers from the files with plain JSON: 154 checks, all matching. |
| **A3** | `tests/test_unet_inference.py`: the real checkpoint on a real validation image, scored against its labelled mask. The scores match `outputs/report/per_image_metrics.csv`. |
| **C1** no team names | Nothing a viewer sees names a team or a person. Text read from data files (run notes, plan messages, warnings, site names) is neutralised before display, by `services/files.display_text`. A guard test renders every page for no site, the demo and S1–S4 using the real outputs. It also scans the source strings and injects names into data files to check they come out neutralised. |
| **C2** no overall accuracy | The "Overall model accuracy" section is gone from Detect. The page shows the analysed scene: its image, mask, overlay, its own validation score when the report has one, and the slick on the map. `metrics.json` is still part of the contract, but only its `split` and `checkpoint_sha256` are read. |
| **D2** live runs | **Run detection** now writes to `runs/dashboard/detection/` (git-ignored; `GULFOILGUARD_RUNS` overrides it), never into `outputs/`. A click no longer adds files to the shared outputs or changes what the next session shows. |
| **D1** slow or failed runs | Under CPU load, Detect used to show no result and no message for 0.5–4.6 s after each run. Now: <ul><li>The model runs in a worker thread. Detect says "Detection is still running on this image (N s so far)", also after leaving the page and coming back.</li><li>A failed or timed-out run shows the saved result for that image when there is one, labelled "Detection couldn't run this time … Showing the saved result for this image from an earlier run instead". Otherwise it says there is no saved result.</li><li>A small "Updating…" label covers slow reruns.</li></ul> |
| **D4** | `tests/README.md` says what the real U-Net tests need and where each file comes from. |
| **P1 audit** | `docs/dashboard_provenance_audit.md`: S1–S4 are four separate, precomputed OpenDrift runs from hypothetical release points (not S1 moved around), and each plan is optimised on its own site's run. The release point and time, the oil (Generic Medium Crude, 300 m³), the fleet and its home ports are assumptions. The audit includes a particle-by-particle comparison and lists what the repo can't show. |
| **P2** spill list | A "Spill site" list under the Overview map offers every marker and "No incident selected". It shares the one selection with the map: a marker click shows in the list, and a choice in the list highlights the marker and drives every page. Without internet the map area keeps its height and says "The map needs an internet connection. Choose a site in the list below the map.", so the whole flow works offline. |
| **P3** provenance wording | Every page says what a site is, with values read from its `meta.json`: "Precomputed OpenDrift run `<id>` from a hypothetical release point at `<lat, lon>`, released `<time>`, for 24 h. Driven by ERA5 hourly 10 m wind data and Copernicus Marine … currents. Assumed: the release point and time, and the oil (Generic Medium Crude, 300 m³); this is not an observed spill." "Real OpenDrift forecast" became "OpenDrift run for site S1, made for its own release point (not moved from another site)". "Live data" became "Saved results". "Over the next 24 hours" became "for 24 hours after the release". The demo stays "Simulated scenario" and is listed as an "illustrative demo scenario". |
| **P4** | Predict's time step is kept per site; a newly chosen site opens at its default step, not at the step last viewed for another site. |

## Tests

Clean venv: Python 3.13, `pip install -r requirements.txt -r requirements-dev.txt bottleneck` (OpenDrift 1.14.12, torch 2.15.0). With the real checkpoint, masks and images present. The dashboard suite ran at d44598d; the other commands ran at e36ee61, and nothing they read changed after it (the later commits touch only one dashboard test and `docs/`):

| Command | Passed | Failed | Errors | Skipped |
|---|---|---|---|---|
| `python -m pytest tests --ignore=tests/dashboard -rs -v` | 223 | 0 | 1 † | 0 |
| `python -m pytest tests/dashboard -rs -v` | 701 | 0 | 0 | 0 |
| `python -m unittest discover -s tests` | 128 run, all pass | 0 | 1 † | 0 |
| `python tests/check_outputs.py outputs --gulf` | "All files follow the contract", exit 0 | | | |
| `python tests/verify_metrics.py` | 154 checks, all match, exit 0 | | | |

† `test_drift_simulation.DriftRunTests` tearDownClass fails with `PermissionError [WinError 32]` when deleting the temp `currents_clean.nc` on Windows, after every drift test has passed. This is the drift test's own cleanup, and the branch doesn't touch `drift/` or that test.

Without the git-ignored data (checkpoint, masks, validation images), the U-Net tests skip with a message naming the missing files; see `tests/README.md`.

## Verified in a real browser, and what wasn't

**Verified in a real browser** (headless Chrome, real clicks on the map markers, the list and the buttons):

- **The spill list, online** (27/27 checks): marker → list and list → marker for S1–S4, in reverse and shuffled orders, mixing both. The list, the highlighted marker and the side panel always agree. Page switches keep the site, "No incident selected" clears it, a reload starts with no site, and a second tab inherits nothing.
- **Offline from the start**, with only localhost reachable (49/49 checks): each of S1–S4 chosen in the list, then Detect (the model runs locally), Predict (Now, +6, +12, +24 h, with particles afloat and "valid at" checked against the files, e.g. S3: 999 afloat at 12 h, 556 at 24 h) and Respond (vessels and response time checked against the files).
- **Detect under CPU load through the list** (24 runs): 23 reached a result with no unexplained gap. The one 1.1 s "gap" was between the click and the server's first reply, while the page still showed the image and the button. The other run (the first, on the server's cold start) failed in the test script, which looked for the list before it had rendered; a screenshot taken a moment later shows the page complete. Found in this check and fixed (P4): Predict opened a newly chosen site at the time step last viewed for the previous site.

- S1–S4 through Detect → Predict → Respond, with values matched to `outputs/sites/<id>/`. Also: switching sites, changing pages, a second tab, reload, and 1,150 px screenshots (125/125 checks).
- No team or person names and no accuracy section on any page, including Diagnostics, for no site, the demo and S1–S4. Detect with a mask, without one, with no detection folder and with a truncated `metrics.json` (44/44).
- Detect under CPU load (the dashboard pytest suite plus two busy loops on 8 cores), polled every 0.5 s:
  - **Before D1:** in all 24 runs the page showed no result and no message for a while after the spinner ended (median 1.0 s, worst 4.6 s). The result then appeared in every run.
  - **After D1:** 31 runs reached a result, and the polls never caught the page with no result, no spinner and no message for more than 0.5 s. One run (S4) never reached the Run detection button, and it left no screenshot, so its cause is unknown.
- The new states, on a real model, a no-PyTorch interpreter and an empty runs folder (10/10 checks):
  - "Detection is still running on this image (N s so far)" next to the selected image;
  - after going to Predict and back, the run is not lost, and the result replaces the message without a click;
  - the "Updating…" label during a slow rerun;
  - "Detection couldn't run this time … Showing the saved result for this image from an earlier run instead", with the saved image, mask and overlay, "Run detection again" and "Continue to Predict";
  - "There is no saved result for this image to show instead", with the retry and simulated options.
- Offline: see Known limits.

**Code / AppTest only:** most missing and broken file cases, the 900 px and 1,600 px layouts (screenshots only), and the timeout path itself. A 300 s timeout was not reproduced in the browser; the AppTest uses a stubbed timeout.

## Known limits

**The maps need the internet.** Folium loads Leaflet, jQuery, Bootstrap and Font Awesome from CDNs, and the basemap tiles from Esri.

- With no internet from the start the maps don't render. Everything else works:
  - The Overview map area keeps its size and says to use the **Spill site** list, and every site can be chosen there.
  - Detect, Predict and Respond show the chosen site's results: text, tiles, tables, time steps and the Detect model run, in fallback fonts.
  - Only the maps on Detect, Predict and Respond are missing. They collapse to a thin line, because only the Overview map got the fixed-height fallback.
- If the connection drops after the page has loaded, the maps still draw the slicks, particles and routes on a plain background, without coastline tiles.

Other limits:

- The drift tests: `bottleneck` is missing from `requirements.txt` (without it the drift tests fail to import), and there is the Windows teardown error above.
- The detection scores are validation scores, and the radar scenes are not georeferenced, so they are not linked to any site. Every drift run starts from a hypothetical release point, labelled as such.
- The status label on Predict and Respond stays **Real forecast, simulated release**, as `tests/check_outputs.py` prints it. "Forecast" there means a model prediction for a past week (23–24 Oct 2026), not a forecast of the future; the notes under it say so.
- `?dev=1` shows absolute paths under Diagnostics, by design for developers.
- Twelve files in `outputs/detection/` come from Detect clicks in a dashboard process started at 13:19 on 4 Nov, which still runs the code from before D2: `palsar_383-d6a3e68f_*`, `palsar_384-0d7aee08_*` and `sentinel_415-78e853e6_*` (image, mask, overlay and `_run.json` each). They are not tracked (`outputs/` is git-ignored). Restart that dashboard so it writes to `runs/dashboard/` instead, and delete the files if the detection outputs should not include those scenes.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
