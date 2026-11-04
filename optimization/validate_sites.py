"""Validate the four demo sites in one go, and check that each has its own drift run (Nihal).

Runs validate_cleanup on every site folder, then compares the sites with each other:
a site whose particles move exactly like another site's, only shifted, is a translated
copy of that run, not its own OpenDrift forecast.

Layout (drift/MAQQAVI_PROGRESS.md, day 3):

  outputs/sites/S1 ... S4/
    drift/      drift.geojson, meta.json
    routing/    routes.geojson, targets.geojson, summary.json, comparison.json, baseline/

Run from the repository root:
    python -m optimization.validate_sites
    python -m optimization.validate_sites --sites-dir outputs/sites --fleet outputs/fleet/gulf_standard.json --write

With --write, each site gets validation.txt and validation.json, and the sites folder gets
sites_summary.md (the table for the demo summary) and sites_summary.json.
"""

import argparse
import contextlib
import io
import json
from math import cos, hypot, radians
from pathlib import Path
from statistics import median

from optimization.config import REPO_ROOT
from optimization.validate_cleanup import _km, _point, parse_point, print_report, validate, write_json

# The four demo locations (coordinates from Joud, agreed with the team; drift/MAQQAVI_PROGRESS.md).
SITES = {
    "S1": ("25.85,55.65", "off Ras Al Khaimah"),
    "S2": ("25.70,55.40", "off Umm Al Quwain"),
    "S3": ("25.45,55.35", "off Sharjah / Hamriyah"),
    "S4": ("25.98,55.85", "off Ras Al Khaimah near Dhayah"),
}
COPY_TOL_KM = 0.05  # every particle moves within 50 m of the same particle at another site: a copy
SIMILAR_KM = 0.5  # median closer than this: suspiciously similar (all runs use the same random seed)


def _moves(drift_dir: Path) -> dict[str, tuple[float, float, float, float]]:
    """Each particle's move from 0 h to the last step, by particle id: (north km, east km, dlat, dlon).

    A copy shifted in degrees moves by the same degrees; one shifted in km by the same km."""
    steps: dict[float, dict[str, tuple[float, float]]] = {}
    for f in json.loads((drift_dir / "drift.geojson").read_text(encoding="utf-8"))["features"]:
        geom, props = f.get("geometry") or {}, f.get("properties") or {}
        if geom.get("type") not in ("Point", "MultiPoint"):
            continue
        ids = props.get("particle_ids") or ([props["particle_id"]] if "particle_id" in props else [])
        pts = [geom["coordinates"]] if geom["type"] == "Point" else geom["coordinates"]
        step = steps.setdefault(float(props["hours"]), {})
        for pid, c in zip(ids, pts):
            step[str(pid)] = (c[1], c[0])
    if not steps:
        return {}
    first, last = steps[min(steps)], steps[max(steps)]
    out = {}
    for pid, (lat0, lon0) in first.items():
        if pid in last:
            lat1, lon1 = last[pid]
            north = _km(_point([lon0, lat0]), _point([lon0, lat1])) * (1 if lat1 >= lat0 else -1)
            east = _km(_point([lon0, lat0]), _point([lon1, lat0])) * (1 if lon1 >= lon0 else -1)
            out[pid] = (north, east, lat1 - lat0, lon1 - lon0)
    return out


def compare_sites(drift_dirs: dict[str, Path]) -> list[dict]:
    """One row per pair of sites: how differently their particles moved."""
    moves = {site: _moves(d) for site, d in drift_dirs.items()}
    rows = []
    names = sorted(moves)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            shared = set(moves[a]) & set(moves[b])
            if not shared:
                continue
            ma, mb = moves[a], moves[b]
            km = [hypot(ma[p][0] - mb[p][0], ma[p][1] - mb[p][1]) for p in shared]
            # the same move in degrees, measured in km at site a
            deg = [hypot((ma[p][2] - mb[p][2]) * 111.2, (ma[p][3] - mb[p][3]) * 111.2 * cos(radians(25.8)))
                   for p in shared]
            closest = min((km, deg), key=max)
            rows.append({"sites": f"{a}-{b}", "particles": len(shared), "median_km": median(closest),
                         "max_km": max(closest), "copy": max(closest) <= COPY_TOL_KM,
                         "similar": median(closest) < SIMILAR_KM})
    return rows


