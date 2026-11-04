# Validation plan

Use standard-library `unittest` for lightweight contracts and adapters; add tools only when justified. No dataset, provider credentials, or training is required for unit checks.

Planned coverage: mask pairing/class encoding; metrics with empty and known masks; coordinate order and missing georeferencing; UTC and environmental coverage; 6/12/24-hour trajectories; vessel constraints and infeasible status; baseline fairness; dashboard empty/error states. Use tiny, explicitly synthetic inputs authored for tests, never copied satellite images.

`test_model.py` checks the implemented U-Net using synthetic tensors: shape preservation, custom channels, gradient flow and weight updates, checkpoint round trips, and invalid inputs. It requires PyTorch but does not import the dataset loader or read satellite files. Run discovered tests from the repository root with `python -m unittest discover -s tests -v`.

The routing tests (`test_optimization_*.py`) are pytest test functions, not `unittest.TestCase` classes, so `unittest discover` imports them but runs none of them. Run everything except the dashboard tests with `python -m pytest tests --ignore=tests/dashboard` after `python -m pip install -r requirements.txt` (which includes `pytest`). The dashboard tests in `tests/dashboard/` need the dashboard's own packages: `python -m pip install -r requirements-dev.txt`, then `python -m pytest tests/dashboard`.

For an additional learning check, run `python -m detection.smoke_test`. It fits two synthetic rectangles with the default U-Net on CPU. This is a model sanity check, not a measure of real oil-spill performance.

`test_training.py` adds synthetic PNG checks for paired transforms, mask threshold boundaries, missing/misaligned pairs, known and empty segmentation metrics, and a full train/save/resume/evaluate/predict cycle. These checks require NumPy and Pillow as well as PyTorch. All training fixtures are created in temporary directories; no downloaded imagery is used by unit tests.

## Real U-Net inference tests (need local data)

Two test files run the trained model on real radar images, with nothing mocked:

- `test_unet_inference.py` (pytest): loads the checkpoint, predicts the mask of `palsar_0.png`, checks it (image size, values 0/255, some oil and some sea), scores it against the labelled mask and runs `detection.evaluate.evaluate()` on `palsar_0.png` and `sentinel_12.png`.
- `dashboard/test_inference_e2e.py`: one image through the dashboard's real subprocess adapter (`services/inference.py` → `python -m detection.predict_cli`), then the cached second call.

None of their data is in Git (`.gitignore` excludes `checkpoints/`, `*.pth`, `/assets/`, `detection/images/`, `detection/masks/` and `outputs/`). To run them, a teammate needs:

| File or folder | Used by | Where it comes from |
| --- | --- | --- |
| `checkpoints/unet_best.pth` | both | The trained U-Net checkpoint. There is no public download: get `best.pth` through the team's file-sharing channel (`docs/detection_model_card.md`, "Get and use the trained weights"), check its SHA-256 against the value there (`Get-FileHash checkpoints/unet_best.pth`), and save it under this name. `GOG_CHECKPOINT` (environment or `.env`) can point elsewhere for the e2e test only. |
| `detection/masks/val/palsar_0.png`, `detection/masks/val/sentinel_12.png` | `test_unet_inference.py` | The labelled masks: `masks.zip` from [Refined Deep-SAR SOS](https://zenodo.org/records/15298010), unpacked by `python -m detection.prepare_data --images-zip <images.zip> --masks-zip <masks.zip> --report runs/data_audit.json` into `detection/{images,masks}/{train,val}/` (`docs/detection_training.md`; the archive hashes are in the model card). Without `--report` the audit is written to `outputs/data_audit.json`. |
| `assets/images/val/palsar_0.png`, `assets/images/val/sentinel_12.png` | `test_unet_inference.py` | The same validation images: copy `detection/images/val/` to `assets/images/val/` (the dashboard's local image folder). |
| any image in the dashboard's image folder | `test_inference_e2e.py` | `GOG_IMAGE_DIR` (environment or `.env`), else `assets/images/`. |
| PyTorch | both | `pip install -r requirements.txt` for `test_unet_inference.py`. The e2e test runs the CLI with the detection interpreter: `.venv-detect/` if it exists, else `GOG_DETECTION_PYTHON`, else the interpreter running the tests. |
| `outputs/report/per_image_metrics.csv` | `test_unet_inference.py` (optional) | Written by `detection/report.py`. When present, the test also checks that its `palsar_0.png` row matches the scores computed here; without it, that comparison is left out. |

When any of these is missing the tests **skip, they don't fail or error**, and the skip reason names what is missing:

```text
SKIPPED [1] tests/test_unet_inference.py:73: missing real data: checkpoints/unet_best.pth, assets/images/val/palsar_0.png, detection/masks/val/palsar_0.png, assets/images/val/sentinel_12.png, detection/masks/val/sentinel_12.png (masks: detection/masks/val from the dataset's masks.zip)
SKIPPED [1] tests/test_unet_inference.py:82: torch is not installed (No module named 'torch'); pip install -r requirements.txt
SKIPPED [1] tests/dashboard/test_inference_e2e.py:40: no checkpoint (GOG_CHECKPOINT environment variable: not set; GOG_CHECKPOINT in .env: not set; standard layout checkpoints/unet_best.pth: missing; built-in default runs/unet_refined_sar/best.pth: missing)
```

(one line per test; the list names only the files that are actually missing.)

Use `-rs` (`python -m pytest tests -rs`) to see the reasons. `python -m unittest discover -s tests` imports `test_unet_inference.py` without running it (its tests are pytest functions), so it doesn't fail there either. On CPU the four model tests take about a minute.

## Contracts and integration

`contract_checks.py` holds one `check_*` function per shared dataclass in `shared/schemas.py`; each returns a list of problems (empty means it follows the contract). Global WGS84 validation always runs; pass `region=GULF_REGION` to also require points in the Gulf. `test_contracts.py` covers these checks.

`scenarios/` holds synthetic demo scenarios, loaded into the shared dataclasses by `scenario_loader.py` and checked by `test_scenarios.py`.

`check_outputs.py` checks the result files under `outputs/` against the shared contract and the dashboard's file contract (`dashboard/README.md`), including the links between teams. Run it before opening a PR that changes an exporter:

```powershell
python tests/check_outputs.py outputs --gulf --release 2026-10-23T12:00:00Z
```

`--gulf` adds the regional check; `--release` checks that the drift run starts at the agreed time (D3). Both are optional.

`test_check_outputs.py` tests it with small synthetic files in temporary folders. See `docs/integration_plan.md` for the handoffs and open compatibility issues.

