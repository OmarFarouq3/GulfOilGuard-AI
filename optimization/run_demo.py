"""One-command demo: scenario file in, plan file out.

Run from the repository root:
    python -m optimization.run_demo
    python -m optimization.run_demo --scenario path/to/scenario.json --out plan.json
"""

import argparse
from pathlib import Path

from optimization.checks import check_plan
from optimization.scenario_io import load_scenario, save_plan
from optimization.vessel_routing import optimize_routes

EXAMPLES = Path(__file__).parent / "examples"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run cleanup route optimization.")
    parser.add_argument("--scenario", default=str(EXAMPLES / "scenario_demo_easy.json"))
    parser.add_argument("--out", default=str(EXAMPLES / "plan_demo.json"))
    args = parser.parse_args()

    scenario_id, vessels, targets = load_scenario(args.scenario)
    plan = optimize_routes(vessels, targets)

    print(f"Scenario: {scenario_id}")
    print(f"Status:   {plan.status}")
    print(f"Message:  {plan.message}")
    for route in plan.routes:
        stops = " -> ".join(route.assigned_target_ids) or "(no targets)"
        print(
            f"  {route.vessel_id}: {stops}  |  "
            f"{route.estimated_distance_km:.1f} km, {route.estimated_travel_hours:.2f} h"
        )

    violations = check_plan(plan, vessels, targets)
    print(
        "Rule check: "
        + ("passed" if not violations else "FAILED: " + "; ".join(violations))
    )

    save_plan(plan, args.out)
    print(f"Saved plan to {args.out}")


if __name__ == "__main__":
    main()