def _summary_row(site: str, place: str, r, result: dict) -> dict:
    opt = result.get("optimized", {})
    metrics = (result.get("metrics") or {}).get("recalculated") or {}
    stranded = result.get("stranded_by_hour") or {}
    last_stranded = stranded[max(stranded)] if stranded else {"particles": 0, "m3": 0.0}
    c = r.counts()
    return {
        "site": site, "place": place, "release": result.get("release"),
        "result": f"{c['OK']} OK, {c['WARN']} WARN, {c['FAIL']} FAIL", "fail": c["FAIL"],
        "afloat_at_dispatch_m3": result["targets"]["oil_afloat_at_dispatch_m3"],
        "stranded_end_m3": last_stranded["m3"], "stranded_end_particles": last_stranded["particles"],
        "targets": len(result["targets"]["targets"]),
        "vessels": [row["vessel_id"] for row in opt.get("routes", []) if row["targets"]],
        "unserved": opt.get("unserved", []),
        **{k: metrics.get(k) for k in ("optimized_oil_recovered_m3", "baseline_oil_recovered_m3",
                                       "optimized_response_hours", "baseline_response_hours",
                                       "optimized_distance_km", "baseline_distance_km", "distance_change_percent",
                                       "travel_hours_change_percent")},
    }


def _f(x, fmt="{:.1f}"):
    return "n/a" if x is None else fmt.format(x)


def summary_markdown(rows: list[dict], pairs: list[dict]) -> str:
    short = {"RAK-FRV-FALCON": "FALCON", "RAK-OSRV-SAQR": "SAQR", "HAMRIYAH-OSRV-RESERVE": "Hamriyah"}
    lines = [
        "| Site | Afloat at dispatch (m³) | Stranded by 24 h (m³) | Targets | Vessels used (optimized) | "
        "Oil cleaned, optimized / baseline (m³) | Back in port, optimized / baseline (h after dispatch) | "
        "Distance change | Validation |",
        "| --- | ---: | ---: | ---: | --- | --- | --- | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['site']} {row['place']} | {_f(row['afloat_at_dispatch_m3'])} | {_f(row['stranded_end_m3'])} | "
            f"{row['targets']} | {', '.join(short.get(v, v) for v in row['vessels']) or 'none'} | "
            f"{_f(row['optimized_oil_recovered_m3'])} / {_f(row['baseline_oil_recovered_m3'])} | "
            f"{_f(row['optimized_response_hours'], '{:.2f}')} / {_f(row['baseline_response_hours'], '{:.2f}')} | "
            f"{_f(row['distance_change_percent'], '{:+.1f} %')} | {row['result']} |")
    if pairs:
        copies = [p["sites"] for p in pairs if p["copy"]]
        similar = [p["sites"] for p in pairs if p["similar"] and not p["copy"]]
        least = min(pairs, key=lambda p: p["median_km"])
        lines += ["", "Own drift run per site: " + (
            f"**NO**, {', '.join(copies)} move identically (translated copies of one run)." if copies else
            f"probably, but {', '.join(similar)} move very alike (median {least['median_km']:.2f} km apart after "
            "24 h): check with Maqqavi." if similar else
            f"yes. The most similar pair, {least['sites']}, still differs by {least['median_km']:.2f} km "
            "(median) in how far and where its particles move in 24 h.")]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sites-dir", default=str(REPO_ROOT / "outputs" / "sites"))
    ap.add_argument("--fleet", default=str(REPO_ROOT / "optimization" / "fixtures" / "gulf_standard.json"),
                    help="the fleet the routes were planned with")
    ap.add_argument("--sites", nargs="*", default=list(SITES), help="which site folders (default: S1 S2 S3 S4)")
    ap.add_argument("--write", action="store_true", help="write validation.txt/.json per site and sites_summary.md/.json")
    ap.add_argument("--details", action="store_true", help="print every check of every site")
    args = ap.parse_args()
    root = Path(args.sites_dir)

    rows, drift_dirs, failed = [], {}, False
    for site in args.sites:
        folder = root / site
        if not (folder / "drift").is_dir() or not (folder / "routing").is_dir():
            print(f"{site}: no drift/ and routing/ in {folder}, skipped")
            failed = True
            continue
        release, place = SITES.get(site, (None, ""))
        r, result = validate(folder / "drift", folder / "routing", args.fleet,
                             parse_point(release) if release else None)
        drift_dirs[site] = folder / "drift"
        rows.append(_summary_row(site, place, r, result))
        failed |= bool(r.counts()["FAIL"])
        if args.details:
            print(f"\n===== {site} =====")
            print_report(r)
        else:
            for row in r.rows:
                if row["level"] == "FAIL":
                    print(f"{site} [FAIL] {row['group']}: {row['text']}")
        if args.write:
            text = io.StringIO()
            with contextlib.redirect_stdout(text):
                print_report(r)
            (folder / "validation.txt").write_text(text.getvalue(), encoding="utf-8")
            write_json(folder / "validation.json", r, result)

    pairs = compare_sites(drift_dirs)
    failed |= any(p["copy"] for p in pairs)
    table = summary_markdown(rows, pairs)
    print("\n" + table)
    if args.write:
        (root / "sites_summary.md").write_text(table, encoding="utf-8")
        (root / "sites_summary.json").write_text(
            json.dumps({"sites": rows, "site_pairs": pairs}, indent=2, default=str), encoding="utf-8")
        print(f"wrote validation.txt/.json in each site folder, and sites_summary.md/.json in {root}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
