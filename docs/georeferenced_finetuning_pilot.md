# Georeferenced Sentinel-1 fine-tuning pilot

## Decision for the demo

Use the original labelled images when demonstrating detection accuracy. The
georeferenced Sentinel-1 scenes at A-D have usable CRS, transforms and acquisition
metadata, so predicted pixels **can** be converted to coordinates. Their predicted
masks are not verified oil boundaries. Do not describe a drift run seeded from
those masks as a validated spill forecast.

## Data and preprocessing

The [Garcia-INPE dataset](https://github.com/Garcia-INPE/oilspill-detection-dataset)
contains 173 Sentinel-1 image/mask pairs from the Cantarell region of the **Gulf of
Mexico**, with aligned georeferenced GeoTIFFs and polygon labels. Its published
splits are grouped by source image: 108 training, 43 validation and 22 test tiles.
The slick class combines oil spills and seepage; it does not label UAE scenes.

The pilot started from Ayham's `runs/unet_refined_sar/best.pth`. It used the
dataset's published RGB PNGs, resized each 800x600 tile to the checkpoint's
256x256 input, divided by 255, and treated mask values greater than zero as
slick (including value 2 found in some masks). Image resizing was bilinear;
mask resizing was nearest-neighbor. Predictions were restored to 800x600 with
bilinear interpolation, then thresholded at the checkpoint's 0.5 threshold.
The 8-bit RGB PNG is paired with a georeferenced TIFF, but the pilot did not
train on raw 16-bit backscatter or use the geo transform during training.

## Exploratory results

Micro metrics pool pixel counts across the 22 test tiles. Validation IoU
selected epoch 6 from the six-epoch run; test tiles were not used for gradient
updates or checkpoint selection. This is a small transfer pilot, and the test
set had already been inspected in earlier preprocessing trials, so it is not a
new blind benchmark.

| Checkpoint | Test IoU | Dice | Precision | Recall | Predicted slick pixels |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original | 0.022 | 0.043 | 0.022 | 0.910 | 44.82% |
| Garcia fine-tuned | 0.510 | 0.676 | 0.701 | 0.652 | 1.01% |

The reference masks contain slick in 1.09% of test pixels. Fine-tuning reduced
the original model's broad overprediction **on this Mexico dataset**.

The fine-tuned model was also run on the unlabelled UAE demo patches. It marked
less area as slick than the original checkpoint, but still marked 8.7% of site A
on a 3 October pre-event scene and 3.7% there on 24 October. The pre-event
image is only a diagnostic; it has no verified clear-water mask. The UAE results
are therefore **not** accuracy measurements. The UAE inputs were made from RTC
VV power using dB conversion and fixed -25 to 0 dB clipping, whereas Garcia's
published PNG conversion is a different image pipeline. Distribution transfer
to A-D remains unvalidated.

## Reproduce locally

Keep the dataset, checkpoint and generated outputs outside Git. Download the
published dataset with its `splits/` and `IMAGES/` directories, then run from
the repository root:

```powershell
.\.venv-1\Scripts\python.exe -m detection.finetune_garcia `
  --dataset-root datasets\garcia `
  --checkpoint runs\unet_refined_sar\best.pth `
  --output-dir runs\unet_garcia_finetune
```

The command saves `best.pth` and `results.json` in the ignored output directory.
The current local pilot artifacts are in
`outputs/external_sentinel1_validation/garcia/finetuned_pilot/`; they are not
committed. The script checks that source scene groups do not cross splits.

For the UAE sites, the next step toward a defensible Detection -> Drift link is
an independently labelled SAR scene at those locations (including clear water
and lookalikes), scored after fixing preprocessing and the checkpoint. The
geographic metadata is already available; trustworthy spill labels are the gap.
