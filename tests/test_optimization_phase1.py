"""Phase 1 tests for cleanup routing.

Run from the repository root:
    python -m pytest tests/test_optimization_phase1.py

Tests that need OR-Tools are skipped automatically if it is not installed.
"""

import pytest

from optimization.checks import check_plan, validate_inputs
from optimization.scenario_io import load_plan, load_scenario, save_plan
from optimization.sea_distance import StraightLineDistance, haversine_km
from optimization.units import m_per_s_to_km_per_h, travel_hours
from shared.schemas import GeoCoordinate, OptimizationOutput, ResponseTarget, Vessel, VesselRoute


def vessel(vessel_id="V1", lat=25.4, lon=55.0, speed=5.0, capacity=200.0, hours=12.0):
    return Vessel(vessel_id, GeoCoordinate(lat, lon), speed, capacity, hours)


def target(target_id="T1", lat=25.8, lon=54.5, volume=100.0):
    return ResponseTarget(target_id, GeoCoordinate(lat, lon), volume)


def optimize(vessels, targets):
    """Always use straight lines here, so these tests never depend on local data files."""
    pytest.importorskip("ortools")
    from optimization.routing_model import solve_routes

    return solve_routes(tuple(vessels), tuple(targets), distance_provider=StraightLineDistance())


# ---- parts that do not need OR-Tools ----------------------------------------


def test_units():
    assert m_per_s_to_km_per_h(5.0) == pytest.approx(18.0)
    assert travel_hours(36.0, 5.0) == pytest.approx(2.0)


def test_haversine():
    assert haversine_km(GeoCoordinate(0, 0), GeoCoordinate(0, 1)) == pytest.approx(111.19, abs=0.5)
    same = GeoCoordinate(25.0, 55.0)
    assert haversine_km(same, same) == 0.0


def test_straight_line_matrix_is_symmetric_with_zero_diagonal():
    points = [GeoCoordinate(25, 55), GeoCoordinate(26, 54), GeoCoordinate(25.5, 54.5)]
    m = StraightLineDistance().matrix_km(points)
    for i in range(3):
        assert m[i][i] == 0.0
        for j in range(3):
            assert m[i][j] == pytest.approx(m[j][i])


def test_validate_inputs_accepts_good_data():
    assert validate_inputs((vessel(),), (target(),)) == []


def test_validate_inputs_rejects_bad_data():
    problems = validate_inputs(
        (vessel(speed=-1.0), vessel(vessel_id="V1")),
        (target(volume=0.0), target(lat=95.0, target_id="T2")),
    )
    text = " | ".join(problems)
    assert "duplicate vessel_id" in text
    assert "speed" in text
    assert "oil volume" in text
    assert "bad coordinate" in text


def test_check_plan_catches_over_capacity_and_double_service():
    v1, v2 = vessel("V1", capacity=100.0), vessel("V2", capacity=500.0)
    t1, t2 = target("T1", volume=80.0), target("T2", volume=80.0)
    here = GeoCoordinate(25, 55)
    plan = OptimizationOutput(
        routes=(
            VesselRoute("V1", ("T1", "T2"), (here, here, here), 0.0, 0.0),
            VesselRoute("V2", ("T2",), (here, here), 0.0, 0.0),
        ),
        status="feasible",
    )
    text = " | ".join(check_plan(plan, (v1, v2), (t1, t2)))
    assert "over capacity" in text
    assert "served twice" in text


def test_scenario_and_plan_round_trip(tmp_path):
    scenario_id, vessels, targets = load_scenario("optimization/examples/scenario_demo_easy.json")
    assert scenario_id == "demo_easy_01"
    assert len(vessels) == 2 and len(targets) == 3
    assert validate_inputs(vessels, targets) == []

    here = GeoCoordinate(25, 55)
    plan = OptimizationOutput(
        routes=(VesselRoute("V1", ("T1",), (here, GeoCoordinate(25.5, 54.5)), 12.5, 0.7),),
        status="feasible",
        message="hello",
    )
    path = tmp_path / "plan.json"
    save_plan(plan, path)
    assert load_plan(path) == plan


def test_bad_input_gives_error_status_not_a_crash():
    pytest.importorskip("ortools")
    plan = optimize([vessel(speed=-1.0)], [target()])
    assert plan.status == "error"
    assert "speed" in plan.message


# ---- parts that need OR-Tools ------------------------------------------------


def test_one_vessel_one_target():
    plan = optimize([vessel()], [target()])
    assert plan.status == "feasible", plan.message
    route = plan.routes[0]
    assert route.assigned_target_ids == ("T1",)
    assert route.coordinates == (vessel().location, target().location, vessel().location)  # back to port
    expected_km = 2 * haversine_km(vessel().location, target().location)
    assert route.estimated_distance_km == pytest.approx(expected_km, rel=1e-6)
    assert route.estimated_travel_hours == pytest.approx(expected_km / 18.0, rel=1e-6)


def test_every_vessel_gets_a_route_even_if_unused():
    plan = optimize([vessel("V1"), vessel("V2", lat=25.5, lon=54.6)], [target()])
    assert {r.vessel_id for r in plan.routes} == {"V1", "V2"}
    idle = [r for r in plan.routes if not r.assigned_target_ids]
    assert len(idle) == 1
    assert idle[0].estimated_distance_km == 0.0


def test_capacity_is_respected_and_extra_target_is_reported():
    vessels = [vessel(capacity=200.0)]
    targets = [target("T1", volume=150.0), target("T2", lat=25.7, lon=54.6, volume=150.0)]
    plan = optimize(vessels, targets)
    assert plan.status == "feasible", plan.message
    served = [t for r in plan.routes for t in r.assigned_target_ids]
    assert len(served) == 1
    assert "unserved: none" not in plan.message
    assert check_plan(plan, tuple(vessels), tuple(targets)) == []


def test_two_vessels_split_two_big_targets():
    # 14 h: V1 needs about 3.7 h out, 5 h of cleanup and 3.7 h back to port
    vessels = [vessel("V1", capacity=200.0, hours=14.0), vessel("V2", lat=25.9, lon=54.2, capacity=200.0, hours=14.0)]
    targets = [target("T1", volume=150.0), target("T2", lat=26.0, lon=54.0, volume=150.0)]
    plan = optimize(vessels, targets)
    served = sorted(t for r in plan.routes for t in r.assigned_target_ids)
    assert served == ["T1", "T2"]
    assert all(len(r.assigned_target_ids) == 1 for r in plan.routes)
    assert check_plan(plan, tuple(vessels), tuple(targets)) == []


def test_target_bigger_than_every_tank_is_unserved():
    plan = optimize([vessel(capacity=200.0)], [target(volume=500.0)])
    assert plan.status == "feasible", plan.message
    assert all(not r.assigned_target_ids for r in plan.routes)
    assert "T1" in plan.message


def test_no_targets_is_fine():
    plan = optimize([vessel()], [])
    assert plan.status == "feasible"
    assert len(plan.routes) == 1


def test_demo_scenario_serves_everything_and_passes_rule_check():
    _, vessels, targets = load_scenario("optimization/examples/scenario_demo_easy.json")
    plan = optimize(vessels, targets)
    assert plan.status == "feasible", plan.message
    served = sorted(t for r in plan.routes for t in r.assigned_target_ids)
    assert served == ["T1", "T2", "T3"]
    assert check_plan(plan, vessels, targets) == []
    assert "straight-line" in plan.message  # the plan must say its distances are not validated
