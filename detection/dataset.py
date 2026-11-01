"""Paired PNG loading. Importing this module never reads data or creates loaders."""

from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch.utils.data import Dataset


class OilSpillDataset(Dataset):
    """RGB images in [0, 1] and binary masks using grayscale >127 as oil."""

    def __init__(self, image_dir, mask_dir, *, image_size=None, augment=False, exclude=()):
        self.image_dir = Path(image_dir)
        self.mask_dir = Path(mask_dir)
        if not self.image_dir.is_dir() or not self.mask_dir.is_dir():
            raise ValueError(f"Image and mask directories must exist: {image_dir}, {mask_dir}")
        images = {p.name for p in self.image_dir.glob("*.png") if not p.name.startswith("._")}
        masks = {p.name for p in self.mask_dir.glob("*.png") if not p.name.startswith("._")}
        if images != masks:
            raise ValueError(f"Unmatched pairs: missing masks={sorted(images - masks)[:5]}, "
                             f"missing images={sorted(masks - images)[:5]}")
        self.files = sorted(images - set(exclude))
        if not self.files:
            raise ValueError(f"No paired PNG files in {image_dir}")
        if image_size is not None and image_size < 16:
            raise ValueError("image_size must be at least 16.")
        self.image_size = image_size
        self.augment = augment

    def __len__(self):
        return len(self.files)

    def __getitem__(self, idx):
        name = self.files[idx]
        with Image.open(self.image_dir / name) as source, Image.open(self.mask_dir / name) as label:
            if source.size != label.size:
                raise ValueError(f"Image/mask size mismatch: {name}")
            image, mask = source.convert("RGB"), label.convert("L")
            if self.image_size is not None:
                size = (self.image_size, self.image_size)
                image = image.resize(size, Image.Resampling.BILINEAR)
                mask = mask.resize(size, Image.Resampling.NEAREST)
            image = torch.from_numpy(np.array(image, dtype=np.float32)).permute(2, 0, 1) / 255.0
            mask = torch.from_numpy((np.array(mask) > 127).astype(np.float32)).unsqueeze(0)
        if self.augment:
            for dimension in (-1, -2):
                if torch.rand(()).item() < 0.5:
                    image, mask = image.flip(dimension), mask.flip(dimension)
        return image, mask


def main():
    from torch.utils.data import DataLoader
    base = Path(__file__).resolve().parent
    for split in ("train", "val"):
        dataset = OilSpillDataset(base / "images" / split, base / "masks" / split)
        images, masks = next(iter(DataLoader(dataset, batch_size=4)))
        print(f"{split}: {len(dataset)} pairs; images={tuple(images.shape)}, "
              f"masks={tuple(masks.shape)}, labels={torch.unique(masks).tolist()}")


if __name__ == "__main__":
    main()
