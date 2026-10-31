
from pathlib import Path
import numpy as np
import torch
from PIL import Image
from torch.utils.data import Dataset, DataLoader

class OilSpillDataset(Dataset):
    def __init__(self, image_dir, mask_dir):
        self.image_dir = Path(image_dir)
        self.mask_dir = Path(mask_dir)

        self.files = sorted(
            f.name for f in self.image_dir.glob("*.png")
            if not f.name.startswith("._")
        )

        missing = [
            name for name in self.files
            if not (self.mask_dir / name).exists()
        ]

        if missing:
            raise ValueError(f"Missing masks: {missing[:5]}")

    def __len__(self):
        return len(self.files)

    def __getitem__(self, idx):
        filename = self.files[idx]

        image = Image.open(
            self.image_dir / filename
        ).convert("RGB")

        mask = Image.open(
            self.mask_dir / filename
        ).convert("L")

        image = torch.from_numpy(
    np.array(image, dtype=np.float32)
).permute(2, 0, 1) / 255.0

        mask = np.array(mask)
        mask = (mask > 127).astype(np.float32)
        mask = torch.from_numpy(mask).unsqueeze(0)

        return image, mask


base = Path(__file__).resolve().parent

train_dataset = OilSpillDataset(
    base / "images" / "train",
    base / "masks" / "train"
)

val_dataset = OilSpillDataset(
    base / "images" / "val",
    base / "masks" / "val"
)

train_loader = DataLoader(
    train_dataset,
    batch_size=4,
    shuffle=True,
    num_workers=0
)

val_loader = DataLoader(
    val_dataset,
    batch_size=4,
    shuffle=False,
    num_workers=0
)

images, masks = next(iter(train_loader))

print("Training samples:", len(train_dataset))
print("Validation samples:", len(val_dataset))
print("Image batch shape:", images.shape)
print("Mask batch shape:", masks.shape)
print("Mask values:", torch.unique(masks))
