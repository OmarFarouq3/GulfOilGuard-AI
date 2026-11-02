# Detection evaluation summary

Evaluation of the baseline U-Net (`runs/unet_refined_sar/best.pth`, SHA-256
`f6ee7c36...31939b`) on the validation split (1,615 images, threshold 0.5), produced with
`python -m detection.report`. Per-image scores, `summary.json` and the best/median/worst
galleries are generated locally in `outputs/report/` and are not committed.

## Headline scores

| Metric | Micro (all pixels pooled) | Macro (per-image mean, images with oil) |
|---|---|---|
| Dice | 0.869 | 0.807 |
| IoU | 0.768 | 0.703 |
| Precision | 0.846 | 0.792 |
| Recall | 0.893 | 0.878 |

The dashboard shows the micro scores. Micro scores are dominated by large spills; macro
scores treat every image equally. 1,539 images contain oil and 76 are clean.

## Weaknesses

**1. Small spills.** Per-image Dice falls with spill size (reference oil pixels, 256x256 images):

| Spill size | Images | Mean Dice | Mean precision | Mean recall | Dice < 0.5 |
|---|---|---|---|---|---|
| Small (< 1,000 px) | 43 | 0.507 | 0.445 | 0.789 | 20 |
| Medium (1,000-10,000 px) | 599 | 0.744 | 0.701 | 0.873 | 41 |
| Large (> 10,000 px) | 897 | 0.864 | 0.870 | 0.885 | 9 |

For small spills precision is much lower than recall: the model usually finds the spill but
also predicts extra oil regions around it. Weighting these bins by image count reproduces the
macro Dice (0.807), so the micro/macro gap comes from small and medium spills.

**2. Complete misses are rare but real.** 5 of 1,539 oil images (0.3%) have Dice 0. They have
very small reference patches (median 160 px vs about 12,600 px for a typical oil image),
mostly at the image border (e.g. `palsar_469`, `palsar_659`, `sentinel_353`, `sentinel_529`).
`sentinel_353` has only a few labelled pixels and may be a labelling artifact (flagged for
the dataset review).

**3. False detections on clean images.** The model predicts oil on 15 of 76 images (19.7%)
whose reference mask contains no oil (e.g. `palsar_290`, `palsar_312`, `palsar_395`,
`sentinel_181`, `sentinel_285`, `sentinel_370`). This counts any predicted oil pixel, so tiny
predictions are included; the size and cause of these false regions (look-alikes such as
calm water or rain cells) have not been analysed.

## Threshold

Dice is flat between thresholds 0.4 and 0.7 (0.868-0.869), so 0.5 is a reasonable setting.
Lower thresholds trade precision for recall (0.3: precision 0.81, recall 0.92), which may suit
response use where a missed spill is costlier than a false alarm; this is a team decision.

## Limitations

- The validation split was also used to select the checkpoint, so these are not independent
  test results.
- The dataset is not Gulf-specific; the scores do not show performance on Gulf imagery.
- Size bins use pixel counts at 256x256 and are arbitrary cut-offs.
