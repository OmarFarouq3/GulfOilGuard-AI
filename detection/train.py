"""Train on paired SAR PNGs and save the model with the best validation Dice.

Run explicitly from the repository root: python -m detection.train --help
"""

import argparse
import json
from pathlib import Path
import random
import time

import torch
from torch import nn
from torch.utils.data import DataLoader

from detection.dataset import OilSpillDataset
from detection.metrics import confusion_counts, metrics_from_counts
from detection.model import build_model


def segmentation_loss(logits, masks):
    """Equal BCE and soft Dice terms, to learn sparse oil regions and background."""
    bce = nn.functional.binary_cross_entropy_with_logits(logits, masks)
    probabilities = logits.sigmoid()
    axes = (1, 2, 3)
    intersection = (probabilities * masks).sum(dim=axes)
    dice = (2 * intersection + 1) / (probabilities.sum(dim=axes) + masks.sum(dim=axes) + 1)
    return 0.5 * bce + 0.5 * (1 - dice.mean())


@torch.inference_mode()
def validate(model, loader, device):
    model.eval()
    counts = torch.zeros(4, dtype=torch.int64, device=device)
    total_loss = 0.0
    for images, masks in loader:
        images, masks = images.to(device, non_blocking=True), masks.to(device, non_blocking=True)
        logits = model(images)
        total_loss += segmentation_loss(logits, masks).item() * images.shape[0]
        counts += confusion_counts(logits, masks)
    return {"loss": total_loss / len(loader.dataset), **metrics_from_counts(counts.cpu().tolist())}


