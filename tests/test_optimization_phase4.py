"""Phase 4 tests: the baseline and the comparison.

Run from the repository root:
    python -m pytest tests/test_optimization_phase4.py

The baseline and comparison tests do not need OR-Tools. Tests that compare against the
OR-Tools plan are skipped if it is not installed. All use straight-line distances.
"""

import math

import pytest

from optimization.baseline import nearest_first_routes
from optimization.checks import check_plan
from optimization.evaluate_routes import evaluate_routes, format_comparison
from optimization.scenario_io import load_scenario
from optimization.sea_distance import StraightLineDistance, haversine_km
from shared.schemas import (
    GeoCoordinate,
    OptimizationOutput,
    ResponseTarget,
    Vessel,
    VesselRoute,
)

STRAIGHT = StraightLineDistance()


def vessel(vessel_id="V1", lat=25.4, lon=55.0, speed=5.0, capacity=500.0, hours=20.0):
    return Vessel(vessel_id, GeoCoordinate(lat, lon), speed, capacity, hours)


def target(target_id="T1", lat=25.8, lon=54.5, volume=60.0):
    return ResponseTarget(target_id, GeoCoordinate(lat, lon), volume)


def baseline(vessels, targets):
    return nearest_first_routes(tuple(vessels), tuple(targets), distance_provider=STRAIGHT)


# ---- the baseline ------------------------------------------------------------


def test_baseline_visits_the_nearest_target_first():
    near = target("NEAR", lat=25.5, lon=55.0)
    far = target("FAR", lat=26.0, lon=55.0)
    plan = baseline([vessel()], [far, near])  # given in the "wrong" order on purpose
    assert plan.status == "feasible", plan.message
    assert plan.routes[0].assigned_target_ids == ("NEAR", "FAR")
    expected = (
        haversine_km(vessel().location, near.location)
        + haversine_km(near.location, far.location)
        + haversine_km(far.location, vessel().location)  # back to port
    )
    assert plan.routes[0].estimated_distance_km == pytest.approx(expected, rel=1e-9)


def test_baseline_respects_tank_and_hours():
    big = target("T1", volume=400.0)
    tiny_tank = vessel(capacity=100.0)
    plan = baseline([tiny_tank], [big])
    assert not plan.routes[0].assigned_target_ids
    assert "larger than every vessel tank" in plan.message

    short_day = vessel(hours=2.0)  # 60 m3 needs 2 h of cleanup, plus sailing
    plan = baseline([short_day], [target(volume=60.0)])
    assert not plan.routes[0].assigned_target_ids


def test_baseline_plans_pass_the_same_rule_check_as_ours():
    for name in ("easy", "hard"):
        _, vessels, targets = load_scenario(f"optimization/examples/scenario_demo_{name}.json")
        plan = baseline(vessels, targets)
        assert plan.status == "feasible", plan.message
        assert check_plan(plan, vessels, targets) == [], name
        assert len(plan.routes) == len(vessels)  # every vessel is listed, even an idle one


def test_baseline_is_deterministic():
    _, vessels, targets = load_scenario("optimization/examples/scenario_demo_hard.json")
    first = baseline(vessels, targets)
    second = baseline(vessels, targets)
    assert first == second


def test_baseline_bad_input_and_empty_cases():
    assert baseline([vessel(speed=-1.0)], [target()]).status == "error"
    assert baseline([vessel()], []).status == "feasible"
    assert baseline([], [target()]).status == "infeasible"


# ---- the comparison ----------------------------------------------------------


def make_plan(*routes):
    return OptimizationOutput(routes=tuple(routes), status="feasible")


def route(vessel_id, ids, distance, hours):
    here = GeoCoordinate(25, 55)
    return VesselRoute(vessel_id, tuple(ids), (here,) * (1 + len(ids)), distance, hours)


def test_evaluate_routes_numbers():
    optimized = make_plan(route("V1", ["T1", "T2"], 10.0, 1.0), route("V2", [], 0.0, 0.0))
    base = make_plan(route("V1", ["T1"], 8.0, 0.8), route("V2", ["T2"], 6.0, 0.6))
    m = evaluate_routes(optimized, base)
    assert m["optimized_distance_km"] == 10.0 and m["baseline_distance_km"] == 14.0
    assert m["distance_change_percent"] == pytest.approx(-28.5714, abs=1e-3)
    assert m["optimized_travel_hours"] == pytest.approx(1.0)
    assert m["baseline_travel_hours"] == pytest.approx(1.4)
    assert m["optimized_longest_route_hours"] == 1.0
    assert m["baseline_longest_route_hours"] == 0.8
    assert m["optimized_targets_covered"] == 2.0 and m["baseline_targets_covered"] == 2.0
    assert m["targets_covered_difference"] == 0.0
    assert m["same_targets_covered"] == 1.0
    assert m["optimized_distance_km_per_target"] == 5.0
    assert m["baseline_distance_km_per_target"] == 7.0
    assert all(isinstance(value, float) for value in m.values())


def test_evaluate_routes_flags_different_coverage():
    optimized = make_plan(route("V1", ["T1", "T2"], 10.0, 1.0))
    base = make_plan(route("V1", ["T1"], 4.0, 0.4))
    m = evaluate_routes(optimized, base)
    assert m["targets_covered_difference"] == 1.0
    assert m["same_targets_covered"] == 0.0
    assert "not directly comparable" in format_comparison(m)


def test_evaluate_routes_handles_no_targets_and_refuses_bad_plans():
    empty = make_plan(route("V1", [], 0.0, 0.0))
    m = evaluate_routes(empty, empty)
    assert m["distance_change_percent"] == 0.0
    assert math.isnan(m["optimized_distance_km_per_target"])

    broken = OptimizationOutput(routes=(), status="error", message="boom")
    with pytest.raises(ValueError, match="cannot compare"):
        evaluate_routes(broken, empty)
    missing = make_plan(VesselRoute("V1", (), (GeoCoordinate(25, 55),), None, None))
    with pytest.raises(ValueError, match="no estimated"):
        evaluate_routes(empty, missing)


# ---- ours against the baseline (needs OR-Tools) ------------------------------


def test_our_plan_is_never_worse_than_the_baseline_on_the_demo_scenarios():
    pytest.importorskip("ortools")
    from optimization.routing_model import solve_routes

    for name in ("easy", "hard"):
        _, vessels, targets = load_scenario(f"optimization/examples/scenario_demo_{name}.json")
        ours = solve_routes(vessels, targets, distance_provider=STRAIGHT)
        theirs = nearest_first_routes(vessels, targets, distance_provider=STRAIGHT)
        assert check_plan(ours, vessels, targets) == [], name
        assert check_plan(theirs, vessels, targets) == [], name

        # The solver puts oil first and response time second, so judge it the same way.
        m = evaluate_routes(ours, theirs, targets)
        assert m["optimized_oil_recovered_m3"] >= m["baseline_oil_recovered_m3"], f"{name}: less oil"
        if m["optimized_oil_recovered_m3"] == m["baseline_oil_recovered_m3"]:
            assert m["optimized_response_hours"] <= m["baseline_response_hours"] + 1e-3, name
