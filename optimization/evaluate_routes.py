"""Compare an optimized plan with a baseline plan.

A fair comparison needs identical inputs and identical rules. Both plans must be made
from the same vessels, targets, distance provider and settings. Check both with
optimization.checks.check_plan before you trust the numbers.

How to read the numbers:
  - Distance and time alone can mislead. A plan that skips targets sails less.
    So always read them together with the number of targets covered, and with
    `distance_km_per_target`.
  - `same_targets_covered` is 1.0 when both plans serve exactly the same targets.
    Only then is a plain distance comparison apples to apples.
  - When the targets are given, read oil recovered first and response time second:
    that is what the solver aims for, and what the dashboard shows at the top.
"""

from dataclasses import dataclass

from optimization.config import DEFAULT_CONFIG, RoutingConfig
from optimization.limits import service_hours
from shared.schemas import OptimizationOutput, ResponseTarget


@dataclass(frozen=True)
class _Summary:
    distance_km: float
    travel_hours: float
    longest_route_hours: float
    target_ids: frozenset[str]


def _summarize(name: str, plan: OptimizationOutput) -> _Summary:
    if plan.status not in ("optimal", "feasible"):
        raise ValueError(f"cannot compare: the {name} plan has status '{plan.status}' ({plan.message})")
    distance = hours = longest = 0.0
    ids: list[str] = []
    for route in plan.routes:
        if route.estimated_distance_km is None or route.estimated_travel_hours is None:
            raise ValueError(f"cannot compare: a {name} route has no estimated distance or time")
        distance += route.estimated_distance_km
        hours += route.estimated_travel_hours
        longest = max(longest, route.estimated_travel_hours)
        ids.extend(route.assigned_target_ids)
    return _Summary(distance, hours, longest, frozenset(ids))


def _change_percent(new: float, old: float) -> float:
    return 0.0 if old == 0 else (new - old) / old * 100.0


def _oil_and_response(
    plan: OptimizationOutput, targets: tuple[ResponseTarget, ...], config: RoutingConfig
) -> tuple[float, float]:
    """(oil recovered in m3, hours until the last vessel is done: sailing + cleanup)."""
    volume_by_id = {t.target_id: t.oil_volume_m3 for t in targets}
    oil = response = 0.0
    for route in plan.routes:
        volumes = [volume_by_id[t] for t in route.assigned_target_ids if t in volume_by_id]
        oil += sum(volumes)
        cleanup = sum(service_hours(v, config) for v in volumes)
        response = max(response, (route.estimated_travel_hours or 0.0) + cleanup)
    return oil, response


def evaluate_routes(
    optimized: OptimizationOutput,
    baseline: OptimizationOutput,
    targets: tuple[ResponseTarget, ...] | None = None,
    config: RoutingConfig = DEFAULT_CONFIG,
) -> dict[str, float]:
    """Compare distance (km), travel time (hours), and target coverage.

    Travel time means sailing time only (cleanup time is not included). Negative
    change percentages mean the optimized plan is lower (better for distance and time).
    `distance_km_per_target` is nan when a plan covers no target.
    With `targets`, also oil recovered (m3) and response time (hours until the last
    vessel finishes, cleanup included).
    Raises ValueError if either plan did not produce a usable result.
    """
    opt = _summarize("optimized", optimized)
    base = _summarize("baseline", baseline)

    def per_target(summary: _Summary) -> float:
        return summary.distance_km / len(summary.target_ids) if summary.target_ids else float("nan")

    extra: dict[str, float] = {}
    if targets is not None:
        opt_oil, opt_response = _oil_and_response(optimized, targets, config)
        base_oil, base_response = _oil_and_response(baseline, targets, config)
        extra = {
            "total_oil_m3": float(sum(t.oil_volume_m3 for t in targets)),
            "optimized_oil_recovered_m3": opt_oil,
            "baseline_oil_recovered_m3": base_oil,
            "oil_recovered_change_percent": _change_percent(opt_oil, base_oil),
            "optimized_response_hours": opt_response,
            "baseline_response_hours": base_response,
            "response_hours_change_percent": _change_percent(opt_response, base_response),
        }

    return extra | {
        "optimized_distance_km": opt.distance_km,
        "baseline_distance_km": base.distance_km,
        "distance_change_percent": _change_percent(opt.distance_km, base.distance_km),
        "optimized_travel_hours": opt.travel_hours,
        "baseline_travel_hours": base.travel_hours,
        "travel_hours_change_percent": _change_percent(opt.travel_hours, base.travel_hours),
        "optimized_longest_route_hours": opt.longest_route_hours,
        "baseline_longest_route_hours": base.longest_route_hours,
        "optimized_targets_covered": float(len(opt.target_ids)),
        "baseline_targets_covered": float(len(base.target_ids)),
        "targets_covered_difference": float(len(opt.target_ids) - len(base.target_ids)),
        "same_targets_covered": 1.0 if opt.target_ids == base.target_ids else 0.0,
        "optimized_distance_km_per_target": per_target(opt),
        "baseline_distance_km_per_target": per_target(base),
    }


def format_comparison(metrics: dict[str, float]) -> str:
    """A small plain-text table of the numbers from evaluate_routes."""
    rows = [
        ("Oil recovered (m3)", "oil_recovered_m3", "{:.0f}"),
        ("Response time, cleanup incl. (h)", "response_hours", "{:.2f}"),
        ("Targets covered", "targets_covered", "{:.0f}"),
        ("Distance (km)", "distance_km", "{:.1f}"),
        ("Sailing time, all vessels (h)", "travel_hours", "{:.2f}"),
        ("Longest single route (h)", "longest_route_hours", "{:.2f}"),
        ("Distance per target (km)", "distance_km_per_target", "{:.1f}"),
    ]
    lines = [f"  {'':<32}{'optimized':>11}{'baseline':>11}"]
    for label, key, fmt in rows:
        if "optimized_" + key not in metrics:
            continue  # oil and response time need the targets
        lines.append(
            f"  {label:<32}{fmt.format(metrics['optimized_' + key]):>11}"
            f"{fmt.format(metrics['baseline_' + key]):>11}"
        )
    if "total_oil_m3" in metrics:
        lines.append(f"  Oil change: {metrics['oil_recovered_change_percent']:+.1f}% "
                     f"(of {metrics['total_oil_m3']:.0f} m3 in all targets)   "
                     f"Response time change: {metrics['response_hours_change_percent']:+.1f}%")
    lines.append(f"  Distance change: {metrics['distance_change_percent']:+.1f}%   "
                 f"Sailing time change: {metrics['travel_hours_change_percent']:+.1f}%")
    if metrics["same_targets_covered"] == 0.0:
        lines.append(
            "  Note: the two plans cover different targets, so distance and time are not "
            "directly comparable. Read coverage first."
        )
    return "\n".join(lines)
