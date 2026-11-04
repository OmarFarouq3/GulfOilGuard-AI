"""Per-image metrics, threshold sweep and ranked galleries for a checkpoint.

Run from repo root:
  python -m detection.report --checkpoint runs/unet_refined_sar/best.pth
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw
from torch.utils.data import DataLoader

from detection.dataset import OilSpillDataset
from detection.evaluate import load_model
from detection.metrics import metrics_from_counts


def counts(prob, mask, t):
    pred = prob >= t
    return [int((pred & mask).sum()), int((pred & ~mask).sum()),
            int((~pred & mask).sum()), int((~pred & ~mask).sum())]


@torch.inference_mode()
def collect(checkpoint, image_dir, mask_dir, device, batch_size=8, limit=None):
    model, ckpt = load_model(checkpoint, device)
    cfg = ckpt["config"]
    ds = OilSpillDataset(image_dir, mask_dir, image_size=cfg["image_size"])
    if limit:
        ds.files = ds.files[:limit]  # quick test on the first N pairs only
    probs, masks = [], []
    loader = DataLoader(ds, batch_size=batch_size, shuffle=False)
    for n, (x, y) in enumerate(loader, 1):
        probs.append(model(x.to(device)).sigmoid().cpu()[:, 0])
        masks.append(y[:, 0] >= 0.5)
        if n % 10 == 0 or n == len(loader):
            print(f"Processed {min(n * batch_size, len(ds))}/{len(ds)} images", flush=True)
    return ds, torch.cat(probs), torch.cat(masks), cfg["threshold"]


def error_overlay(rgb, pred, ref):
    out = rgb.copy()
    for color, region in (((0, 255, 0), pred & ref),     # green = true positive
                          ((255, 0, 0), pred & ~ref),    # red   = false positive
                          ((0, 128, 255), ~pred & ref)): # blue  = false negative
        out[region] = (0.4 * out[region] + 0.6 * np.array(color)).astype(np.uint8)
    return out


def gallery(ds, probs, masks, indices, path, threshold, title):
    tile = 256
    canvas = Image.new("RGB", (4 * tile, len(indices) * (tile + 20) + 30), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((6, 8), f"{title} | cols: input, reference, prediction, "
                      "errors (green TP, red FP, blue FN)", fill="black")
    for row, i in enumerate(indices):
        image, _ = ds[i]
        rgb = (image.permute(1, 2, 0).numpy() * 255).round().astype(np.uint8)
        pred, ref = (probs[i] >= threshold).numpy(), masks[i].numpy()
        panels = [rgb, ref.astype(np.uint8) * 255, pred.astype(np.uint8) * 255,
                  error_overlay(rgb, pred, ref)]
        y = 30 + row * (tile + 20)
        draw.text((6, y), ds.files[i], fill="black")
        for col, p in enumerate(panels):
            canvas.paste(Image.fromarray(p).convert("RGB").resize((tile, tile)),
                         (col * tile, y + 16))
    canvas.save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", type=Path, required=True)
    ap.add_argument("--image-dir", type=Path, default=Path("detection/images/val"))
    ap.add_argument("--mask-dir", type=Path, default=Path("detection/masks/val"))
    ap.add_argument("--output-dir", type=Path, default=Path("outputs/report"))
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--limit", type=int, default=None,
                    help="Only use the first N pairs (for a quick test).")
    a = ap.parse_args()
    torch.set_num_threads(max(1, (os.cpu_count() or 4) - 1))
    a.output_dir.mkdir(parents=True, exist_ok=True)

    ds, probs, masks, thr = collect(a.checkpoint, a.image_dir, a.mask_dir, a.device, limit=a.limit)
    split = a.image_dir.name.lower() if a.image_dir.name.lower() in {"train", "val", "test"} else None

    # 1) Per-image CSV
    rows = []
    for i, name in enumerate(ds.files):
        c = counts(probs[i], masks[i], thr)
        rows.append({"file": name, **({"split": split} if split else {}),
                     "ref_oil_pixels": c[0] + c[2], **metrics_from_counts(c)})
    with open(a.output_dir / "per_image_metrics.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)

    # 2) Summary: micro (global) vs macro (per-image mean) on images that contain oil
    has_oil = [r for r in rows if r["ref_oil_pixels"] > 0]
    digest = hashlib.sha256(a.checkpoint.read_bytes()).hexdigest()
    summary = {"threshold": thr, "n_images": len(rows), "checkpoint_sha256": digest,
               **({"split": split} if split else {}), "n_with_oil": len(has_oil),
               "n_empty_reference": len(rows) - len(has_oil),
               "micro": metrics_from_counts(counts(probs, masks, thr)),
               "macro_images_with_oil": {k: float(np.mean([r[k] for r in has_oil]))
                                         for k in ("dice", "iou", "precision", "recall")}}
    # 3) Threshold sweep
    summary["threshold_sweep"] = {f"{t:.2f}": metrics_from_counts(counts(probs, masks, t))
                                  for t in np.arange(0.1, 0.91, 0.1)}
    (a.output_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    # 4) Worst / median / best galleries (only images with reference oil)
    order = sorted((i for i, r in enumerate(rows) if r["ref_oil_pixels"] > 0),
                   key=lambda i: rows[i]["dice"])
    mid = len(order) // 2
    for title, idx in (("worst", order[:4]), ("median", order[mid - 2:mid + 2]),
                       ("best", order[-4:])):
        gallery(ds, probs, masks, idx, a.output_dir / f"gallery_{title}.png", thr, title)
    print(json.dumps(summary["micro"], indent=2))


if __name__ == "__main__":
    main()
