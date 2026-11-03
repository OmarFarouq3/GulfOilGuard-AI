# U-Net Prediction Review

## 1. Overview

I reviewed five validation prediction examples generated using the trained U-Net model. Each example included the original SAR image, ground-truth mask, and predicted mask.

The purpose was to check image-mask alignment, review the model's predictions, and identify any noticeable data-quality or preprocessing issues.

I also performed an additional alignment check by overlaying the ground-truth masks on their corresponding original SAR images.

Additional prediction galleries and evaluation metrics were provided from the U-Net validation evaluation. These results are referenced below to document relevant prediction differences and potential issues for further investigation.

## 2. Prediction Review Results

The following table summarizes the five initial prediction examples and their evaluation scores.

The Dice and IoU scores were taken from the provided prediction examples. These metrics were not independently recalculated during this review.

| Image | Dice | IoU | Observation |
|---|---|---|---|
| palsar_0.png | 0.773 | 0.629 | Main oil regions detected, with some differences in boundaries and smaller regions. |
| palsar_461.png | 0.932 | 0.873 | Strong overlap between predicted and ground-truth masks. |
| sentinel_126.png | 0.384 | 0.238 | Noticeable false positives and additional predicted oil regions. |
| sentinel_49.png | 0.875 | 0.779 | Good overall overlap, with some differences in region shapes. |
| sentinel_99.png | 0.814 | 0.687 | Main regions detected, with some differences in shape and thickness. |

### Understanding the Evaluation Metrics

The Dice score and Intersection over Union (IoU) measure how closely the predicted oil-spill regions match the ground-truth masks.

- **Dice Score:** Measures the overlap between the predicted mask and the ground-truth mask. A score of 1 means a perfect match, while 0 means no overlap.
- **IoU:** Measures the intersection (shared pixels) divided by the union (all pixels marked as oil spill in either mask). A higher IoU indicates better agreement.

Both metrics range from 0 to 1, where higher values indicate better segmentation performance.

For example, `palsar_461.png` achieved a Dice score of **0.932** and an IoU of **0.873**, indicating strong agreement between the predicted and ground-truth masks.

In contrast, `sentinel_126.png` achieved a Dice score of **0.384** and an IoU of **0.238**, indicating weaker agreement and more segmentation errors.

## 3. Observations

The strongest overlap among the five initially reviewed examples was observed in `palsar_461.png`, with a Dice score of 0.932.

The weakest result was observed in `sentinel_126.png`, with a Dice score of 0.384. Its predicted mask contained additional white regions not present in the ground-truth mask, indicating false-positive detections.

The remaining examples showed reasonable overlap, with some differences in boundaries and predicted oil-spill regions.

No clear data-quality or preprocessing issues were identified from the five prediction comparisons.

The false positives observed in `sentinel_126.png` indicate a prediction weakness, but they do not necessarily indicate a dataset or preprocessing problem.

## 4. Original Image and Ground-Truth Mask Alignment Check

To further investigate image-mask alignment, I generated overlays for the five validation examples by placing each ground-truth mask directly over its corresponding original SAR image.

The images and masks were loaded using Python, and the ground-truth masks were converted to binary using a threshold of 127, consistent with the dataset preprocessing.

All five original image-mask pairs had matching dimensions of **256 × 256 pixels**.

### Alignment Results

| Image | Alignment Observation |
|---|---|
| palsar_0.png | The highlighted regions generally followed the visible dark patterns in the SAR image. |
| palsar_461.png | The small labeled region was positioned near a dark area on the right side of the image. |
| sentinel_126.png | The labeled region appeared near the lower-left edge, although its boundary was difficult to distinguish. |
| sentinel_49.png | A large portion of the image was labeled as oil spill, making the boundaries harder to assess. |
| sentinel_99.png | The highlighted regions generally followed the branching dark patterns visible in the SAR image. |

### Findings

The overlays showed no obvious shifting, rotation, or flipping between the original SAR images and their corresponding ground-truth masks.

In several examples, the labeled regions generally followed the dark patterns visible in the original images.

