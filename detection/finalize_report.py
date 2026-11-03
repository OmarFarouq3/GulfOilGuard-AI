"""Add provenance to the evaluation outputs (no model rerun needed).

Run after `python -m detection.report`:
  python -m detection.finalize_report --checkpoint runs/unet_refined_sar/best.pth

- per_image_metrics.csv: adds a `split` column (train/ and val/ reuse filenames).
- summary.json: adds checkpoint_sha256, checkpoint_file, split, created.
- outputs/detection/metrics.json: flat dashboard file with the same provenance keys.
"""
import argparse
import csv
import hashlib
import json
from datetime import date
from pathlib import Path


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", type=Path, required=True)
    ap.add_argument("--split", default="val")
    ap.add_argument("--report-dir", type=Path, default=Path("outputs/report"))
    ap.add_argument("--metrics-json", type=Path, default=Path("outputs/detection/metrics.json"))
    ap.add_argument("--model", default="U-Net (unet_refined_sar)")
    a = ap.parse_args()

    meta = {"checkpoint_sha256": sha256(a.checkpoint), "checkpoint_file": a.checkpoint.name,
            "split": a.split, "created": date.today().isoformat()}

    # 1) per_image_metrics.csv: add split column (second position)
    csv_path = a.report_dir / "per_image_metrics.csv"
    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["split"] = a.split
    fields = ["file", "split"] + [k for k in rows[0] if k not in ("file", "split")]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    # 2) summary.json: provenance first, then the existing content
    sum_path = a.report_dir / "summary.json"
    s = json.loads(sum_path.read_text())
    s = {**meta, **{k: v for k, v in s.items() if k not in meta}}
    sum_path.write_text(json.dumps(s, indent=2))

    # 3) flat dashboard metrics.json (overall validation scores, not per image)
    a.metrics_json.parent.mkdir(parents=True, exist_ok=True)
    flat = {"model": a.model, **meta, "n_images": s["n_images"],
            "threshold": s["threshold"], **s["micro"]}
    a.metrics_json.write_text(json.dumps(flat, indent=2))

    print(f"checkpoint_sha256: {meta['checkpoint_sha256']}")
    print(f"Updated {csv_path}, {sum_path}, {a.metrics_json}")


if __name__ == "__main__":
    main()
