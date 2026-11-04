# Validation plan

Use standard-library `unittest` for lightweight contracts and adapters; add tools only when justified. No dataset, provider credentials, or training is required for unit checks.

Planned coverage: mask pairing/class encoding; metrics with empty and known masks; coordinate order and missing georeferencing; UTC and environmental coverage; 6/12/24-hour trajectories; vessel constraints and infeasible status; baseline fairness; dashboard empty/error states. Use tiny, explicitly synthetic inputs authored for tests, never copied satellite images.

`test_model.py` checks the implemented U-Net using synthetic tensors: shape preservation, custom channels, gradient flow and weight updates, checkpoint round trips, and invalid inputs. It requires PyTorch but does not import the dataset loader or read satellite files. Run discovered tests from the repository root with `python -m unittest discover -s tests -v`.

The routing tests (`test_optimization_*.py`) are pytest test functions, not `unittest.TestCase` classes, so `unittest discover` imports them but runs none of them. Run everything except the dashboard tests with `python -m pytest tests --ignore=tests/dashboard` after `python -m pip install -r requirements.txt` (which includes `pytest`). The dashboard tests in `tests/dashboard/` need the dashboard's own packages: `python -m pip install -r requirements-dev.txt`, then `python -m pytest tests/dashboard`.

For an additional learning check, run `python -m detection.smoke_test`. It fits two synthetic rectangles with the default U-Net on CPU. This is a model sanity check, not a measure of real oil-spill performance.

`test_training.py` adds synthetic PNG checks for paired transforms, mask threshold boundaries, missing/misaligned pairs, known and empty segmentation metrics, and a full train/save/resume/evaluate/predict cycle. These checks require NumPy and Pillow as well as PyTorch. All training fixtures are created in temporary directories; no downloaded imagery is used by unit tests.

## Contracts and integration

`contract_checks.py` holds one `check_*` function per shared dataclass in `shared/schemas.py`; each returns a list of problems (empty means it follows the contract). Global WGS84 validation always runs; pass `region=GULF_REGION` to also require points in the Gulf. `test_contracts.py` covers these checks.

`scenarios/` holds synthetic demo scenarios, loaded into the shared dataclasses by `scenario_loader.py` and checked by `test_scenarios.py`.

`check_outputs.py` checks the result files under `outputs/` against the shared contract and the dashboard's file contract (`dashboard/README.md`), including the links between teams. Run it before opening a PR that changes an exporter:

```powershell
python tests/check_outputs.py outputs --gulf --release 2026-10-23T12:00:00Z
```

`--gulf` adds the regional check; `--release` checks that the drift run starts at the agreed time (D3). Both are optional.

`test_check_outputs.py` tests it with small synthetic files in temporary folders. See `docs/integration_plan.md` for the handoffs and open compatibility issues.

