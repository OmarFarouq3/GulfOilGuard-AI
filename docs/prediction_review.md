# U-Net Prediction Review

## 1. Overview

I reviewed five validation prediction examples generated using the trained U-Net model. Each example included the original SAR image, ground-truth mask, and predicted mask.

The purpose was to check image-mask alignment, review the model's predictions, and identify any noticeable data-quality or preprocessing issues.

I also performed an additional alignment check by overlaying the ground-truth masks on their corresponding original SAR images.

## 2. Prediction Review Results

The following table summarizes the five prediction examples and their evaluation scores.

The Dice and IoU scores were taken from the prediction examples. These metrics were not independently recalculated during this review.

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

The strongest overlap among the reviewed examples was observed in `palsar_461.png`, with a Dice score of 0.932.

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


## 5. Conclusion

The five reviewed prediction examples showed no obvious image-mask alignment problems in the provided comparisons.

Most predictions demonstrated reasonable overlap with the ground-truth masks, while `sentinel_126.png` showed noticeable false positives.

The additional overlay check showed that all five original SAR images and ground-truth masks had matching dimensions of 256 × 256 pixels, with no obvious geometric alignment issues observed.

Some segmentation boundaries were difficult to assess because of the noisy appearance of SAR images, and the large labeled region in `sentinel_49.png` may benefit from further inspection.

No definite data-quality or preprocessing errors were identified during this review.
