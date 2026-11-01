"""Phase 3 tests: working hours and cleanup time.

Run from the repository root:
    python -m pytest tests/test_optimization_phase3.py

Tests that need OR-Tools are skipped automatically if it is not installed.
All of them use straight-line distances, so they never depend on local data files.
"""

import pytest

from optimization.checks import check_plan
from optimization.config import DEFAULT_CONFIG, RoutingConfig
from optimization.limits import (
    leg_minutes,
    minutes_down,
    minutes_up,
    service_hours,
    service_minutes,
    unserved_reason,
)
from optimization.scenario_io import load_scenario
from optimization.sea_distance import StraightLineDistance
from shared.schemas import (
    GeoCoordinate,
    OptimizationOutput,
    ResponseTarget,
    Vessel,
    VesselRoute,
)


def vessel(vessel_id="V1", lat=25.4, lon=55.0, speed=5.0, capacity=500.0, hours=12.0):
    return Vessel(vessel_id, GeoCoordinate(lat, lon), speed, capacity, hours)


def target(target_id="T1", lat=25.8, lon=54.5, volume=60.0):
    return ResponseTarget(target_id, GeoCoordinate(lat, lon), volume)


def optimize(vessels, targets, config=DEFAULT_CONFIG):
    pytest.importorskip("ortools")
    from optimization.routing_model import solve_routes

    return solve_routes(
        tuple(vessels), tuple(targets), config, distance_provider=StraightLineDistance()
    )


# ---- the rules themselves (no OR-Tools needed) -------------------------------


def test_cleanup_time():
    assert service_hours(60.0, DEFAULT_CONFIG) == pytest.approx(2.0)  # 60 m3 at 30 m3/h
    assert service_minutes(60.0, DEFAULT_CONFIG) == 120
    assert service_minutes(61.0, DEFAULT_CONFIG) == 122  # exactly 122 minutes
    assert service_minutes(61.1, DEFAULT_CONFIG) == 123  # 122.2 minutes, rounded UP


def test_rounding_is_strict():
    assert minutes_up(1.001) == 61
    assert minutes_down(1.999) == 119
    assert leg_minutes(18.0, 5.0) == 60  # 18 km at 18 km/h is exactly one hour
    assert leg_minutes(18.1, 5.0) == 61


def test_config_rejects_a_bad_cleanup_rate():
    with pytest.raises(ValueError):
        RoutingConfig(recovery_rate_m3_per_hour=0.0)


def test_check_plan_catches_too_many_working_hours():
    here = GeoCoordinate(25, 55)
    v = vessel(hours=5.0)
    t = target(volume=120.0)  # 4 h of cleanup
    plan = OptimizationOutput(
        routes=(VesselRoute("V1", ("T1",), (here, here), 100.0, 2.0),),  # 2 h sailing + 4 h = 6 h
        status="feasible",
    )
    text = " | ".join(check_plan(plan, (v,), (t,)))
    assert "works 6.00 h" in text


def test_unserved_reasons():
    v = vessel(capacity=200.0, hours=3.0)
    huge = target(volume=500.0)
    assert "larger than every vessel tank" in unserved_reason(huge, [v], [10.0], DEFAULT_CONFIG)
    slow = target(volume=150.0)  # 5 h of cleanup, but only 3 h available
    assert "enough hours" in unserved_reason(slow, [v], [1.0], DEFAULT_CONFIG)
    ok = target(volume=30.0)
    assert "full or out of hours" in unserved_reason(ok, [v], [1.0], DEFAULT_CONFIG)


# ---- the solver respects the rules (needs OR-Tools) --------------------------


def test_cleanup_time_counts_against_available_hours():
    close = target(lat=25.45, lon=55.0, volume=300.0)  # very close, but 10 h of cleanup
    short = optimize([vessel(hours=8.0)], [close])
    assert short.status == "feasible", short.message
    assert not short.routes[0].assigned_target_ids
    assert "enough hours" in short.message

    long = optimize([vessel(hours=12.0)], [close])
    assert long.routes[0].assigned_target_ids == ("T1",)


def test_sailing_time_counts_against_available_hours():
    far = target(lat=26.8, lon=54.0, volume=30.0)  # about 150 km away: 8+ h of sailing at 18 km/h
    plan = optimize([vessel(hours=6.0)], [far])
    assert not plan.routes[0].assigned_target_ids
    plan = optimize([vessel(hours=12.0)], [far])
    assert plan.routes[0].assigned_target_ids == ("T1",)


def test_hours_allow_only_one_of_two_targets():
    a = target("T1", lat=25.45, lon=55.0, volume=120.0)  # 4 h each
    b = target("T2", lat=25.45, lon=55.05, volume=120.0)
    plan = optimize([vessel(hours=6.0)], [a, b])
    served = [t for r in plan.routes for t in r.assigned_target_ids]
    assert len(served) == 1
    assert check_plan(plan, (vessel(hours=6.0),), (a, b)) == []


def test_each_vessel_uses_its_own_speed():
    slow = vessel("V1", speed=2.0, hours=6.0)  # 7.2 km/h
    fast = vessel("V2", lat=25.4, lon=55.01, speed=10.0, hours=6.0)  # 36 km/h
    far = target(lat=26.0, lon=54.8, volume=30.0)  # about 70 km away: too far for V1 in 6 h
    plan = optimize([slow, fast], [far])
    by_vessel = {r.vessel_id: r.assigned_target_ids for r in plan.routes}
    assert by_vessel["V1"] == ()
    assert by_vessel["V2"] == ("T1",)


def test_plan_message_states_the_assumed_cleanup_rate():
    plan = optimize([vessel()], [target()])
    assert "cleanup rate 30 m3/h (assumed)" in plan.message


def test_a_different_cleanup_rate_changes_what_fits():
    t = target(lat=25.45, lon=55.0, volume=300.0)
    slow_rate = optimize([vessel(hours=8.0)], [t], RoutingConfig(recovery_rate_m3_per_hour=30.0))
    fast_rate = optimize([vessel(hours=8.0)], [t], RoutingConfig(recovery_rate_m3_per_hour=60.0))
    assert not slow_rate.routes[0].assigned_target_ids  # 10 h of cleanup
    assert fast_rate.routes[0].assigned_target_ids == ("T1",)  # 5 h of cleanup


def test_every_plan_passes_the_hours_check_on_both_demo_scenarios():
    for name in ("easy", "hard"):
        _, vessels, targets = load_scenario(f"optimization/examples/scenario_demo_{name}.json")
        plan = optimize(vessels, targets)
        assert plan.status == "feasible", plan.message
        assert check_plan(plan, vessels, targets) == [], name


def test_easy_demo_serves_everything():
    _, vessels, targets = load_scenario("optimization/examples/scenario_demo_easy.json")
    plan = optimize(vessels, targets)
    served = sorted(t for r in plan.routes for t in r.assigned_target_ids)
    assert served == ["T1", "T2", "T3"], plan.message