However, some boundaries were difficult to distinguish because SAR images contain considerable noise and texture.

In particular, `sentinel_49.png` contained a large labeled region covering most of the image. This is not necessarily a data-quality issue, but the annotation may benefit from further inspection.

Overall, no obvious geometric alignment problems were identified in the five original image-mask pairs. However, the overlay review alone cannot confirm that every annotation is perfectly aligned or correctly labeled.

## 5. Additional Prediction Review

### Overview

Additional best, median, and worst prediction galleries were provided as part of the U-Net validation evaluation, together with per-image metrics.

The results below are taken from these evaluation outputs. They are included to highlight prediction differences and potential issues for further investigation. 

The evaluation covered 1,615 validation images using a prediction threshold of 0.5.

### Overall Evaluation Results

The following metrics were reported in the evaluation results.

| Metric | Score |
|---|---|
| Dice | 0.8689 |
| IoU | 0.7682 |
| Precision | 0.8459 |
| Recall | 0.8932 |

These represent the overall pixel-level (micro-averaged) validation metrics.

### Best Prediction Examples

The best prediction gallery included `sentinel_455.png`, `sentinel_460.png`, `sentinel_591.png`, and `sentinel_798.png`.

All four examples achieved Dice scores of 1.000, indicating perfect agreement between predicted and ground-truth masks.

However, all four examples contained fully positive ground-truth masks, with 65,536 labeled oil-spill pixels each. This means every pixel in the 256 × 256 images was labeled as oil spill.

Although these predictions achieved perfect scores, they do not demonstrate the model's ability to distinguish complex oil-spill boundaries from background regions.

### Median Prediction Examples

| Image | Dice | Observation |
|---|---|---|
| palsar_480.png | 0.845 | Differences between predicted and ground-truth boundaries, including false-positive and false-negative regions. |
| palsar_259.png | 0.845 | Differences around irregular and branching labeled regions. |
| palsar_15.png | 0.845 | Additional predicted regions were visible around some boundaries. |
| palsar_637.png | 0.846 | Differences in the shapes and boundaries of smaller labeled regions. |

These observations describe differences visible in the provided prediction galleries. They do not establish an image-mask alignment or preprocessing error.

### Worst Prediction Examples

The following values were obtained from the provided `per_image_metrics.csv` file.

| Image | Dice | Ground-Truth Oil Pixels | Observation |
|---|---|---|---|
| palsar_469.png | 0.000 | 583 | No overlap with the labeled oil-spill pixels. |
| palsar_659.png | 0.000 | 160 | No overlap with the small labeled region. |
| sentinel_353.png | 0.000 | 1 | The single labeled oil-spill pixel was not detected. |
| sentinel_528.png | 0.961 | 49,466 | High overlap despite appearing in the worst prediction gallery. |

The first three examples had Dice and recall scores of 0.000, indicating that none of their ground-truth oil-spill pixels were detected.

Although `sentinel_528.png` appears in the worst prediction gallery, its Dice score is 0.961. The gallery selection criteria would need clarification to explain this difference.

### Relevant Observations

**1. Small Labeled Regions**

Several examples with small ground-truth oil-spill regions had zero overlap between the predictions and reference masks. This suggests a possible weakness in detecting small oil spills.

**2. Boundary Differences**

The median prediction examples showed differences between predicted and reference boundaries, particularly around irregular shapes.

**3. False-Positive Regions**

Some examples contained predicted oil-spill pixels outside the ground-truth regions.


## 6. Conclusion

The five initially reviewed prediction examples showed no obvious image-mask alignment problems. Most predictions demonstrated reasonable overlap with the ground-truth masks, while `sentinel_126.png` showed noticeable false positives.

The additional overlay check showed that all five original SAR images and ground-truth masks had matching dimensions of 256 × 256 pixels, with no obvious geometric alignment issues observed.

The additional evaluation outputs provided further examples of prediction differences, including missed small labeled regions, boundary differences, and false-positive detections. These observations may help guide future model improvements.

No definite data-quality or preprocessing errors were identified during this review. 
