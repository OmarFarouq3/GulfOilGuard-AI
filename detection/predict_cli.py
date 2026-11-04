"""Predict one image and write the dashboard's detection files.

Usage (from the repository root):
    python -m detection.predict_cli --checkpoint runs/unet_refined_sar/best.pth \
        --image assets/images/scene.png --out outputs/detection --image-id scene

Writes ``<image-id>_image.png`` (the RGB input the model saw), ``<image-id>_mask.png``
(white = predicted oil) and ``<image-id>_overlay.png`` into ``--out``, using
``evaluate.predict``. Each file is written to a temporary file in the same folder and then
moved into place, so a reader never sees a half-written PNG. On success the last stdout
line is ``RESULT_PREFIX {json}``; exit codes are in shared/detection_cli.py. The dashboard
calls this in a subprocess so that Streamlit never imports torch; torch is imported only
inside ``main``, so the parser can be built (and tested) without it.
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from shared.detection_cli import EXIT_FAILED, EXIT_NO_TORCH, KINDS, RESULT_PREFIX, atomic_replace

# Same amber tint as dashboard/services/imaging.py (oil is amber everywhere in the dashboard).
OVERLAY_RGB = (245, 158, 11)
OVERLAY_ALPHA = 0.45


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m detection.predict_cli", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="cpu")
    return parser


def save_png_atomic(pixels: np.ndarray, target: Path) -> None:
    """Write a PNG next to ``target`` under a temporary name, then move it into place."""
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.stem}.", suffix=".tmp")
    os.close(fd)
    try:
        Image.fromarray(pixels).save(temporary, format="PNG")
        atomic_replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def write_outputs(image_path: Path, mask_png: Path, out: Path, image_id: str) -> dict:
    """Save input, mask and overlay as <image_id>_{image,mask,overlay}.png; return their paths."""
    with Image.open(image_path) as source:
        rgb = np.asarray(source.convert("RGB"), dtype=np.float32)  # as predict() feeds the model
    with Image.open(mask_png) as mask_image:
        mask = np.asarray(mask_image.convert("L"))
    oil = mask > 127
    overlay = rgb.copy()
    overlay[oil] = (1 - OVERLAY_ALPHA) * overlay[oil] + OVERLAY_ALPHA * np.array(OVERLAY_RGB, dtype=np.float32)
    files = {kind: out / f"{image_id}_{kind}.png" for kind in KINDS}
    save_png_atomic(rgb.astype(np.uint8), files["image"])
    save_png_atomic(mask, files["mask"])
    save_png_atomic(overlay.clip(0, 255).astype(np.uint8), files["overlay"])
    return {"files": {k: str(v) for k, v in files.items()}, "oil_fraction": float(oil.mean())}


def main() -> int:
    args = build_parser().parse_args()

    try:
        import torch

        from detection.evaluate import predict
    except ImportError as exc:
        print(f"PyTorch is not available in this interpreter ({sys.executable}): {exc}", file=sys.stderr)
        return EXIT_NO_TORCH

    try:
        torch.set_num_threads(4)
        args.out.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=args.out) as scratch:
            output = predict(args.checkpoint, args.image, Path(scratch), device=args.device)
            result = write_outputs(args.image, Path(output.mask_path), args.out, args.image_id)
        config = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
        result.update(image_id=args.image_id, threshold=config["config"]["threshold"],
                      image_size=config["config"]["image_size"], epoch=config.get("epoch"))
    except Exception as exc:  # report any failure as one line; the traceback goes to stderr
        import traceback

        traceback.print_exc()
        print(f"Prediction failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_FAILED
    print(RESULT_PREFIX + json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
