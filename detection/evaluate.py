"""Evaluate a trained checkpoint or export a predicted binary mask."""

import argparse
import json
from pathlib import Path
from typing import TypedDict

import numpy as np
from PIL import Image, ImageDraw
import torch
from torch.utils.data import DataLoader

from detection.dataset import OilSpillDataset
from detection.metrics import confusion_counts, metrics_from_counts
from detection.model import build_model
from shared.schemas import DetectionOutput


class SegmentationMetrics(TypedDict):
    dice: float
    iou: float
    precision: float
    recall: float


def load_model(checkpoint_path: Path, device="cpu"):
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    config = checkpoint["config"]
    model = build_model(config["in_channels"], config["out_channels"],
                        base_channels=config["base_channels"])
    model.load_state_dict(checkpoint["model_state_dict"])
    return model.to(device).eval(), checkpoint


@torch.inference_mode()
def evaluate(checkpoint_path: Path, image_dir: Path, mask_dir: Path, *,
             device="auto", batch_size=8, output_dir=None) -> SegmentationMetrics:
    """Evaluate all pairs using global pixel counts and the saved preprocessing."""
    device = torch.device(("cuda" if torch.cuda.is_available() else "cpu") if device == "auto" else device)
    model, checkpoint = load_model(checkpoint_path, device)
    config = checkpoint["config"]
    dataset = OilSpillDataset(image_dir, mask_dir, image_size=config["image_size"])
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False)
    counts = torch.zeros(4, dtype=torch.int64, device=device)
    for images, masks in loader:
        counts += confusion_counts(model(images.to(device)), masks.to(device), config["threshold"])
    counts = counts.cpu().tolist()
    metrics = metrics_from_counts(counts)
    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        report = {"checkpoint": str(Path(checkpoint_path).resolve()), "epoch": checkpoint["epoch"],
                  "pairs": len(dataset), "threshold": config["threshold"], "image_size": config["image_size"],
                  "aggregation": "global pixel counts (micro)", "metrics": metrics,
                  "counts": dict(zip(("true_positive", "false_positive", "false_negative", "true_negative"), counts)),
                  "limitations": "Provider validation split used for model selection; not an independent test set. "
                                  "Source-scene independence and Gulf-region generalization are unverified."}
        (output_dir / "metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        make_gallery(model, dataset, device, output_dir / "examples.png", config["threshold"])
    return metrics


@torch.inference_mode()
def make_gallery(model, dataset, device, path, threshold=0.5):
    """Evenly spaced samples in filename order, selected without looking at scores."""
    indices = np.linspace(0, len(dataset) - 1, min(6, len(dataset)), dtype=int).tolist()
    tile, row_height = 256, 292
    canvas = Image.new("RGB", (4 * tile, len(indices) * row_height + 30), "white")
    draw = ImageDraw.Draw(canvas)
    for column, title in enumerate(("SAR input", "Reference mask", "Predicted mask", "Red: predicted oil")):
        draw.text((column * tile + 6, 8), title, fill="black")
    for row, index in enumerate(indices):
        image, mask = dataset[index]
        predicted = model(image.unsqueeze(0).to(device)).sigmoid()[0, 0].cpu().numpy() >= threshold
        rgb = (image.permute(1, 2, 0).numpy() * 255).round().astype(np.uint8)
        overlay = rgb.copy()
        overlay[predicted] = (0.55 * rgb[predicted] + 0.45 * np.array([255, 0, 0])).astype(np.uint8)
        panels = (Image.fromarray(rgb), Image.fromarray((mask[0].numpy() * 255).astype(np.uint8)),
                  Image.fromarray(predicted.astype(np.uint8) * 255), Image.fromarray(overlay))
        y = 30 + row * row_height
        draw.text((6, y + 4), dataset.files[index], fill="black")
        for column, panel in enumerate(panels):
            canvas.paste(panel.convert("RGB").resize((tile, tile), Image.Resampling.NEAREST), (column * tile, y + 24))
    canvas.save(path)


def predict(checkpoint_path: Path, image_path: Path, output_dir: Path, *, device="cpu") -> DetectionOutput:
    """Export a mask at original image size; geographic coordinates stay absent."""
    device = torch.device(("cuda" if torch.cuda.is_available() else "cpu") if device == "auto" else device)
    model, checkpoint = load_model(checkpoint_path, device)
    config = checkpoint["config"]
    image_path, output_dir = Path(image_path), Path(output_dir)
    with Image.open(image_path) as source:
        original_size = source.size
        image = source.convert("RGB").resize((config["image_size"],) * 2, Image.Resampling.BILINEAR)
        tensor = torch.from_numpy(np.array(image, dtype=np.float32)).permute(2, 0, 1).unsqueeze(0) / 255
    with torch.inference_mode():
        probabilities = model(tensor.to(device)).sigmoid()
        probabilities = torch.nn.functional.interpolate(probabilities, size=original_size[::-1],
                                                         mode="bilinear", align_corners=False)
        mask = (probabilities[0, 0].cpu().numpy() >= config["threshold"]).astype(np.uint8) * 255
    output_dir.mkdir(parents=True, exist_ok=True)
    mask_path = output_dir / f"{image_path.stem}_mask.png"
    Image.fromarray(mask).save(mask_path)
    return DetectionOutput(image_id=image_path.stem, mask_path=mask_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--image-dir", type=Path, default=Path("detection/images/val"))
    parser.add_argument("--mask-dir", type=Path, default=Path("detection/masks/val"))
    parser.add_argument("--image", type=Path, help="Predict one image instead of evaluating a labelled split.")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/unet_validation"))
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    args = parser.parse_args()
    torch.set_num_threads(4)
    if args.image:
        print(predict(args.checkpoint, args.image, args.output_dir, device=args.device))
    else:
        print(json.dumps(evaluate(args.checkpoint, args.image_dir, args.mask_dir,
                                  device=args.device, output_dir=args.output_dir), indent=2))


if __name__ == "__main__":
    main()