def save_checkpoint(path, checkpoint):
    """Atomic replacement preserves the previous checkpoint if writing fails."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(checkpoint, temporary)
    temporary.replace(path)


def train(
    image_dir: Path, mask_dir: Path, output_dir: Path, epochs: int = 15, *,
    val_image_dir: Path, val_mask_dir: Path, batch_size: int = 8,
    learning_rate: float = 3e-4, image_size: int = 256, base_channels: int = 32,
    device: str = "auto", workers: int = 2, seed: int = 42, patience: int = 5,
    resume: Path | None = None, audit_path: Path | None = None,
) -> Path:
    """Return best.pth; epochs is the total target, including resumed epochs.

    Validation is never augmented or used for gradients. If supplied, the audit
    excludes training images identical to validation images. It cannot establish
    independence of source scenes without geographic/crop metadata.
    """
    if epochs < 1 or batch_size < 1 or learning_rate <= 0 or workers < 0 or patience < 1:
        raise ValueError("epochs, batch_size, learning_rate and patience must be positive; workers >= 0.")
    if Path(image_dir).resolve() == Path(val_image_dir).resolve():
        raise ValueError("Training and validation image directories must be different.")
    output_dir = Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()) and resume is None:
        raise ValueError("Output directory is not empty. Use a new directory or --resume its last.pth.")
    selected_device = "cuda" if torch.cuda.is_available() else "cpu"
    device = torch.device(selected_device if device == "auto" else device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA requested but this environment has no available CUDA GPU.")
    torch.set_num_threads(4)
    torch.manual_seed(seed)
    random.seed(seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.benchmark = True

    excluded = []
    if audit_path is not None:
        audit = json.loads(Path(audit_path).read_text(encoding="utf-8"))
        excluded = sorted({name for group in audit["exact_image_overlap"] for name in group["train"]})
    training = OilSpillDataset(image_dir, mask_dir, image_size=image_size, augment=True, exclude=excluded)
    validation = OilSpillDataset(val_image_dir, val_mask_dir, image_size=image_size)
    generator = torch.Generator().manual_seed(seed)
    options = {"batch_size": batch_size, "num_workers": workers,
               "pin_memory": device.type == "cuda", "persistent_workers": workers > 0}
    train_loader = DataLoader(training, shuffle=True, generator=generator, **options)
    val_loader = DataLoader(validation, shuffle=False, **options)
    model = build_model(base_channels=base_channels).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="max", factor=0.5, patience=2)
    config = {
        "image_dir": str(Path(image_dir).resolve()), "mask_dir": str(Path(mask_dir).resolve()),
        "val_image_dir": str(Path(val_image_dir).resolve()), "val_mask_dir": str(Path(val_mask_dir).resolve()),
        "epochs": epochs, "batch_size": batch_size, "learning_rate": learning_rate,
        "image_size": image_size, "base_channels": base_channels, "in_channels": 3, "out_channels": 1,
        "seed": seed, "patience": patience, "workers": workers, "device": str(device),
        "torch_version": str(torch.__version__), "train_pairs": len(training), "val_pairs": len(validation),
        "excluded_training_duplicates": excluded, "loss": "0.5 BCEWithLogits + 0.5 soft Dice",
        "threshold": 0.5, "normalization": "RGB float32 / 255", "mask_encoding": "grayscale > 127",
        "augmentation": "independent horizontal/vertical flips, p=0.5 each, training only",
        "metric_aggregation": "global pixel counts (micro)",
        "audit_path": str(Path(audit_path).resolve()) if audit_path else None,
    }
    history, first_epoch, best_dice, stale_epochs = [], 1, -1.0, 0
    if resume is not None:
        if Path(resume).resolve().parent != output_dir.resolve():
            raise ValueError("Resume checkpoint must belong to output_dir, alongside best.pth.")
        checkpoint = torch.load(resume, map_location="cpu", weights_only=True)
        for key in ("image_dir", "mask_dir", "val_image_dir", "val_mask_dir", "image_size",
                    "base_channels", "batch_size", "learning_rate", "seed",
                    "train_pairs", "val_pairs", "excluded_training_duplicates"):
            if checkpoint["config"][key] != config[key]:
                raise ValueError(f"Resume configuration mismatch: {key}")
        model.load_state_dict(checkpoint["model_state_dict"])
        optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
        scheduler.load_state_dict(checkpoint["scheduler_state_dict"])
        history = checkpoint["history"]
        first_epoch = checkpoint["epoch"] + 1
        if epochs < first_epoch:
            raise ValueError(f"epochs must exceed saved epoch {checkpoint['epoch']} to resume training.")
        best_dice, stale_epochs = checkpoint["best_dice"], checkpoint["stale_epochs"]
        torch.set_rng_state(checkpoint["torch_rng_state"])
        generator.set_state(checkpoint["loader_rng_state"])
        random.setstate(checkpoint["python_rng_state"])
        if device.type == "cuda" and checkpoint["cuda_rng_states"]:
            torch.cuda.set_rng_state_all(checkpoint["cuda_rng_states"])
        if not (output_dir / "best.pth").is_file():
            raise ValueError("Missing best.pth for this resumed run.")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    (output_dir / "split_manifest.json").write_text(json.dumps(
        {"train": training.files, "val": validation.files}, indent=2), encoding="utf-8")
    print(f"Device: {device}; training={len(training)}, validation={len(validation)}; "
          f"size={image_size}; batch={batch_size}", flush=True)
    if excluded:
        print(f"Excluded {len(excluded)} training images identical to validation images.", flush=True)
    for epoch in range(first_epoch, epochs + 1):
        started = time.perf_counter()
        model.train()
        total_loss = 0.0
        for step, (images, masks) in enumerate(train_loader, 1):
            images, masks = images.to(device, non_blocking=True), masks.to(device, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            loss = segmentation_loss(model(images), masks)
            if not torch.isfinite(loss).item():
                raise RuntimeError(f"Non-finite loss at epoch {epoch}, batch {step}.")
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0, error_if_nonfinite=True)
            optimizer.step()
            total_loss += loss.item() * images.shape[0]
            if step % 100 == 0 or step == len(train_loader):
                print(f"Epoch {epoch}/{epochs}, batch {step}/{len(train_loader)}, loss={loss.item():.4f}", flush=True)
        metrics = validate(model, val_loader, device)
        if not all(torch.isfinite(torch.tensor(value)).item() for value in metrics.values()):
            raise RuntimeError("Validation produced a non-finite metric.")
        improved = metrics["dice"] > best_dice
        best_dice = max(best_dice, metrics["dice"])
        stale_epochs = 0 if improved else stale_epochs + 1
        row = {"epoch": epoch, "train_loss": total_loss / len(training),
               "val_loss": metrics.pop("loss"), **metrics,
               "learning_rate": optimizer.param_groups[0]["lr"], "seconds": time.perf_counter() - started}
        history.append(row)
        scheduler.step(row["dice"])
        checkpoint = {"format_version": 1, "model_state_dict": model.state_dict(), "config": config,
                      "epoch": epoch, "validation": row, "best_dice": best_dice}
        if improved:
            save_checkpoint(output_dir / "best.pth", checkpoint)
        checkpoint.update({"optimizer_state_dict": optimizer.state_dict(),
                           "scheduler_state_dict": scheduler.state_dict(), "history": history,
                           "stale_epochs": stale_epochs, "torch_rng_state": torch.get_rng_state(),
                           "loader_rng_state": generator.get_state(), "python_rng_state": random.getstate(),
                           "cuda_rng_states": torch.cuda.get_rng_state_all() if device.type == "cuda" else []})
        save_checkpoint(output_dir / "last.pth", checkpoint)
        (output_dir / "history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
        print(f"Epoch {epoch}: train_loss={row['train_loss']:.4f}, val_loss={row['val_loss']:.4f}, "
              f"Dice={row['dice']:.4f}, IoU={row['iou']:.4f}, precision={row['precision']:.4f}, "
              f"recall={row['recall']:.4f}, {row['seconds']:.1f}s; best={best_dice:.4f}", flush=True)
        if stale_epochs >= patience:
            print(f"Early stopping after {patience} epochs without improved validation Dice.", flush=True)
            break
    print(f"Best checkpoint: {output_dir / 'best.pth'}", flush=True)
    return output_dir / "best.pth"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-dir", type=Path, default=Path("detection/images/train"))
    parser.add_argument("--mask-dir", type=Path, default=Path("detection/masks/train"))
    parser.add_argument("--val-image-dir", type=Path, default=Path("detection/images/val"))
    parser.add_argument("--val-mask-dir", type=Path, default=Path("detection/masks/val"))
    parser.add_argument("--output-dir", type=Path, default=Path("runs/unet_refined_sar"))
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--image-size", type=int, default=256)
    parser.add_argument("--base-channels", type=int, default=32)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--patience", type=int, default=5)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--audit-path", type=Path)
    train(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
