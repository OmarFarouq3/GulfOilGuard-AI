"""Phase 5 tests: what the solver aims for, team scenario formats, and the dashboard files.

Run from the repository root:
    python -m pytest tests/test_optimization_phase5.py

Tests that need OR-Tools are skipped automatically if it is not installed.
All of them use straight-line distances, so they never depend on local data files.
"""

import json

import pytest

from optimization.checks import check_plan
from optimization.config import RoutingConfig
from optimization.dashboard_export import export_for_dashboard
from optimization.evaluate_routes import evaluate_routes, format_comparison
from optimization.scenario_io import load_scenario, scenario_is_synthetic
from optimization.sea_distance import StraightLineDistance
from shared.schemas import GeoCoordinate, OptimizationOutput, ResponseTarget, Vessel, VesselRoute


def vessel(vessel_id="V1", lat=25.4, lon=55.0, speed=5.0, capacity=500.0, hours=20.0):
    return Vessel(vessel_id, GeoCoordinate(lat, lon), speed, capacity, hours)


def target(target_id="T1", lat=25.8, lon=54.5, volume=60.0):
    return ResponseTarget(target_id, GeoCoordinate(lat, lon), volume)


def optimize(vessels, targets, config=RoutingConfig()):
    pytest.importorskip("ortools")
    from optimization.routing_model import solve_routes

    return solve_routes(
        tuple(vessels), tuple(targets), config, distance_provider=StraightLineDistance()
    )


# ---- what the solver aims for (needs OR-Tools) -------------------------------


def test_when_only_one_target_fits_the_bigger_oil_patch_wins():
    small_near = target("SMALL", lat=25.45, lon=55.0, volume=30.0)
    big_far = target("BIG", lat=25.7, lon=55.0, volume=90.0)  # farther, but three times the oil
    v = vessel(capacity=100.0)  # room for one of them only
    plan = optimize([v], [small_near, big_far])
    assert plan.routes[0].assigned_target_ids == ("BIG",)
    assert check_plan(plan, (v,), (small_near, big_far)) == []


def test_work_is_shared_so_the_response_ends_sooner():
    # Two patches close to each other, far from base. One vessel could do both with the
    # least sailing, but two vessels finish hours earlier, and that is worth more.
    a = target("A", lat=25.85, lon=55.0, volume=60.0)  # 2 h of cleanup each
    b = target("B", lat=25.86, lon=55.01, volume=60.0)
    v1, v2 = vessel("V1"), vessel("V2", lon=55.001)
    plan = optimize([v1, v2], [a, b])
    assert all(len(r.assigned_target_ids) == 1 for r in plan.routes), plan.routes

    distance_only = optimize([v1, v2], [a, b], RoutingConfig(response_hour_cost_km=0))
    assert sorted(len(r.assigned_target_ids) for r in distance_only.routes) == [0, 2]


def test_config_rejects_negative_weights():
    with pytest.raises(ValueError):
        RoutingConfig(response_hour_cost_km=-1)
    with pytest.raises(ValueError):
        RoutingConfig(drop_penalty_km_per_m3=-1)


# ---- both team scenario formats load -----------------------------------------


def test_nested_location_format_with_scenario_name(tmp_path):
    path = tmp_path / "nested.json"
    path.write_text(json.dumps({
        "scenario_name": "smoke_test",
        "vessels": [{"vessel_id": "V1", "location": {"latitude": 25.9, "longitude": 56.0},
                     "speed_m_per_s": 7.2, "capacity_m3": 200.0, "available_hours": 12.0}],
        "targets": [{"target_id": "T1", "location": {"latitude": 25.92, "longitude": 55.95},
                     "oil_volume_m3": 25.0}],
        "summary": {"num_vessels": 1},
    }))
    scenario_id, vessels, targets = load_scenario(path)
    assert scenario_id == "smoke_test"
    assert vessels[0].location == GeoCoordinate(25.9, 56.0)
    assert targets[0].oil_volume_m3 == 25.0
    assert scenario_is_synthetic(path)  # says nothing, so it is treated as made up


def test_flat_latitude_longitude_format(tmp_path):
    path = tmp_path / "flat.json"
    path.write_text(json.dumps({
        "scenario_id": "S1", "synthetic": True,
        "vessels": [{"vessel_id": "S1-V1", "latitude": 24.52, "longitude": 54.37,
                     "speed_m_per_s": 5.0, "capacity_m3": 200, "available_hours": 12}],
        "targets": [{"target_id": "S1-T1", "latitude": 24.92, "longitude": 53.55, "oil_volume_m3": 120}],
        "sensitive_sites": [{"name": "intake", "latitude": 24.77, "longitude": 54.70}],
    }))
    scenario_id, vessels, targets = load_scenario(path)
    assert scenario_id == "S1"
    assert vessels[0].location == GeoCoordinate(24.52, 54.37)
    assert targets[0].location == GeoCoordinate(24.92, 53.55)
    assert scenario_is_synthetic(path)


def test_only_an_explicit_false_means_real_data(tmp_path):
    path = tmp_path / "real.json"
    path.write_text(json.dumps({"synthetic": False, "vessels": [], "targets": []}))
    assert not scenario_is_synthetic(path)


# ---- the comparison reports oil and response time ----------------------------


