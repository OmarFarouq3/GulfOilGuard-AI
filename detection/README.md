# Detection (members 1-3)

Load and preprocess SAR imagery, implement binary U-Net, train and validate, evaluate Dice/IoU/precision/recall, and export masks through `DetectionOutput`.

`dataset.py` is now safe to import: it creates no datasets or loaders until explicitly called. It verifies filename pairing in both directions and image/mask dimensions, supports nearest-neighbor mask resizing, and optionally applies paired flips for training. `inspect_data.py` and `visualization.py` remain standalone inspection scripts; their paths depend on the working directory. `visualize_data.py` explicitly launches the existing visualization script.

Local data convention: `detection/images/{train,val}` and `detection/masks/{train,val}`. No imagery belongs in Git. Confirm mask class encoding before using the existing thresholding with a new dataset. Preserve held-out splits and prevent scene leakage.

`model.py` implements U-Net, `train.py` trains and selects a checkpoint by validation Dice, and `evaluate.py` reloads checkpoints to calculate metrics and export predicted masks. See [the training guide](../docs/detection_training.md) for commands and [the model card](../docs/detection_model_card.md) for the trained baseline results and team handoff. Geographic locations require source CRS and transform metadata; image pixel indices cannot seed drift simulations.

## U-Net (Ayham)

`build_model()` creates an untrained model with four encoder levels, a bottleneck,
and four decoder levels connected to the encoder by skip connections. Each
convolution block contains two 3x3 convolutions and ReLU activations. Max pooling
reduces resolution; bilinear upsampling restores it. The default feature widths
are 32, 64, 128, 256, and 512, followed by a 1x1 output convolution.

- Input: float tensor `[batch, 3, height, width]`, matching the loader's RGB
  images scaled to `[0, 1]`.
- Output: raw logits `[batch, 1, height, width]`, matching the binary mask shape.
- Height and width must each be at least 16. Odd sizes are supported; images
  within one batch still need the same dimensions.
- Use `torch.nn.BCEWithLogitsLoss` directly on logits and float masks containing
  0 or 1. Do not apply sigmoid before this loss.
- For a predicted mask, apply `torch.sigmoid(logits) >= 0.5`. The threshold is a
  starting point to assess on validation data, not an established optimum.
- `base_channels` optionally controls model width. Save this setting alongside
  checkpoints if changing the default; reconstruct the same architecture when
  loading weights. No pretrained weights or extra model packages are needed.

Run this minimal example from the repository root:

```python
import torch
from detection.model import build_model

model = build_model()
images = torch.rand(2, 3, 128, 128)  # Synthetic inputs, not satellite imagery.
model.eval()
with torch.inference_mode():
    logits = model(images)
    predicted_masks = torch.sigmoid(logits) >= 0.5
print(logits.shape)  # torch.Size([2, 1, 128, 128])
```

An untrained model's masks are not meaningful detections. Use `detection.train`
to train on paired data, or `detection.evaluate.load_model` to restore the trained
checkpoint. The supplied archives were audited before training; Yara can review
annotation correctness and scene provenance. Sumaia can use the shared metric
helpers and one-channel predictions for further evaluation and visualizations.

## Test the model without downloading a dataset

The model uses PyTorch only; installing NumPy also avoids PyTorch's optional
NumPy initialization warning. The full project requirements include other teams'
dependencies, which are not required for these checks. For CPU setup in an
activated virtual environment:

```powershell
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install numpy
python -m unittest discover -s tests -p test_model.py -v
python -m detection.smoke_test
```

If using the local `.venv` without activation, replace `python` with
`.\.venv\Scripts\python.exe` in the commands above.

The unit tests check output sizes, custom channels, backpropagation and weight
updates, checkpoint round trips, and input errors. The smoke test trains the
default model for 60 CPU steps on two generated rectangles and checks loss
reduction plus foreground/background recovery. It creates no dataset or
checkpoint files. This verifies that the model can learn a simple mapping;
oil-spill accuracy still requires evaluation on held-out satellite data.

Verified locally on Windows with Python 3.10.0 and PyTorch 2.14.1+cpu: all six
unit tests passed, and the synthetic smoke test reduced BCE loss from 0.7084 to
0.0205 in 60 steps. Results can vary across platforms and PyTorch versions.
