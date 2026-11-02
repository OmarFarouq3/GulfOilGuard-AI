# Validation plan

Use standard-library `unittest` for lightweight contracts and adapters; add tools only when justified. No dataset, provider credentials, or training is required for unit checks.

Planned coverage: mask pairing/class encoding; metrics with empty and known masks; coordinate order and missing georeferencing; UTC and environmental coverage; 6/12/24-hour trajectories; vessel constraints and infeasible status; baseline fairness; dashboard empty/error states. Use tiny, explicitly synthetic inputs authored for tests, never copied satellite images.

`test_model.py` checks the implemented U-Net using synthetic tensors: shape preservation, custom channels, gradient flow and weight updates, checkpoint round trips, and invalid inputs. It requires PyTorch but does not import the dataset loader or read satellite files. Run discovered tests from the repository root with `python -m unittest discover -s tests -v`.

For an additional learning check, run `python -m detection.smoke_test`. It fits two synthetic rectangles with the default U-Net on CPU. This is a model sanity check, not a measure of real oil-spill performance. Other component tests remain planned.

`test_training.py` adds synthetic PNG checks for paired transforms, mask threshold boundaries, missing/misaligned pairs, known and empty segmentation metrics, and a full train/save/resume/evaluate/predict cycle. These checks require NumPy and Pillow as well as PyTorch. All training fixtures are created in temporary directories; no downloaded imagery is used by unit tests.

## Dashboard tests (pytest)

`tests/dashboard/` covers the Overview click -> random image -> Detect / Predict / Respond flow: image listing and ids, selection state and map-click parsing, scenario translation, the detection subprocess adapter (stubbed), the pages through Streamlit's `AppTest`, and an import guard (no torch / opendrift / ortools / `detection` under `dashboard/`). They use pytest (`pip install -r requirements-dev.txt`) and generate their images in temporary folders, so they never read the git-ignored `assets/images` or write to `outputs/`.

```powershell
python -m pytest tests/dashboard        # dashboard only
python -m pytest tests                  # everything (torch / scipy / ortools tests need those packages)
```

`test_inference_e2e.py` runs the real U-Net on a real image and is skipped unless the checkpoint (`GOG_CHECKPOINT` or `runs/unet_refined_sar/best.pth`), images in `assets/images` (or `GOG_IMAGE_DIR`) and an interpreter with torch (`GOG_DETECTION_PYTHON`) are available. `unittest discover` does not collect `tests/dashboard/` (no `__init__.py`).