def test_evaluate_routes_oil_and_response_time():
    here = GeoCoordinate(25, 55)
    targets = (target("T1", volume=60.0), target("T2", volume=30.0))  # 2 h and 1 h of cleanup
    ours = OptimizationOutput(
        routes=(VesselRoute("V1", ("T1",), (here, here), 10.0, 1.0),
                VesselRoute("V2", ("T2",), (here, here), 10.0, 1.0)),
        status="feasible",
    )
    theirs = OptimizationOutput(routes=(VesselRoute("V1", ("T1",), (here, here), 5.0, 0.5),), status="feasible")
    m = evaluate_routes(ours, theirs, targets)
    assert m["total_oil_m3"] == 90.0
    assert m["optimized_oil_recovered_m3"] == 90.0 and m["baseline_oil_recovered_m3"] == 60.0
    assert m["oil_recovered_change_percent"] == pytest.approx(50.0)
    assert m["optimized_response_hours"] == pytest.approx(3.0)  # 1 h sailing + 2 h cleanup
    assert m["baseline_response_hours"] == pytest.approx(2.5)
    assert "Oil recovered" in format_comparison(m)
    assert "Oil recovered" not in format_comparison(evaluate_routes(ours, theirs))


# ---- the dashboard files ------------------------------------------------------


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_dashboard_files_follow_the_dashboard_contract(tmp_path):
    v1, v2 = vessel("V1", capacity=200.0), vessel("V2", lat=26.0, lon=54.0)
    t1, t2 = target("T1", volume=60.0), target("T2", lat=25.6, lon=54.8, volume=30.0)
    plan = OptimizationOutput(
        routes=(
            VesselRoute("V1", ("T2", "T1"), (v1.location, t2.location, t1.location), 80.0, 1.5),
            VesselRoute("V2", (), (v2.location,), 0.0, 0.0),
        ),
        status="feasible",
        message="hello",
    )
    written = export_for_dashboard(plan, (v1, v2), (t1, t2), tmp_path, scenario_id="demo")
    assert sorted(p.name for p in written) == ["routes.geojson", "summary.json", "targets.geojson"]

    routes = _read(tmp_path / "routes.geojson")
    assert routes["type"] == "FeatureCollection"
    assert len(routes["features"]) == 1  # the idle vessel is left out
    feature = routes["features"][0]
    assert feature["geometry"]["type"] == "LineString"
    assert feature["geometry"]["coordinates"] == [[55.0, 25.4], [54.8, 25.6], [54.5, 25.8]]  # [lon, lat]
    props = feature["properties"]
    assert props["vessel_id"] == "V1"
    assert props["assigned_target_ids"] == ["T2", "T1"]
    assert props["estimated_distance_km"] == 80.0 and props["estimated_travel_hours"] == 1.5
    assert (props["speed_m_per_s"], props["capacity_m3"], props["available_hours"]) == (5.0, 200.0, 20.0)
    assert props["oil_collected_m3"] == 90.0
    assert props["cleanup_hours"] == pytest.approx(3.0)
    assert props["finish_hours"] == pytest.approx(4.5)
    assert "sea_path" not in props  # no sea provider given

    summary = _read(tmp_path / "summary.json")
    assert summary["status"] == "feasible" and summary["message"] == "hello"
    assert summary["synthetic"] is True
    assert summary["idle_vessel_ids"] == ["V2"]
    assert summary["unserved_target_ids"] == []

    points = _read(tmp_path / "targets.geojson")["features"]
    assert [p["properties"]["target_id"] for p in points] == ["T1", "T2"]
    assert points[0]["geometry"] == {"type": "Point", "coordinates": [54.5, 25.8]}
    assert points[0]["properties"]["served_by"] == "V1"


def test_a_failed_plan_removes_old_routes(tmp_path):
    v, t = vessel(), target()
    good = OptimizationOutput(
        routes=(VesselRoute("V1", ("T1",), (v.location, t.location), 50.0, 1.0),), status="feasible"
    )
    export_for_dashboard(good, (v,), (t,), tmp_path)
    assert (tmp_path / "routes.geojson").exists()

    failed = OptimizationOutput(routes=(), status="error", message="invalid input: boom")
    export_for_dashboard(failed, (v,), (t,), tmp_path, synthetic=False)
    assert not (tmp_path / "routes.geojson").exists()  # no old routes next to the new status
    summary = _read(tmp_path / "summary.json")
    assert summary["status"] == "error" and summary["synthetic"] is False
    assert summary["unserved_target_ids"] == ["T1"]


def test_a_real_solver_plan_exports_cleanly(tmp_path):
    _, vessels, targets = load_scenario("optimization/examples/scenario_demo_hard.json")
    plan = optimize(vessels, targets)
    export_for_dashboard(plan, vessels, targets, tmp_path)
    features = _read(tmp_path / "routes.geojson")["features"]
    served = [t for f in features for t in f["properties"]["assigned_target_ids"]]
    unserved = _read(tmp_path / "summary.json")["unserved_target_ids"]
    assert sorted(served + unserved) == sorted(t.target_id for t in targets)
    for f in features:
        props = f["properties"]
        assert len(f["geometry"]["coordinates"]) == 1 + len(props["assigned_target_ids"])
        assert props["oil_collected_m3"] <= props["capacity_m3"]
        assert props["finish_hours"] <= props["available_hours"] + 1e-6
