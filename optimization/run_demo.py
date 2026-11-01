"""One-command demo: scenario file in, plan file out, with a baseline comparison.

It also writes the dashboard files (outputs/routing/), so after this the dashboard's
Respond page shows the plan. Run from the repository root:
    python -m optimization.run_demo
    python -m optimization.run_demo --scenario optimization/examples/scenario_demo_hard.json
    python -m optimization.run_demo --scenario my.json --out plan.json --baseline-out baseline.json
    python -m optimization.run_demo --dashboard-dir sample_outputs/routing
    python -m optimization.run_demo --no-dashboard
"""

import argparse
from pathlib import Path

from optimization.baseline import nearest_first_routes
from optimization.checks import check_plan
from optimization.config import DEFAULT_CONFIG
from optimization.dashboard_export import DEFAULT_DIR, export_for_dashboard
from optimization.evaluate_routes import evaluate_routes, format_comparison
from optimization.routing_model import solve_routes
from optimization.scenario_io import load_scenario, save_plan, scenario_is_synthetic
from optimization.sea_distance import default_provider

EXAMPLES = Path(__file__).parent / "examples"


def _print_plan(title, plan, vessels, targets) -> None:
    print(f"\n{title}")
    print(f"  Status:  {plan.status}")
    print(f"  Message: {plan.message}")
    for route in plan.routes:
        stops = " -> ".join(route.assigned_target_ids) or "(no targets)"
        print(
            f"  {route.vessel_id}: {stops}  |  "
            f"{route.estimated_distance_km:.1f} km, {route.estimated_travel_hours:.2f} h sailing"
        )
    violations = check_plan(plan, vessels, targets)
    print("  Rule check: " + ("passed" if not violations else "FAILED: " + "; ".join(violations)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run cleanup route optimization.")
    parser.add_argument("--scenario", default=str(EXAMPLES / "scenario_demo_easy.json"))
    parser.add_argument("--out", default=str(EXAMPLES / "plan_demo.json"))
    parser.add_argument("--baseline-out", default=None, help="also save the baseline plan here")
    parser.add_argument("--dashboard-dir", default=str(DEFAULT_DIR), help="where the dashboard reads routing files")
    parser.add_argument("--no-dashboard", action="store_true", help="do not write the dashboard files")
    args = parser.parse_args()

    scenario_id, vessels, targets = load_scenario(args.scenario)
    print(f"Scenario: {scenario_id}")

    # One provider for both plans, so both measure distance the same way.
    provider = default_provider(DEFAULT_CONFIG)
    plan = solve_routes(vessels, targets, distance_provider=provider)
    baseline = nearest_first_routes(vessels, targets, distance_provider=provider)

    _print_plan("OPTIMIZED PLAN (OR-Tools)", plan, vessels, targets)
    _print_plan("BASELINE (nearest target first)", baseline, vessels, targets)

    print("\nCOMPARISON")
    try:
        print(format_comparison(evaluate_routes(plan, baseline, targets)))
    except ValueError as exc:
        print(f"  {exc}")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    save_plan(plan, args.out)
    print(f"\nSaved plan to {args.out}")
    if args.baseline_out:
        Path(args.baseline_out).parent.mkdir(parents=True, exist_ok=True)
        save_plan(baseline, args.baseline_out)
        print(f"Saved baseline to {args.baseline_out}")
    if not args.no_dashboard:
        synthetic = scenario_is_synthetic(args.scenario)
        export_for_dashboard(
            plan, vessels, targets, args.dashboard_dir,
            scenario_id=scenario_id, synthetic=synthetic, distance_provider=provider,
        )
        label = " (labelled as a simulated scenario)" if synthetic else ""
        print(f"Wrote dashboard files to {args.dashboard_dir}{label}")


if __name__ == "__main__":
    main()
