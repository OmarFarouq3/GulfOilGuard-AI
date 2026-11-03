"""Drift forecast in, cleanup plan for MOVING oil out, with the nearest-target baseline.

  1. read the drift forecast (Maqqavi's outputs/drift/, or the synthetic stand-in)
  2. cut the oil into patches at the dispatch hour and follow them (drift_targets.py)
  3. plan with OR-Tools inside the re-planning loop, and the baseline, against the same
     moving oil, fleet, distances and rules (moving_targets.py)
  4. write the dashboard files (outputs/routing/), the baseline's files
     (outputs/routing/baseline/) and comparison.json

The fleet comes from a scenario file; its targets are ignored. Run from the repository root:
    python -m optimization.run_drift_plan
    python -m optimization.run_drift_plan --drift-dir optimization/examples/drift_standin
    python -m optimization.run_drift_plan --dispatch-hours 12 --fleet optimization/fixtures/gulf_standard.json
    python -m optimization.run_drift_plan --pure-oil    # tanks as pure oil, to compare with emulsion
"""

import argparse
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

from optimization.config import DEFAULT_CONFIG, DEFAULT_DRIFT_CONFIG, REPO_ROOT
from optimization.dashboard_export import DEFAULT_DIR, export_comparison, export_for_dashboard
from optimization.drift_targets import DEFAULT_DRIFT_DIR, build_tracks, load_drift
from optimization.evaluate_routes import evaluate_routes, format_comparison
from optimization.moving_targets import MovingPlan, nearest_first_moving, solve_moving
from optimization.run_demo import print_plan
from optimization.scenario_io import load_scenario, scenario_is_synthetic
from optimization.sea_distance import default_provider

DEFAULT_FLEET = Path(__file__).parent / "fixtures" / "gulf_standard.json"
STANDIN_DIR = Path(__file__).parent / "examples" / "drift_standin"
FOLLOW_NOTE = {
    "patch_id": "patches followed by the drift module's patch_id",
    "particle_id": "patches cut into cells at dispatch, then followed by their particle ids",
    "static": "STATIC: the drift files have no patch_id or particle ids, so patches cannot be "
              "followed and stay where they were at dispatch",
}


def _whole(hours: float) -> float:
    return int(hours) if float(hours).is_integer() else hours  # "12", not "12.0", in the files


def _clock(start_time: str | None, hours: float) -> str | None:
    if not start_time:
        return None
    start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    return (start + timedelta(minutes=round(hours * 60))).isoformat().replace("+00:00", "Z")


def _layer_hours(result: MovingPlan, steps, dispatch_hours: float) -> float:
    """The forecast step nearest the average meeting time: the best oil layer to draw under the routes."""
    when = mean(result.meet_hours.values()) if result.meet_hours else dispatch_hours
    return _whole(min(steps, key=lambda h: abs(h - when)))


def _target_properties(result: MovingPlan, start_time: str | None, dispatch_hours: float) -> dict:
    return {
        t.target_id: {
            "meet_hours": round(result.meet_hours[t.target_id], 2) if t.target_id in result.meet_hours else None,
            "meet_time": _clock(start_time, result.meet_hours[t.target_id]) if t.target_id in result.meet_hours else None,
            "drifted_km": round(result.moved_km.get(t.target_id, 0.0), 2),
            "position_hours": round(result.meet_hours.get(t.target_id, dispatch_hours), 2),
        }
        for t in result.targets
    }


def _moved_summary(result: MovingPlan) -> dict:
    moved = list(result.moved_km.values())
    return {"mean_km": round(mean(moved), 2) if moved else 0.0, "max_km": round(max(moved), 2) if moved else 0.0}


