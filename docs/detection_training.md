# Training and using the oil-spill U-Net

Run commands from the **GulfOilGuard-AI repository root**, not its parent directory.
Data, weights, predictions, logs, and image galleries remain ignored local files.
Do not commit them to Git. The code and this guide can be shared in the repository.

## Environment

The tested environment uses Python 3.10, PyTorch, NumPy, and Pillow. Other teams' simulator,
dashboard, and routing dependencies are not needed for detection training.
Install a PyTorch build compatible with your GPU using the
[official installation instructions](https://pytorch.org/get-started/previous-versions/).
Create and activate a virtual environment with a Python version supported by your
chosen PyTorch wheel. For the GTX 1070 used in this run, the tested GPU build is
PyTorch 2.7.1 with CUDA 11.8:

```powershell
python -m pip install torch==2.7.1 --index-url https://download.pytorch.org/whl/cu118
python -m pip install -r detection/requirements.txt
```

For a machine without a compatible NVIDIA GPU, use the CPU wheel instead:

```powershell
python -m pip install torch==2.7.1 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r detection/requirements.txt
```

Use `--device cpu` in the commands below for CPU execution. Virtual environments
are local and are not supplied by cloning the repository.

## Prepare the supplied archives

```powershell
python -m detection.prepare_data --images-zip "C:/path/to/images.zip" --masks-zip "C:/path/to/masks.zip"
```

Replace the example archive paths with the local files downloaded from
[Refined Deep-SAR SOS](https://zenodo.org/records/15298010).
Only `images/{train,val}/*.png` and `masks/{train,val}/*.png` are extracted under
`detection/`; macOS metadata is skipped. Existing files with different contents
are not overwritten. The script reads every image and mask, checks matching
names and sizes, records label histograms, and compares decoded image hashes
across splits. Archive SHA-256 hashes and findings are in `outputs/data_audit.json`.

The supplied archives contain 6,455 training pairs and 1,615 validation pairs,
all 256x256. The audit found no exact duplicate images within or between splits.
All RGB masks have identical R/G/B channels. There are 1,847 training masks with
intermediate grayscale values and none in validation; the existing rule
`grayscale > 127` converts them to binary oil masks. Oil covers approximately
24.94% of training pixels and 27.05% of validation pixels. There are 255 empty
training masks and 76 empty validation masks.

These checks establish file integrity and encoding consistency, not the
scientific correctness of every annotation. Source-scene/crop metadata is absent,
so scene independence and performance on Gulf-region imagery remain unverified.

## Train

```powershell
python -m detection.train --device cuda --epochs 15 --batch-size 8 --audit-path outputs/data_audit.json
```

Defaults use the original 256x256 resolution, all training pairs, three RGB input
channels scaled by 255, the 32-channel-base U-Net (7,846,657 parameters), Adam at
0.0003, and equal BCE/soft-Dice loss weights. Training randomly flips each image
and mask together. Validation uses all validation pairs without augmentation or
gradient updates. The decision threshold is fixed at 0.5.

Validation Dice selects the best checkpoint. A scheduler halves the learning
rate after three epochs without improvement, and early stopping ends training
after five such epochs. The seed and settings are recorded, but GPU algorithms
and worker scheduling can prevent bit-for-bit identical retraining/resuming.

`runs/unet_refined_sar/` contains:

- `best.pth`: selected model weights, model/preprocessing settings, and metrics.
- `last.pth`: latest weights plus optimizer, scheduler, random states, and history
  for resuming at the next epoch.
- `config.json`: run settings and environment version.
- `split_manifest.json`: the exact image names used in each split.
- `history.json`: per-epoch losses, Dice, IoU, precision, recall, and elapsed time.

An existing output directory cannot be silently overwritten. To continue a run:

```powershell
python -m detection.train --device cuda --epochs 20 --batch-size 8 --audit-path outputs/data_audit.json --resume runs/unet_refined_sar/last.pth
```

`--epochs` is the total epoch target, not an additional count. Keep the data,
image size, batch size, model width, initial learning rate, seed, and audit settings
consistent when resuming. The optimizer's scheduled learning rate is restored
from the checkpoint; `--learning-rate` is the original starting rate, not an override.
For a separate experiment, specify a new `--output-dir runs/another_run`.

## Evaluate the saved model

```powershell
python -m detection.evaluate --checkpoint runs/unet_refined_sar/best.pth --device cuda
```

This reloads the saved weights and evaluates all validation pairs. It saves
`outputs/unet_validation/metrics.json` and a gallery `examples.png`, whose six
images are evenly spaced in sorted filename order without selecting by score.
Each row shows input, reference mask, prediction, and prediction overlay.

Metrics aggregate TP/FP/FN over all pixels (micro averaging). Both-empty sets
score 1; undefined precision/recall score 0 when only one foreground set is empty.
Validation scores are development results: this split also selects checkpoints,
so it is not an independent final test set. Sumaia can extend the shared metric
helpers and galleries for the team's broader evaluation.

## Predict an image without its mask

```powershell
python -m detection.evaluate --checkpoint runs/unet_refined_sar/best.pth --image detection/images/val/sentinel_4.png --output-dir outputs/predictions
```

Prediction supports `--device cpu`, `--device cuda`, and `--device auto`, restores the output to the original image size, and
saves `sentinel_4_mask.png`. White means predicted oil; black means background.
`DetectionOutput.oil_coordinates` and `confidence` remain `None`: there is no
georeferencing metadata or calibrated image-level confidence in this baseline.

To share the trained detector, distribute `best.pth` through separate file
storage together with the code revision and preprocessing instructions. It
contains weights and settings; teammates do not need the training images to
perform inference. Keep checkpoints out of Git as required by this project.

See [the baseline model card and team handoff](detection_model_card.md) for the
completed run's metrics, checkpoint checksum, and teammate integration examples.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Tests cover tensor contracts, gradients, paired transformations, label thresholds,
known metrics, checkpoint round trips, resume behavior, and predicted-mask export.
