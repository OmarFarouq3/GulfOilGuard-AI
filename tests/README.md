# Validation plan

Use standard-library `unittest` for lightweight contracts and adapters; add tools only when justified. No dataset, provider credentials, or training is required for unit checks.

Planned coverage: mask pairing/class encoding; metrics with empty and known masks; coordinate order and missing georeferencing; UTC and environmental coverage; 6/12/24-hour trajectories; vessel constraints and infeasible status; baseline fairness; dashboard empty/error states. Use tiny, explicitly synthetic inputs authored for tests, never copied satellite images.

`test_model.py` checks the implemented U-Net using synthetic tensors: shape preservation, custom channels, gradient flow and weight updates, checkpoint round trips, and invalid inputs. It requires PyTorch but does not import the dataset loader or read satellite files. Run discovered tests from the repository root with `python -m unittest discover -s tests -v`.

For an additional learning check, run `python -m detection.smoke_test`. It fits two synthetic rectangles with the default U-Net on CPU. This is a model sanity check, not a measure of real oil-spill performance. Other component tests remain planned.

`test_training.py` adds synthetic PNG checks for paired transforms, mask threshold boundaries, missing/misaligned pairs, known and empty segmentation metrics, and a full train/save/resume/evaluate/predict cycle. These checks require NumPy and Pillow as well as PyTorch. All training fixtures are created in temporary directories; no downloaded imagery is used by unit tests.
