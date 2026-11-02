
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image

BASE = Path(__file__).resolve().parent

image_folder = BASE / "images" / "val"
mask_folder = BASE / "masks" / "val"


files = [
    "palsar_0.png",
    "palsar_461.png",
    "sentinel_126.png",
    "sentinel_49.png",
    "sentinel_99.png"
]

for filename in files:

    image_path = image_folder / filename
    mask_path = mask_folder / filename

    if not image_path.exists() or not mask_path.exists():
        print("Missing file:", filename)
        continue

    image = np.array(Image.open(image_path).convert("L"))
    mask = np.array(Image.open(mask_path).convert("L"))

    print("\nImage:", filename)
    print("Original shape:", image.shape)
    print("Mask shape:", mask.shape)

    if image.shape != mask.shape:
        print("WARNING: Image and mask dimensions differ!")
        continue

    binary_mask = mask > 127

    fig, axes = plt.subplots(1, 3, figsize=(12, 4))

    # Original SAR image
    axes[0].imshow(image, cmap="gray")
    axes[0].set_title("Original SAR Image")

    # Ground-truth mask
    axes[1].imshow(binary_mask, cmap="gray")
    axes[1].set_title("Ground-Truth Mask")

    # Overlay
    axes[2].imshow(image, cmap="gray")
    axes[2].imshow(
        np.ma.masked_where(~binary_mask, binary_mask),
        cmap="autumn",
        alpha=0.5,
        vmin=0,
        vmax=1
    )
    axes[2].set_title("Mask Overlay on SAR Image")

    for ax in axes:
        ax.axis("off")

    plt.suptitle(filename)
    plt.tight_layout()
    plt.show()
