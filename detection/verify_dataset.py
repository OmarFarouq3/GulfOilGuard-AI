
from pathlib import Path
from collections import Counter
import hashlib
import numpy as np
from PIL import Image

BASE = Path("/Users/yarazaben/Downloads/GulfOilGuard-AI-main/detection")

def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def verify_split(split):
    image_dir = BASE / "images" / split
    mask_dir = BASE / "masks" / split

    images = {p.name: p for p in image_dir.glob("*.png")
              if not p.name.startswith("._")}
    masks = {p.name: p for p in mask_dir.glob("*.png")
             if not p.name.startswith("._")}

    missing_masks = sorted(set(images) - set(masks))
    extra_masks = sorted(set(masks) - set(images))
    matched = sorted(set(images) & set(masks))

    dimension_errors = []
    unreadable = []
    label_counts = Counter()
    image_hashes = {}
    mask_hashes = {}
    image_sizes = Counter()
    mask_sizes = Counter()

    for name in matched:
        try:
            with Image.open(images[name]) as im:
                image_sizes[im.size] += 1
                image_size = im.size

            with Image.open(masks[name]) as m:
                mask_sizes[m.size] += 1
                mask_size = m.size
                values, counts = np.unique(
                    np.asarray(m.convert("L")),
                    return_counts=True
                )
                label_counts.update({
                    int(v): int(c)
                    for v, c in zip(values, counts)
                })

            if image_size != mask_size:
                dimension_errors.append(name)

            image_hashes[name] = file_hash(images[name])
            mask_hashes[name] = file_hash(masks[name])

        except Exception as e:
            unreadable.append((name, str(e)))

    def duplicate_groups(hashes):
        groups = {}
        for name, digest in hashes.items():
            groups.setdefault(digest, []).append(name)
        return [names for names in groups.values()
                if len(names) > 1]

    print(f"\n{'=' * 50}")
    print(f"{split.upper()} DATASET VERIFICATION")
    print("=" * 50)
    print("Images:", len(images))
    print("Masks:", len(masks))
    print("Matched pairs:", len(matched))
    print("Missing masks:", len(missing_masks))
    print("Extra masks:", len(extra_masks))
    print("Dimension mismatches:", len(dimension_errors))
    print("Unreadable pairs:", len(unreadable))
    print("Image dimensions:", dict(image_sizes))
    print("Mask dimensions:", dict(mask_sizes))
    print("Original mask pixel values:", sorted(label_counts))
    print("Mask pixel counts:", dict(label_counts))

    image_dupes = duplicate_groups(image_hashes)
    mask_dupes = duplicate_groups(mask_hashes)
    print("Duplicate image groups:", len(image_dupes))
    print("Duplicate mask groups:", len(mask_dupes))

    for label, items in [
        ("Missing masks", missing_masks),
        ("Extra masks", extra_masks),
        ("Dimension mismatches", dimension_errors),
        ("Unreadable pairs", unreadable),
        ("Duplicate images", image_dupes),
        ("Duplicate masks", mask_dupes),
    ]:
        if items:
            print(f"{label} examples:", items[:5])

    return image_hashes, mask_hashes


train_images, train_masks = verify_split("train")
val_images, val_masks = verify_split("val")

print("\n" + "=" * 50)
print("TRAIN / VALIDATION OVERLAP")
print("=" * 50)

image_overlap = set(train_images.values()) & set(val_images.values())
mask_overlap = set(train_masks.values()) & set(val_masks.values())

print("Identical image files across splits:", len(image_overlap))
print("Identical mask files across splits:", len(mask_overlap))
print("\nVerification finished!")
