"""Independent check of the numbers the dashboard shows, recomputed from outputs/ with plain json.

    python tests/verify_metrics.py [outputs]

The "expected" side never imports dashboard code: it reads the files with json / csv (and numpy + PIL
for the masks) and applies the formulas written out below. The "dashboard" side calls the
dashboard's own loaders (services.routing_loader, services.detection_loader) on the same files, and
every pair is printed next to each other; a difference beyond the tolerance is flagged MISMATCH and
makes the exit code 1.

Per site (outputs/sites/S1..S4) and its nearest-target baseline:
  completion time  max finish_hours over the plan's routes (sailing out + cleanup + back to port)
  sailing time     max estimated_travel_hours (sailing only, the trip back included)
  served/unserved  targets minus summary.json unserved_target_ids / that list
  oil recovered    sum of the routes' oil_collected_m3
  comparison.json  optimized_/baseline_ response_hours, longest_route_hours, oil_recovered_m3,
                   targets_covered, distance_km recomputed from each plan's own routes
  targets          cut at one forecast hour that is in the site's drift file, from afloat oil only
Detection: Dice / IoU / precision / recall from outputs/detection/metrics.json, and recomputed from
one real image / labelled mask / predicted mask triple when the labelled mask is on this machine.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "outputs"
SITES = ("S1", "S2", "S3", "S4")
TOL = 0.01
problems: list[str] = []


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def check(label: str, expected, shown, tol: float = TOL) -> None:
    if isinstance(expected, (int, float)) and isinstance(shown, (int, float)):
        same = math.isclose(expected, shown, abs_tol=tol)
    else:
        same = expected == shown
    flag = "ok" if same else "MISMATCH"
    if not same:
        problems.append(f"{label}: expected {expected!r}, dashboard {shown!r}")
    print(f"  {label:<46} expected {fmt(expected):>12}   dashboard {fmt(shown):>12}   {flag}")


def fmt(value) -> str:
    return f"{value:.3f}" if isinstance(value, float) else str(value)


def haversine_km(lon1, lat1, lon2, lat2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


# --- Recomputed from the files (no dashboard code) ---------------------------------------------------------


def plan_numbers(routing_dir: Path) -> dict:
    routes = [f["properties"] for f in read(routing_dir / "routes.geojson")["features"]]
    targets = [f["properties"]["target_id"] for f in read(routing_dir / "targets.geojson")["features"]]
    summary = read(routing_dir / "summary.json")
    unserved = list(summary.get("unserved_target_ids") or [])
    return {
        "completion_hours": max(r["finish_hours"] for r in routes),
        "sailing_hours": max(r["estimated_travel_hours"] for r in routes),
        "served": len(set(targets) - set(unserved)),
        "unserved": len(unserved),
        "unserved_ids": unserved,
        "oil_recovered_m3": sum(r.get("oil_collected_m3") or 0.0 for r in routes),
        "distance_km": sum(r["estimated_distance_km"] for r in routes),
        "targets_covered": len({t for r in routes for t in r["assigned_target_ids"]}),
        "cleanup_hours": {r["vessel_id"]: r.get("cleanup_hours") for r in routes},
        "routes": routes,
    }


def drift_steps(drift_file: Path) -> dict[float, dict[str, list]]:
    """{hours: {status: [[lon, lat], ...]}} of the particle layers, and the oil volume per status."""
    steps: dict[float, dict] = {}
    for f in read(drift_file)["features"]:
        if f["geometry"]["type"] != "MultiPoint":
            continue
        p = f["properties"]
        step = steps.setdefault(float(p["hours"]), {"points": {}, "oil": {}})
        step["points"].setdefault(p["status"], []).extend(f["geometry"]["coordinates"])
        step["oil"][p["status"]] = step["oil"].get(p["status"], 0.0) + float(p.get("oil_volume_m3") or 0.0)
    return steps


def nearest(points: list, lon: float, lat: float) -> float:
    return min((haversine_km(lon, lat, x, y) for x, y in points), default=float("inf"))


def target_origin(site: str) -> None:
    """Targets come from one forecast hour in the site's drift file, and from afloat particles only."""
    d = OUTPUTS / "sites" / site
    comparison, summary = read(d / "routing" / "comparison.json"), read(d / "routing" / "summary.json")
    steps = drift_steps(d / "drift" / "drift.geojson")
    dispatch = float(comparison["drift"]["dispatch_hours"])
    in_file = dispatch in steps
    print(f"  targets cut at dispatch +{dispatch:g} h: hour present in drift.geojson: {in_file}")
    if not in_file:
        problems.append(f"{site}: dispatch hour {dispatch} not in drift.geojson")
        return
    at = steps[dispatch]
    afloat_oil, stranded_oil = at["oil"].get("active", 0.0), sum(v for k, v in at["oil"].items() if k != "active")
    targeted = comparison["drift"]["targeted_oil_at_dispatch_m3"]
    print(f"  oil at +{dispatch:g} h in drift.geojson: afloat {afloat_oil:.2f} m3, not afloat {stranded_oil:.2f} m3; "
          f"comparison.json targeted {targeted:.2f} m3 (afloat {comparison['drift']['oil_afloat_at_dispatch_m3']:.2f})")
    if not math.isclose(targeted, afloat_oil, abs_tol=0.05) or targeted > afloat_oil + 0.05:
        problems.append(f"{site}: targeted oil {targeted} != oil afloat at dispatch {afloat_oil}")
    layer = summary.get("source_hours")
    sources = {f["properties"].get("source_hours") for f in read(d / "routing" / "targets.geojson")["features"]}
    print(f"  display layer source_hours {layer} (targets: {sorted(sources)}): in drift.geojson: {float(layer) in steps}")
    if layer is None or float(layer) not in steps or sources != {layer}:
        problems.append(f"{site}: targets' source_hours {sources} / summary {layer} not one hour of the drift file")
    worst = []
    for f in read(d / "routing" / "targets.geojson")["features"]:
        p, (lon, lat) = f["properties"], f["geometry"]["coordinates"]
        hour = min(steps, key=lambda h: abs(h - float(p.get("position_hours", dispatch))))
        active = nearest(steps[hour]["points"].get("active", []), lon, lat)
        gone = min((nearest(v, lon, lat) for k, v in steps[hour]["points"].items() if k != "active"), default=float("inf"))
        worst.append((p["target_id"], hour, active, gone))
        if not active < gone:
            problems.append(f"{site} {p['target_id']}: nearest particle at +{hour:g} h is not afloat")
    print("  each target vs particles at its position hour (nearest afloat km / nearest not-afloat km): "
          + ", ".join(f"{t} +{h:g}h {a:.2f}/{'-' if g == float('inf') else f'{g:.1f}'}" for t, h, a, g in worst))


