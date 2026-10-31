
from pathlib import Path
from PIL import Image
import numpy as np
import matplotlib.pyplot as plt

base = Path(__file__).resolve().parent

image_dir = base / "images" / "train"

if not image_dir.exists():
    image_dir = base / "images" / "images" / "train"

mask_dir = base / "masks" / "train"

image_files = {
    f.name: f for f in image_dir.glob("*.png")
    if not f.name.startswith("._")
}

mask_files = {
    f.name: f for f in mask_dir.glob("*.png")
    if not f.name.startswith("._")
}

common = sorted(set(image_files) & set(mask_files))

print("Matching pairs:", len(common))
print("Images without masks:", len(set(image_files) - set(mask_files)))
print("Masks without images:", len(set(mask_files) - set(image_files)))

if not common:
    raise ValueError("No matching image-mask pairs found")

filename = common[0]

image = Image.open(image_files[filename]).convert("RGB")
mask = Image.open(mask_files[filename]).convert("RGB")

print("Filename:", filename)
print("Image:", image.size, image.mode)
print("Mask:", mask.size, mask.mode)

mask_array = np.array(mask)

colors, counts = np.unique(
    mask_array.reshape(-1, 3),
    axis=0,
    return_counts=True
)

for color, count in zip(colors, counts):
    print(f"Color: {color}, Pixels: {count}")

print("Unique colors:", len(colors))

fig, axes = plt.subplots(1, 2, figsize=(12, 5))

axes[0].imshow(image)
axes[0].set_title("Satellite Image")
axes[0].axis("off")

axes[1].imshow(mask)
axes[1].set_title("Segmentation Mask")
axes[1].axis("off")

plt.tight_layout()
plt.show()
