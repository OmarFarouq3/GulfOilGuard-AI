# Dataset Verification Report

## 1. Dataset Overview

The dataset is used for oil-spill detection using satellite radar (SAR) images and segmentation masks. Each image has a corresponding mask that identifies the labeled regions.

The dataset is divided into:

- **Training:** 6,455 image-mask pairs
- **Validation:** 1,615 image-mask pairs
- **Total:** 8,070 image-mask pairs
- **Image and mask dimensions:** 256 × 256 pixels

## 2. Dataset Verification

I created and ran `verify_dataset.py` to check the training and validation datasets.

The verification confirmed that:

- Every image has a corresponding mask with the same filename.
- There are no missing or extra masks.
- There are no unreadable image-mask pairs.
- All image and mask dimensions match.
- No exact duplicate image files were found within either split or between training and validation.

Some identical masks were found. This does not necessarily indicate an issue because different images can share the same segmentation mask.

## 3. Mask Label Analysis

I checked the original pixel values in the segmentation masks.

- **Training masks:** Some contain intermediate grayscale values between 0 and 255, instead of being strictly black and white.
- **Validation masks:** Contain only 0 (black) and 255 (white).

The existing `dataset.py` converts both training and validation masks into binary values using:

```python
mask = (mask > 127).astype(np.float32)
```

This means pixels above 127 become 1, while pixels at or below 127 become 0.

I also visualized an example (`palsar_1260.png`) to compare the radar image, original mask, and binary mask.

The binary conversion preserved the main labeled regions in this example, although small differences were visible around the edges.

### Intermediate Grayscale Pixel Analysis

To measure how widespread intermediate grayscale values are, all 6,455 training masks were analyzed.

- **1,847 masks (28.61%)** contain intermediate grayscale pixel values between 1 and 254.
- **6,105,247 pixels (1.44%)** out of 423,034,880 total training mask pixels contain intermediate grayscale values.

Although 28.61% of training masks contain intermediate grayscale values, these represent only 1.44% of all training mask pixels.

These results help assess how widespread intermediate grayscale values are in the training dataset and provide useful information for evaluating mask preprocessing.

## 4. Conclusion

The dataset passed the image-mask matching, readability, and dimension checks. No exact duplicate images were detected across the training and validation sets.

The mask preprocessing was visually checked on one example.