def _with_notes(result: MovingPlan, notes: list[str]) -> MovingPlan:
    """The drift assumptions belong in the plan's own message too."""
    message = "; ".join(filter(None, [result.plan.message, *notes]))
    return replace(result, plan=replace(result.plan, message=message))


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan cleanup routes for a moving drift forecast.")
    parser.add_argument("--drift-dir", default=str(DEFAULT_DRIFT_DIR), help="folder with drift.geojson")
    parser.add_argument("--dispatch-hours", type=float, default=DEFAULT_DRIFT_CONFIG.dispatch_hours,
                        help="when the vessels leave port, hours since release (a drift step)")
    parser.add_argument("--fleet", default=str(DEFAULT_FLEET), help="scenario file with the vessels")
    parser.add_argument("--dashboard-dir", default=str(DEFAULT_DIR))
    parser.add_argument("--pure-oil", action="store_true",
                        help="count tank use and cleanup time as pure oil, not emulsion (for comparison)")
    args = parser.parse_args()
    dispatch = _whole(args.dispatch_hours)
    drift_config = replace(DEFAULT_DRIFT_CONFIG, count_emulsion=not args.pure_oil)

    try:
        forecast = load_drift(args.drift_dir, drift_config)
    except FileNotFoundError as exc:
        standin = STANDIN_DIR.relative_to(REPO_ROOT)
        raise SystemExit(f"{exc}\nNo drift output yet? Test with the synthetic stand-in:\n"
                         f"  python -m optimization.run_drift_plan --drift-dir {standin}") from exc
    fleet_id, vessels, _ = load_scenario(args.fleet)
    try:
        patches = build_tracks(forecast, dispatch, max_target_m3=max(v.capacity_m3 for v in vessels))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    tracks = patches.tracks
    synthetic = forecast.synthetic or scenario_is_synthetic(args.fleet)
    scenario_id = f"{forecast.simulation_id}@dispatch{dispatch:g}h"
    steps = list(forecast.steps)
    targeted = sum(t.volumes[0] for t in tracks)

    print(f"Drift forecast: {forecast.simulation_id}{'  (SYNTHETIC)' if forecast.synthetic else ''}")
    print(f"  {len(steps)} steps from {steps[0]:g} to {steps[-1]:g} h; vessels leave at {dispatch:g} h")
    print(f"  {FOLLOW_NOTE[patches.follow]}")
    print(f"  oil afloat at dispatch {patches.oil_afloat_m3:.1f} m3 -> {len(tracks)} moving targets "
          f"holding {targeted:.1f} m3 ({patches.untargeted_m3:.1f} m3 in small patches not targeted)")
    for note in forecast.notes:
        print(f"  assumption: {note}")
    water = forecast.water_fraction
    if water:
        print(f"  emulsion: water fraction {water[dispatch]:.0%} at dispatch, {water[steps[-1]]:.0%} at "
              f"{steps[-1]:g} h, so 1 m3 of oil fills {1 / (1 - water[dispatch]):.2f} to "
              f"{1 / (1 - water[steps[-1]]):.2f} m3 of tank")
    print(f"Fleet: {fleet_id}, {len(vessels)} vessels")

    provider = default_provider(DEFAULT_CONFIG)  # one provider, so both plans measure alike
    notes = [FOLLOW_NOTE[patches.follow], *forecast.notes]
    optimized, baseline = (
        _with_notes(solve(vessels, tracks, dispatch, provider), notes)
        for solve in (solve_moving, nearest_first_moving)
    )

    print_plan("OPTIMIZED PLAN (OR-Tools, re-planned for moving oil)", optimized.plan, vessels, optimized.targets)
    print_plan("BASELINE (nearest interception first)", baseline.plan, vessels, baseline.targets)
    print("\nCOMPARISON (oil as each plan finds it)")
    try:
        metrics = evaluate_routes(optimized.plan, baseline.plan, optimized.targets,
                                  baseline_targets=baseline.targets)
        print(format_comparison(metrics))
        print(f"  Share of the oil afloat at dispatch recovered: optimized "
              f"{metrics['optimized_oil_recovered_m3'] / patches.oil_afloat_m3:.0%}, baseline "
              f"{metrics['baseline_oil_recovered_m3'] / patches.oil_afloat_m3:.0%}")
    except ValueError as exc:
        print(f"  {exc}")
    cleaned = {
        name: None if r.last_cleanup_hours is None else round(r.last_cleanup_hours - dispatch, 2)
        for name, r in (("optimized", optimized), ("baseline", baseline))
    }
    if None not in cleaned.values():
        print(f"  Last patch cleaned {cleaned['optimized']:.2f} h after dispatch (baseline "
              f"{cleaned['baseline']:.2f} h); the response time above adds the trip back to port.")
    moved = _moved_summary(optimized)
    print(f"  Patches drifted {moved['mean_km']:.1f} km on average (max {moved['max_km']:.1f} km) between "
          "dispatch and the vessel reaching them: how far off a plan with frozen oil would aim.")

    layer = _layer_hours(optimized, steps, dispatch)
    details = {
        "drift": {
            "simulation_id": forecast.simulation_id,
            "drift_dir": str(args.drift_dir),
            "follow": patches.follow,
            "dispatch_hours": dispatch,
            "dispatch_time": _clock(forecast.start_time, dispatch),
            "forecast_steps_hours": [_whole(h) for h in steps],
            "oil_afloat_at_dispatch_m3": round(patches.oil_afloat_m3, 2),
            "targeted_oil_at_dispatch_m3": round(targeted, 2),
            "untargeted_oil_m3": round(patches.untargeted_m3, 2),
            "cell_deg": DEFAULT_DRIFT_CONFIG.cell_deg,
            "tank_basis": "emulsion" if water else "pure oil",
            "water_fraction_by_hour": {f"{h:g}": round(w, 3) for h, w in water.items()} or None,
            "assumptions": notes,
        },
        "fleet": fleet_id,
        "replan_rounds": optimized.rounds,
        "last_patch_cleaned_hours_after_dispatch": cleaned,
        "patch_drift_before_meeting_km": {"optimized": moved, "baseline": _moved_summary(baseline)},
    }
    out = Path(args.dashboard_dir)
    for result, folder in ((optimized, out), (baseline, out / "baseline")):
        export_for_dashboard(
            result.plan, vessels, result.targets, folder, scenario_id=scenario_id, synthetic=synthetic,
            distance_provider=provider, source_hours=layer,
            target_properties=_target_properties(result, forecast.start_time, dispatch),
        )
    export_comparison(optimized.plan, baseline.plan, vessels, optimized.targets, out,
                      scenario_id=scenario_id, synthetic=synthetic,
                      baseline_targets=baseline.targets, details=details)
    label = " (labelled as a simulated scenario)" if synthetic else ""
    print(f"\nWrote dashboard files, comparison.json and baseline/ to {out}{label}")


if __name__ == "__main__":
    main()
