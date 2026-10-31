# Detection (members 1-3)

Load and preprocess SAR imagery, implement binary U-Net, train and validate, evaluate Dice/IoU/precision/recall, and export masks through `DetectionOutput`.

Existing `dataset.py`, `inspect_data.py`, and `visualization.py` are preserved. `visualize_data.py` explicitly launches the existing visualization script. The existing loader reads data at import time; do not import it into the dashboard until the detection team agrees on a refactor. Inspection paths depend on the working directory; run inspection from `detection/`.

Local data convention: `detection/images/{train,val}` and `detection/masks/{train,val}`. No imagery belongs in Git. Confirm mask class encoding before using the existing thresholding with a new dataset. Preserve held-out splits and prevent scene leakage.

`model.py`, `train.py`, and `evaluate.py` are interfaces raising `NotImplementedError`. No training or predictions are implemented here. Geographic locations require source CRS and transform metadata; image pixel indices cannot seed drift simulations.