def per_image(csv_path: Path, name: str) -> dict | None:
    if not csv_path.is_file():
        return None
    return next((r for r in csv.DictReader(csv_path.open(encoding="utf-8")) if r["file"] == name), None)


def mask_scores(predicted_png: Path, truth_png: Path) -> dict:
    import numpy as np
    from PIL import Image
    with Image.open(predicted_png) as p, Image.open(truth_png) as t:
        pred, truth = np.asarray(p.convert("L")) >= 128, np.asarray(t.convert("L")) >= 128
    tp, fp, fn = int((pred & truth).sum()), int((pred & ~truth).sum()), int((~pred & truth).sum())
    return {"dice": 2 * tp / (2 * tp + fp + fn), "iou": tp / (tp + fp + fn),
            "precision": tp / (tp + fp), "recall": tp / (tp + fn), "ref_oil_pixels": tp + fn}


# --- The dashboard's side -------------------------------------------------------------------------------


def dashboard():
    """The dashboard's loaders, pointed at the same outputs folder (only used for the right-hand column)."""
    import os
    os.environ["GULFOILGUARD_OUTPUTS"] = str(OUTPUTS)
    sys.path.insert(0, str(ROOT / "dashboard"))
    import logging
    logging.getLogger("streamlit").setLevel(logging.ERROR)
    import config
    from services.detection_loader import load_detection
    from services.routing_loader import load_comparison, load_routing
    return config, load_routing, load_comparison, load_detection


