"""Fine-tune an existing U-Net on Garcia-INPE's scene-grouped Sentinel-1 splits.

Run from the repository root: python -m detection.finetune_garcia --help
The dataset and source checkpoint are local inputs; neither belongs in Git.
"""

import argparse
import csv
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image
import torch
from torch.utils.data import DataLoader, Dataset

from detection.evaluate import load_model
from detection.train import segmentation_loss


class GarciaTiles(Dataset):
    """Published RGB inputs and masks; the dataset benchmark defines mask > 0 as slick."""

    def __init__(self, root: Path, split: str, image_size: int):
        self.root = root
        self.image_size = image_size
        manifest = root / "splits" / f"{split}.csv"
        if not manifest.is_file():
            manifest = root / f"{split}.csv"
        with manifest.open(encoding="utf-8", newline="") as source:
            self.rows = list(csv.DictReader(source))
        if not self.rows:
            raise ValueError(f"No samples in {split} split")
        for row in self.rows:
            for key in ("image_path", "mask_path"):
                if not (root / row[key]).is_file():
                    raise FileNotFoundError(root / row[key])

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        row = self.rows[index]
        with Image.open(self.root / row["image_path"]) as source, Image.open(
            self.root / row["mask_path"]
        ) as label:
            if source.size != label.size:
                raise ValueError(f"Image/mask size mismatch: {row['sample_id']}")
            size = (self.image_size, self.image_size)
            image = source.convert("RGB").resize(size, Image.Resampling.BILINEAR)
            mask = label.convert("L").resize(size, Image.Resampling.NEAREST)
            x = torch.from_numpy(np.asarray(image, dtype=np.float32)).permute(2, 0, 1) / 255
            y = torch.from_numpy((np.asarray(mask) > 0).astype(np.float32))[None]
        return x, y


@torch.inference_mode()
def score(model, tiles: GarciaTiles, device: torch.device, threshold: float):
    """Pool pixel counts at the published 800x600 resolution, as in the pilot."""
    model.eval()
    counts = np.zeros(4, dtype=np.int64)
    for row in tiles.rows:
        with Image.open(tiles.root / row["image_path"]) as source, Image.open(
            tiles.root / row["mask_path"]
        ) as target:
            reference = np.asarray(target.convert("L")) > 0
            scaled = source.convert("RGB").resize(
                (tiles.image_size, tiles.image_size), Image.Resampling.BILINEAR
            )
            image = torch.from_numpy(np.asarray(scaled, dtype=np.float32)).permute(
                2, 0, 1
            )[None].to(device) / 255
            probabilities = torch.nn.functional.interpolate(
                model(image).sigmoid(), size=reference.shape,
                mode="bilinear", align_corners=False,
            )[0, 0].cpu().numpy()
        predicted = probabilities >= threshold
        counts += (
            int((predicted & reference).sum()),
            int((predicted & ~reference).sum()),
            int((~predicted & reference).sum()),
            int((~predicted & ~reference).sum()),
        )
    tp, fp, fn, tn = map(int, counts)
    total = tp + fp + fn + tn
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "iou": tp / (tp + fp + fn) if tp + fp + fn else 1.0,
        "dice": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 1.0,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "reference_fraction": (tp + fn) / total,
        "predicted_fraction": (tp + fp) / total,
    }


def source_groups(tiles):
    return {row["sample_id"].rsplit("_TILE_", 1)[0] for row in tiles.rows}


def run(dataset_root: Path, checkpoint: Path, output_dir: Path, epochs: int,
        batch_size: int, learning_rate: float, device_name: str, seed: int):
    if epochs < 1 or batch_size < 1 or learning_rate <= 0:
        raise ValueError("epochs and batch_size must be positive; learning_rate must be > 0")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"Output directory is not empty: {output_dir}")
    device = torch.device("cuda" if device_name == "auto" and torch.cuda.is_available()
                          else "cpu" if device_name == "auto" else device_name)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA requested but unavailable")
    torch.set_num_threads(4)
    torch.manual_seed(seed)
    model, source = load_model(checkpoint, device)
    config = source["config"]
    image_size = int(config["image_size"])
    threshold = float(config["threshold"])
    splits = {name: GarciaTiles(dataset_root, name, image_size)
              for name in ("train", "val", "test")}
    groups = {name: source_groups(tiles) for name, tiles in splits.items()}
    if any(groups[a] & groups[b] for a, b in (("train", "val"), ("train", "test"), ("val", "test"))):
        raise ValueError("Source scene groups overlap across splits")
    output_dir.mkdir(parents=True, exist_ok=True)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    loader = DataLoader(splits["train"], batch_size=batch_size, shuffle=True,
                        num_workers=0, generator=torch.Generator().manual_seed(seed))
    baseline_val = score(model, splits["val"], device, threshold)
    history = []
    best_iou = -1.0
    for epoch in range(1, epochs + 1):
        started = time.perf_counter()
        model.train()
        losses = []
        for images, masks in loader:
            optimizer.zero_grad(set_to_none=True)
            loss = segmentation_loss(model(images.to(device)), masks.to(device))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            losses.append(loss.item())
        val = score(model, splits["val"], device, threshold)
        row = {"epoch": epoch, "train_loss": float(np.mean(losses)),
               "val": val, "seconds": time.perf_counter() - started}
        history.append(row)
        print(f"Epoch {epoch}/{epochs}: loss={row['train_loss']:.4f}, "
              f"val IoU={val['iou']:.4f}", flush=True)
        if val["iou"] > best_iou:
            best_iou = val["iou"]
            saved_config = dict(config)
            saved_config.update(finetuned_on="Garcia-INPE train split",
                                mask_encoding="grayscale > 0",
                                normalization="published RGB / 255")
            torch.save({"format_version": 1, "model_state_dict": model.state_dict(),
                        "config": saved_config, "epoch": epoch,
                        "source_checkpoint": str(checkpoint)}, output_dir / "best.pth")
    chosen, details = load_model(output_dir / "best.pth", device)
    report = {
        "dataset": "Garcia-INPE/oilspill-detection-dataset",
        "geography": "Cantarell, Gulf of Mexico; not UAE",
        "split_sizes": {name: len(tiles) for name, tiles in splits.items()},
        "source_groups": {name: sorted(value) for name, value in groups.items()},
        "preprocessing": f"Published RGB bilinear-resized to {image_size}x{image_size}, divided by 255; "
                         "mask nearest-resized, value > 0; output probabilities bilinear-restored "
                         "before thresholding",
        "threshold": threshold,
        "best_epoch": details["epoch"],
        "baseline_val": baseline_val,
        "finetuned_val": score(chosen, splits["val"], device, threshold),
        "finetuned_test": score(chosen, splits["test"], device, threshold),
        "history": history,
        "limitations": "This evaluates slick masks in Mexico. It does not establish accuracy "
                       "at the four UAE sites or validate their candidate oil masks.",
    }
    (output_dir / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["finetuned_test"], indent=2), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, default=Path("runs/unet_refined_sar/best.pth"))
    parser.add_argument("--output-dir", type=Path, default=Path("runs/unet_garcia_finetune"))
    parser.add_argument("--epochs", type=int, default=6)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--device-name", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--seed", type=int, default=42)
    run(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
