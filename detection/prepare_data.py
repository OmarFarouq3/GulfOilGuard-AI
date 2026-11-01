"""Extract the supplied Refined Deep-SAR archives and audit every image/mask pair."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

import numpy as np
from PIL import Image


def prepare_data(images_zip: Path, masks_zip: Path, data_dir: Path, report_path: Path) -> dict:
    data_dir = data_dir.resolve()
    archive_hashes = {}
    for kind, archive_path in (("images", images_zip), ("masks", masks_zip)):
        digest = hashlib.sha256()
        with archive_path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        archive_hashes[kind] = digest.hexdigest()
        with ZipFile(archive_path) as archive:
            for member in archive.infolist():
                parts = PurePosixPath(member.filename).parts
                # Only explicitly permitted dataset paths; skip macOS metadata.
                if (len(parts) != 3 or parts[0] != kind or parts[1] not in ("train", "val")
                        or parts[2].startswith(".") or not parts[2].endswith(".png")):
                    continue
                target = data_dir.joinpath(*parts)
                if not target.resolve().is_relative_to(data_dir):
                    raise ValueError(f"Unsafe archive path: {member.filename}")
                content = archive.read(member)  # Also verifies the ZIP member CRC.
                if target.exists() and target.read_bytes() != content:
                    raise ValueError(f"Refusing to overwrite different data: {target}")
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
        print(f"Extracted {kind}.", flush=True)

    report = {"archive_sha256": archive_hashes, "mask_rule": "PIL grayscale > 127 = oil",
              "splits": {}, "scene_disjointness": "Unverified: source scene/crop metadata not provided."}
    fingerprints = {}
    for split in ("train", "val"):
        images = {p.name: p for p in (data_dir / "images" / split).glob("*.png")}
        masks = {p.name: p for p in (data_dir / "masks" / split).glob("*.png")}
        if not images or images.keys() != masks.keys():
            raise ValueError(f"Missing or unmatched files in {split}: images={len(images)}, masks={len(masks)}")
        sizes, modes = Counter(), Counter()
        histogram = np.zeros(256, dtype=np.int64)
        hashes = defaultdict(list)
        empty = oil_pixels = total_pixels = soft_masks = colored_masks = 0
        for index, name in enumerate(sorted(images), 1):
            with Image.open(images[name]) as image, Image.open(masks[name]) as mask:
                image.load()
                mask.load()
                if image.size != mask.size:
                    raise ValueError(f"Size mismatch: {split}/{name}")
                sizes[str(image.size)] += 1
                modes[mask.mode] += 1
                rgb = np.asarray(image.convert("RGB"))
                digest = hashlib.sha256(str(image.size).encode() + rgb.tobytes()).hexdigest()
                hashes[digest].append(name)
                mask_rgb = np.asarray(mask.convert("RGB"))
                colored_masks += int(np.any(mask_rgb[..., 0] != mask_rgb[..., 1])
                                     or np.any(mask_rgb[..., 1] != mask_rgb[..., 2]))
                labels = np.asarray(mask.convert("L"))
            histogram += np.bincount(labels.ravel(), minlength=256)
            positive = int((labels > 127).sum())
            oil_pixels += positive
            total_pixels += labels.size
            empty += int(positive == 0)
            soft_masks += int(np.any((labels != 0) & (labels != 255)))
            if index % 1000 == 0:
                print(f"Audited {split}: {index}/{len(images)}", flush=True)
        fingerprints[split] = hashes
        report["splits"][split] = {
            "pairs": len(images), "sizes": dict(sizes), "mask_modes": dict(modes),
            "empty_masks": empty, "masks_with_intermediate_values": soft_masks,
            "masks_with_unequal_rgb_channels": colored_masks,
            "oil_pixels": oil_pixels, "total_pixels": total_pixels,
            "oil_fraction": oil_pixels / total_pixels,
            "grayscale_histogram": histogram.tolist(),
            "duplicate_image_groups": [v for v in hashes.values() if len(v) > 1],
        }
    overlap = fingerprints["train"].keys() & fingerprints["val"].keys()
    report["exact_image_overlap"] = [
        {"train": fingerprints["train"][h], "val": fingerprints["val"][h]} for h in sorted(overlap)
    ]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Audit saved: {report_path}", flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images-zip", type=Path, required=True)
    parser.add_argument("--masks-zip", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=Path("detection"))
    parser.add_argument("--report", type=Path, default=Path("outputs/data_audit.json"))
    args = parser.parse_args()
    prepare_data(args.images_zip, args.masks_zip, args.data_dir, args.report)


if __name__ == "__main__":
    main()