def main() -> int:
    config, load_routing, load_comparison, load_detection = dashboard()
    for site in SITES:
        d = OUTPUTS / "sites" / site
        if not (d / "routing" / "routes.geojson").is_file():
            print(f"\n{site}: no routing files, skipped")
            continue
        files = config.site_files(site)
        print(f"\n=== {site} ({read(d / 'routing' / 'summary.json').get('scenario_id')})")
        expected = {"optimized": plan_numbers(d / "routing"), "baseline": plan_numbers(d / "routing" / "baseline")}
        shown = {"optimized": load_routing(files["routing"]), "baseline": load_routing(files["baseline"])}
        for plan in ("optimized", "baseline"):
            e, s = expected[plan], shown[plan]
            print(f" {plan} plan")
            check("completion time, max finish_hours (h)", e["completion_hours"], s.completion_hours)
            check("headline response time (h)", e["completion_hours"], s.response_time_hours)
            check("sailing time, max estimated_travel_hours (h)", e["sailing_hours"], s.sailing_time_hours)
            check("patches served", e["served"], len({t.target_id for t in s.targets} - set(s.unserved_target_ids)))
            check("patches unserved", e["unserved"], len(s.unserved_target_ids))
            check("unserved ids", e["unserved_ids"], list(s.unserved_target_ids))
            check("oil recovered (m3)", e["oil_recovered_m3"], s.oil_collected_m3)
            check("distance sailed (km)", e["distance_km"], s.total_distance_km)
        metrics = read(d / "routing" / "comparison.json")["metrics"]
        shown_metrics = (load_comparison(files["routing"]["comparison"])[0] or {}).get("metrics", {})
        print(" comparison.json vs each plan's own routes")
        for plan in ("optimized", "baseline"):
            e = expected[plan]
            for key, value in (("response_hours", e["completion_hours"]), ("longest_route_hours", e["sailing_hours"]),
                               ("oil_recovered_m3", e["oil_recovered_m3"]), ("targets_covered", float(e["targets_covered"])),
                               ("distance_km", e["distance_km"])):
                check(f"{plan}_{key}", value, metrics[f"{plan}_{key}"])
                check(f"{plan}_{key} as the dashboard reads it", metrics[f"{plan}_{key}"], shown_metrics.get(f"{plan}_{key}"))
        target_origin(site)
        if site == "S3":
            r = expected["optimized"]["routes"]
            for route in r:
                print(f"  S3 gap: {route['vessel_id']} sails {route['estimated_travel_hours']:.2f} h "
                      f"({route['estimated_distance_km']:.1f} km at {route.get('speed_m_per_s')} m/s, out and back) and "
                      f"skims {route['oil_collected_m3']:.1f} m3 for {route['cleanup_hours']:.2f} h at 30 m3/h "
                      f"(optimization/config.py) = finish {route['finish_hours']:.2f} h")

    print("\n=== Detection (outputs/detection/metrics.json)")
    raw = read(OUTPUTS / "detection" / "metrics.json")
    detection = load_detection()
    for key in ("dice", "iou", "precision", "recall"):
        check(f"{key} (split {raw.get('split')}, {raw.get('n_images')} images)", raw[key],
              (detection.metrics or {}).get(key) if detection else None, tol=1e-6)
    dice = raw["dice"]
    check("IoU = Dice / (2 - Dice) for the pooled counts", dice / (2 - dice), raw["iou"], tol=1e-6)
    truth = ROOT / "detection" / "masks" / "val" / "palsar_0.png"
    # The app's own runs are named <stem>-<hash of the relative path>: palsar_0 exists in train/ and val/, so the
    # mask is chosen by its run manifest (the image it was made from), never by the name alone.
    predicted = [run.with_name(run.name.replace("_run.json", "_mask.png"))
                 for run in sorted((OUTPUTS / "detection").glob("palsar_0-*_run.json"))
                 if Path(read(run)["fingerprint"]["image"].replace("\\", "/")).parts[-2:] == ("val", "palsar_0.png")]
    predicted = [p for p in predicted if p.is_file()] or sorted((OUTPUTS / "detection").glob("palsar_0_mask.png"))
    recorded = per_image(OUTPUTS / "report" / "per_image_metrics.csv", "palsar_0.png")
    if truth.is_file() and predicted and recorded:
        scores = mask_scores(predicted[0], truth)
        print(f"\n=== Triple: assets/images/val/palsar_0.png, {truth.relative_to(ROOT).as_posix()}, "
              f"{predicted[0].relative_to(OUTPUTS).as_posix()} vs report/per_image_metrics.csv")
        check("labelled oil pixels", int(recorded["ref_oil_pixels"]), scores["ref_oil_pixels"], tol=0)
        for key in ("dice", "iou", "precision", "recall"):
            check(f"palsar_0 {key}", float(recorded[key]), scores[key])
    else:
        print("\nTriple check skipped: needs detection/masks/val/palsar_0.png (masks.zip), a palsar_0 mask in "
              "outputs/detection and outputs/report/per_image_metrics.csv.")

    print("\n" + ("All values match." if not problems else f"{len(problems)} MISMATCH(ES):\n  " + "\n  ".join(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
