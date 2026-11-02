"""Check the sea-distance setup with your real land file, before trusting any plan.

Run from the repository root:
    python -m optimization.sea_check
    python -m optimization.sea_check --scenario optimization/examples/scenario_demo_easy.json --plot check.png
    python -m optimization.sea_check --plan optimization/examples/plan_demo.json --plot check.png

It prints how big the water grid is, whether every vessel and target is on water,
and how much longer each sea distance is than a straight line. A ratio far above 1
means the path has to go around land. With --plot it saves a picture of the grid.
"""

import argparse
import time
from pathlib import Path

from optimization.config import DEFAULT_CONFIG
from optimization.scenario_io import load_plan, load_scenario
from optimization.sea_distance import haversine_km
from optimization.sea_grid import SeaRoutingError, default_sea_provider, find_land_file

EXAMPLES = Path(__file__).parent / "examples"


def _plot(provider, points, labels, plan, out_path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    reg = provider.mask.region
    fig, ax = plt.subplots(figsize=(9, 7))
    ax.imshow(
        provider.mask.land,
        extent=[reg.lon_min, reg.lon_max, reg.lat_min, reg.lat_max],
        cmap="Greys",
        origin="upper",
        alpha=0.6,
    )
    if plan is not None:
        for route in plan.routes:
            stops = route.coordinates
            for a, b in zip(stops, stops[1:]):
                path = provider.path(a, b)
                ax.plot([p.longitude for p in path], [p.latitude for p in path], linewidth=2)
    ax.scatter([p.longitude for p in points], [p.latitude for p in points], c="red", zorder=5)
    for p, name in zip(points, labels):
        ax.annotate(name, (p.longitude, p.latitude), xytext=(4, 4), textcoords="offset points")
    lons = [p.longitude for p in points]
    lats = [p.latitude for p in points]
    ax.set_xlim(min(lons) - 0.6, max(lons) + 0.6)
    ax.set_ylim(min(lats) - 0.6, max(lats) + 0.6)
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title("Land (grey) and sea. Coloured lines are sea paths.")
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    print(f"Saved picture to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check navigable-water distances.")
    parser.add_argument("--scenario", default=str(EXAMPLES / "scenario_demo_easy.json"))
    parser.add_argument("--plan", default=None, help="draw the sea paths of a saved plan")
    parser.add_argument("--plot", default=None, help="save a picture to this file")
    args = parser.parse_args()

    try:
        land_file = find_land_file(DEFAULT_CONFIG.land_dir)
    except FileNotFoundError as exc:
        print(f"PROBLEM: {exc}")
        raise SystemExit(1)
    print(f"Land file: {land_file}")

    started = time.time()
    provider = default_sea_provider(DEFAULT_CONFIG)
    reg = provider.mask.region
    print(
        f"Grid: {reg.rows} x {reg.cols} cells of {provider.cell_km:.1f} km, "
        f"{provider.mask.water_fraction * 100:.0f}% water (loaded in {time.time() - started:.1f} s)"
    )

    _, vessels, targets = load_scenario(args.scenario)
    points = [v.location for v in vessels] + [t.location for t in targets]
    labels = [v.vessel_id for v in vessels] + [t.target_id for t in targets]

    try:
        matrix = provider.matrix_km(points, labels)
    except SeaRoutingError as exc:
        print(f"PROBLEM: {exc}")
        raise SystemExit(1)

    if provider.warnings:
        print("Warnings:")
        for warning in provider.warnings:
            print(f"  - {warning}")
    else:
        print("All points are on water.")

    print("\nSea distance vs straight line (vessel to target):")
    print(f"  {'pair':<10}{'sea km':>9}{'straight km':>13}{'ratio':>8}")
    for i, v in enumerate(vessels):
        for j, t in enumerate(targets):
            a, b = len(vessels) + j, i
            sea, straight = matrix[b][a], haversine_km(points[b], points[a])
            ratio = sea / straight if straight > 0 else 1.0
            # A grid can be off by about one cell at each end, so short legs look longer
            # than they are. Only flag a leg when the extra distance is clearly more than that.
            extra = sea - straight
            flag = "   <- goes around land" if ratio > 1.15 and extra > 3 * provider.cell_km else ""
            print(f"  {v.vessel_id}-{t.target_id:<7}{sea:>9.1f}{straight:>13.1f}{ratio:>8.2f}{flag}")

    if args.plot:
        plan = load_plan(args.plan) if args.plan else None
        _plot(provider, points, labels, plan, args.plot)


if __name__ == "__main__":
    main()
