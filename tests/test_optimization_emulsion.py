"""Emulsion tests: weathered oil takes up water, so the tank and the skimmer handle more than
the pure oil. Tank use and cleanup time are oil / (1 - water fraction); oil recovered stays pure oil.

Run from the repository root:
    python -m pytest tests/test_optimization_emulsion.py

Tests that need OR-Tools are skipped automatically if it is not installed.
All of them use straight-line distances, so they never depend on local data files.
"""

import json
from math import cos, radians

import pytest

from optimization.checks import check_plan
from optimization.config import DriftTargetConfig
from optimization.dashboard_export import export_for_dashboard
from optimization.drift_targets import PatchTrack, build_tracks, load_drift
from optimization.limits import EmulsionTarget, tank_m3
from optimization.moving_targets import nearest_first_moving, sail
from optimization.sea_distance import StraightLineDistance
from shared.schemas import GeoCoordinate, OptimizationOutput, ResponseTarget, Vessel, VesselRoute

KM_PER_DEG = 111.2


def east(km, lat=25.8, lon=55.7):
    """A point `km` east of (lat, lon)."""
    return GeoCoordinate(lat, lon + km / (KM_PER_DEG * cos(radians(lat))))


def write_drift(folder, steps, water=None):
    """One particle per step at `east(km)` holding `oil` m3: steps = {hours: (km, oil)}.
    `water` = {hours: mean_water_fraction} goes into meta.json summary_by_hour."""
    features = [
        {"type": "Feature", "geometry": {"type": "MultiPoint", "coordinates": [[east(km).longitude, east(km).latitude]]},
         "properties": {"hours": h, "particle_ids": [1], "oil_volume_m3": oil}}
        for h, (km, oil) in steps.items()
    ]
    (folder / "drift.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    if water is not None:
        rows = [{"hours": h, "mean_water_fraction": w} for h, w in water.items()]
        (folder / "meta.json").write_text(json.dumps({"summary_by_hour": rows}))
    return folder


def still_track(target_id="T01", oil=50.0, water=0.5, km=10.0):
    """A patch that does not move or weather, with a fixed water fraction."""
    return PatchTrack(target_id, (0.0, 24.0), (east(km), east(km)), (oil, oil), (water, water))


def vessel(capacity=200.0, hours=12.0):
    return Vessel("V1", east(0), 10 / 3.6, capacity, hours)


# ---- reading the water fraction --------------------------------------------------


def test_water_fraction_from_meta_makes_emulsion_targets(tmp_path):
    write_drift(tmp_path, {0: (10, 40.0), 10: (20, 40.0)}, water={0: 0.5, 10: 0.75})
    forecast = load_drift(tmp_path)
    assert forecast.water_fraction == {0: 0.5, 10: 0.75}
    assert any("counted as emulsion" in note for note in forecast.notes)

    (track,) = build_tracks(forecast, 0).tracks
    target = track.target_at(5)  # halfway: water fraction 0.625
    assert isinstance(target, EmulsionTarget)
    assert target.oil_volume_m3 == pytest.approx(40.0)  # oil recovered stays pure oil
    assert target.water_fraction == pytest.approx(0.625)
    assert tank_m3(target) == pytest.approx(40.0 / 0.375)


def test_without_a_full_water_fraction_the_tank_takes_pure_oil_and_says_so(tmp_path):
    write_drift(tmp_path, {0: (10, 40.0), 10: (20, 40.0)}, water={0: 0.5})  # 10 h missing
    forecast = load_drift(tmp_path)
    assert forecast.water_fraction == {}
    assert any("pure oil" in note and "10 h" in note for note in forecast.notes)
    (track,) = build_tracks(forecast, 0).tracks
    assert type(track.target_at(5)) is ResponseTarget and tank_m3(track.target_at(5)) == pytest.approx(40.0)


def test_emulsion_can_be_switched_off(tmp_path):
    write_drift(tmp_path, {0: (10, 40.0)}, water={0: 0.5})
    forecast = load_drift(tmp_path, DriftTargetConfig(count_emulsion=False))
    assert forecast.water_fraction == {}
    assert any("switched off" in note for note in forecast.notes)


def test_a_water_fraction_of_one_or_more_is_refused(tmp_path):
    write_drift(tmp_path, {0: (10, 40.0)}, water={0: 1.0})
    with pytest.raises(ValueError, match="mean_water_fraction"):
        load_drift(tmp_path)


def test_patches_are_split_by_the_fullest_emulsion_not_the_oil_at_dispatch(tmp_path):
    # 80 m3 of oil fits a 100 m3 tank at dispatch, but is 80 / (1 - 0.6) = 200 m3 of emulsion at 10 h
    write_drift(tmp_path, {0: (10, 80.0), 10: (12, 80.0)}, water={0: 0.0, 10: 0.6})
    tracks = build_tracks(load_drift(tmp_path), 0, max_target_m3=100).tracks
    assert [t.target_id for t in tracks] == ["T01-1", "T01-2"]
    assert all(tank_m3(t.target_at(10)) <= 100 + 1e-9 for t in tracks)


# ---- the tank, cleanup time and the checks ------------------------------------------


def test_the_tank_is_filled_with_emulsion_not_pure_oil():
    # 50 m3 of oil at 50 % water is 100 m3 in the tank: fits 100, not 80
    patch = still_track(oil=50.0, water=0.5)
    plan = OptimizationOutput((VesselRoute("V1", ("T01",), (east(0), east(10), east(0))),), "feasible")
    (small,) = sail((vessel(capacity=80.0),), plan, (patch,), 0.0, StraightLineDistance())
    assert small.stops == []
    (big,) = sail((vessel(capacity=100.0),), plan, (patch,), 0.0, StraightLineDistance())
    assert [s.target_id for s in big.stops] == ["T01"] and big.tank == pytest.approx(0.0)


def test_cleanup_time_is_for_the_emulsion():
    # 30 m3 of oil at 50 % water: 60 m3 to skim at 30 m3/h = 2 h, not 1 h
    patch = still_track(oil=30.0, water=0.5)
    plan = OptimizationOutput((VesselRoute("V1", ("T01",), (east(0), east(10), east(0))),), "feasible")
    (voyage,) = sail((vessel(),), plan, (patch,), 0.0, StraightLineDistance())
    (stop,) = voyage.stops
    assert voyage.clock == pytest.approx(stop.meet_hours + 2.0)


def test_check_plan_counts_emulsion_against_capacity():
    target = EmulsionTarget("T01", east(10), 50.0, emulsion_m3=100.0, water_fraction=0.5)
    route = VesselRoute("V1", ("T01",), (east(0), east(10), east(0)), 20.0, 2.0)
    plan = OptimizationOutput((route,), "feasible")
    assert check_plan(plan, (vessel(capacity=100.0),), (target,)) == []
    assert any("over capacity" in v for v in check_plan(plan, (vessel(capacity=80.0),), (target,)))


def test_baseline_and_export_report_oil_and_emulsion(tmp_path):
    patch = still_track(oil=40.0, water=0.6)  # 100 m3 of emulsion
    vessels = (vessel(capacity=150.0),)
    result = nearest_first_moving(vessels, (patch,), 0.0, StraightLineDistance())
    assert check_plan(result.plan, vessels, result.targets) == []

    export_for_dashboard(result.plan, vessels, result.targets, tmp_path)
    (route,) = json.loads((tmp_path / "routes.geojson").read_text())["features"]
    props = route["properties"]
    assert props["oil_collected_m3"] == pytest.approx(40.0)  # recovered: pure oil
    assert props["emulsion_collected_m3"] == pytest.approx(100.0)  # in the tank
    assert props["tank_used_percent"] == pytest.approx(100 / 1.5)
    assert props["cleanup_hours"] == pytest.approx(100 / 30)
    (target,) = json.loads((tmp_path / "targets.geojson").read_text())["features"]
    assert target["properties"]["emulsion_m3"] == pytest.approx(100.0)


def test_the_solver_plans_with_emulsion():
    pytest.importorskip("ortools")
    from optimization.routing_model import solve_routes

    # each patch is 30 m3 of oil but 60 m3 of emulsion: a 100 m3 tank takes one, not three
    targets = tuple(EmulsionTarget(f"T{i}", east(5 * i), 30.0, emulsion_m3=60.0, water_fraction=0.5)
                    for i in range(1, 4))
    vessels = (vessel(capacity=100.0, hours=24.0),)
    plan = solve_routes(vessels, targets, distance_provider=StraightLineDistance())
    assert plan.status == "feasible"
    assert len(plan.routes[0].assigned_target_ids) == 1
    assert check_plan(plan, vessels, targets) == []
