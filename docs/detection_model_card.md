# Ayham's U-Net baseline and team handoff

## Delivered scope

A basic PyTorch U-Net, dataset loading and archive audit tools, a training loop
with validation/checkpoint/resume support, and a tested prediction interface.
The model was trained on the supplied Refined Deep-SAR SOS archives. This is a
research baseline for pixel segmentation; it does not predict drift or vessel routes.

## Completed experiment

| Setting | Value |
| --- | --- |
| Dataset | [Refined Deep-SAR Oil Spill (SOS), v1](https://zenodo.org/records/15298010) |
| Training / validation | 6,455 / 1,615 paired images; provider splits retained |
| Input | 256x256 RGB PNG, float32 divided by 255 |
| Target | Grayscale mask >127 means oil; otherwise background |
| Architecture | Four-level U-Net, base width 32, 7,846,657 trainable parameters |
| Loss | 0.5 BCEWithLogits + 0.5 soft Dice |
| Optimizer | Adam, starting learning rate 0.0003; plateau scheduler |
| Batch / seed | 8 / 42 |
| Augmentation | Paired horizontal and vertical flips, p=0.5 each, training only |
| Completed epochs | 15; resumed from the saved epoch-8 state |
| Selected checkpoint | Epoch 12, highest validation Dice |
| Inference threshold | 0.5 |
| Training environment | Windows, Python 3.10, PyTorch 2.7.1+cu118, GTX 1070 |

Validation results from reloading `best.pth` and evaluating all 1,615 pairs:

| Metric | Value |
| --- | ---: |
| Oil Dice / pixel F1 | 0.8689371265 |
| Oil IoU | 0.7682482972 |
| Oil precision | 0.8459312465 |
| Oil recall | 0.8932293213 |

These metrics use global pixel counts (micro averaging), not a mean of per-image
scores. TP=25,572,373; FP=4,657,475; FN=3,056,751; TN=72,554,041. The IoU above
is for oil only. If reporting the average of oil and background IoU instead,
the corresponding value is 0.8360713733; label this separately as two-class mIoU.

## Get and use the trained weights

The repository deliberately excludes datasets and checkpoint binaries. **Request
`best.pth` from Ayham through the team's separate file-sharing channel.** No public
checkpoint download URL has been published. Cloning this branch gives the code,
not the learned weights. Place the received file at `models/oil_unet/best.pth`.

The completed baseline file is 31,402,525 bytes. Verify its SHA-256 before comparing
results or integrating it:

```text
f6ee7c3692f02629bf06cab7b9e5123a399f43f697e0f628037bc7ee0a31939b
```

On PowerShell:

```powershell
Get-FileHash models/oil_unet/best.pth -Algorithm SHA256
```

After installing the detection dependencies as described in the
[training guide](detection_training.md), predict a single image from the repository root:

```powershell
python -m detection.evaluate --checkpoint models/oil_unet/best.pth --image "C:/path/to/sar_patch.png" --output-dir outputs/predictions --device cpu
```

The training images and reference masks are not required for this command. The
input should be an SAR image patch prepared similarly to the training PNGs.
Large satellite scenes need a separately validated tiling/georeferencing workflow;
resizing an entire scene into one patch is not a validated use of this model.

For Python/dashboard integration:

```python
from pathlib import Path
from detection.evaluate import predict

result = predict(
    checkpoint_path=Path("models/oil_unet/best.pth"),
    image_path=Path("path/to/sar_patch.png"),
    output_dir=Path("outputs/predictions"),
    device="cpu",
)
# result.mask_path points to a PNG: 255 = predicted oil, 0 = background.
# Its dimensions match the original input image.
```

The checkpoint stores `model_state_dict`, architecture/preprocessing `config`,
epoch, and validation results. `load_model(path, device)` returns the restored
model and checkpoint dictionary for integrations that want to cache the model.
`build_model()` alone creates random weights and must not be used as a trained detector.

## Responsibilities for the next team steps

| Teammate | Available interface | Remaining work |
| --- | --- | --- |
| Yara | `OilSpillDataset`, `prepare_data.py`, audit report generation | Review annotation quality and identify source scenes/crops; the file audit alone cannot establish scene independence. |
| Sumaia | `evaluate()`, `confusion_counts()`, `metrics_from_counts()`, example galleries | Extend evaluation with per-image/per-sensor results, small spills, empty-mask false alarms, and independent test scenes. |
| Obeid | `predict()` returning `DetectionOutput` | Connect explicit dashboard actions, display the original image and mask, and handle missing checkpoint/input errors. |
| Drift team | Optional geographic fields in `DetectionOutput` | Supply a real georeferencing adapter and release time before consuming detections. Pixel coordinates cannot seed physical drift. |

`oil_coordinates` and `confidence` are currently `None`; neither georeferencing
nor calibrated image-level confidence is supplied by this baseline. The example
gallery uses six evenly spaced filenames without selecting for good scores.

## Evidence and limits

- All supplied pairs were readable and matched in name and dimensions. No exact
  decoded image duplicates were found within or across the provider splits.
- Source-scene independence is unverified: different patches may still come from
  a common acquisition/event. Matching file hashes does not detect that relationship.
- The validation set selected the best epoch and controlled the scheduler, so
  these are development scores, not untouched final test results.
- Results reflect one seed and a resumed run. Multiple seeds and independent
  scenes are needed for stronger comparisons; no state-of-the-art claim is made.
- Annotation correctness, small-spill reliability, look-alike rejection, and
  transfer to new Gulf scenes still need team review and testing.
- Unit checks use generated tiny inputs, including the train/save/resume/evaluate/
  predict path. They require no satellite dataset and create no committed artifacts.

Dataset archive SHA-256 values, for identifying the exact supplied version:

```text
images.zip: a39aa7bd582d5aa8710c1a8e6d9932cdde8d96688df53a26c7428e19265c9cf2
masks.zip:  2463682b13bd0a404ba8dce29734176622f2c3f1e231560d0b73dc3c9a0f143c
```

Local audit JSON, training history, metrics JSON, and galleries can be regenerated
using the training guide. Keep those generated files and both ZIPs outside Git.
