"""Phase 6 tests: drift forecast -> MOVING cleanup targets -> plan, baseline and comparison files.

Run from the repository root:
    python -m pytest tests/test_optimization_phase6.py

Tests that need OR-Tools are skipped automatically if it is not installed.
All of them use straight-line distances, so they never depend on local data files.
"""

import json
from math import cos, radians

import pytest

from optimization.checks import check_plan
from optimization.config import DriftTargetConfig
from optimization.dashboard_export import export_comparison, export_for_dashboard
from optimization.drift_targets import PatchTrack, build_tracks, load_drift, particles_at
from optimization.moving_targets import _intercept, nearest_first_moving, sail
from optimization.sea_distance import StraightLineDistance, haversine_km
from optimization.units import travel_hours
from shared.schemas import GeoCoordinate, OptimizationOutput, Vessel, VesselRoute

KM_PER_DEG = 111.2


def east(km, lat=25.8, lon=55.7):
    """A point `km` east of (lat, lon)."""
    return GeoCoordinate(lat, lon + km / (KM_PER_DEG * cos(radians(lat))))


def feature(hours, points, geometry="MultiPoint", **props):
    coordinates = [[p.longitude, p.latitude] if isinstance(p, GeoCoordinate) else [p[1], p[0]] for p in points]
    if geometry == "Point":
        coordinates = coordinates[0]
    return {
        "type": "Feature",
        "geometry": {"type": geometry, "coordinates": coordinates},
        "properties": {"hours": hours, **props},
    }


def write_drift(folder, features, meta=None):
    (folder / "drift.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    if meta is not None:
        (folder / "meta.json").write_text(json.dumps(meta))
    return folder


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def track(target_id="T01", hours=(0.0, 10.0), km=(10.0, 20.0), volumes=(50.0, 50.0)):
    """A patch drifting east along latitude 25.8."""
    return PatchTrack(target_id, tuple(hours), tuple(east(k) for k in km), tuple(volumes))


def vessel(vessel_id="V1", location=None, speed=10 / 3.6, capacity=200.0, hours=12.0):
    return Vessel(vessel_id, location or east(0), speed, capacity, hours)


# ---- reading the drift files --------------------------------------------------


def test_equal_share_of_the_release_and_stranded_oil_left_out(tmp_path):
    write_drift(tmp_path, [
        feature(0, [(25.85, 55.65)] * 4),
        feature(12, [(25.80, 55.70)] * 3),
        feature(12, [(25.70, 55.90)], geometry="Point", status="stranded"),
        {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}, "properties": {"hours": 12}},
    ], meta={"simulation_id": "sim-1", "release_volume_m3": 100, "synthetic": True})
    forecast = load_drift(tmp_path)

    assert forecast.simulation_id == "sim-1" and forecast.synthetic
    assert sorted(forecast.steps) == [0, 12]
    at_12 = particles_at(forecast, 12)
    assert len(at_12) == 3  # the stranded particle and the envelope are not oil to skim
    assert all(p.volume_m3 == pytest.approx(25.0) for p in at_12)  # 100 m3 / 4 released
    assert at_12[0].location == GeoCoordinate(25.80, 55.70)  # GeoJSON lon, lat read correctly
    assert any("weathering" in note for note in forecast.notes)


def test_feature_volumes_and_particle_ids(tmp_path):
    write_drift(tmp_path, [feature(6, [(25.8, 55.7), (25.81, 55.71)], oil_volume_m3=40, particle_ids=[7, 8])])
    forecast = load_drift(tmp_path)
    particles = particles_at(forecast, 6)
    assert [p.volume_m3 for p in particles] == [20.0, 20.0]
    assert [p.particle_id for p in particles] == ["7", "8"]
    # only the tank basis had to be assumed: no meta.json, so no water fraction for emulsion
    assert len(forecast.notes) == 1 and "counted as pure oil" in forecast.notes[0]
    assert not forecast.synthetic


def test_without_release_volume_the_assumption_is_reported(tmp_path):
    write_drift(tmp_path, [feature(0, [(25.8, 55.7)] * 2)])
    forecast = load_drift(tmp_path, DriftTargetConfig(release_volume_m3=50))
    assert [p.volume_m3 for p in particles_at(forecast, 0)] == [25.0, 25.0]
    assert any("50 m3 assumed" in note for note in forecast.notes)


def test_bad_files_give_clear_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_drift(tmp_path)
    write_drift(tmp_path, [feature("soon", [(25.8, 55.7)])])
    with pytest.raises(ValueError, match="hours"):
        load_drift(tmp_path)
    write_drift(tmp_path, [feature(0, [(25.8, 55.7)] * 2, particle_ids=[1])])
    with pytest.raises(ValueError, match="one id per point"):
        load_drift(tmp_path)
    write_drift(tmp_path, [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []},
                            "properties": {"hours": 0}}])
    with pytest.raises(ValueError, match="no particle"):
        load_drift(tmp_path)


def test_dispatch_must_be_a_forecast_step(tmp_path):
    forecast = load_drift(write_drift(tmp_path, [feature(6, [(25.8, 55.7)]), feature(24, [(25.7, 55.8)])]))
    with pytest.raises(ValueError, match="have 6, 24 h"):
        build_tracks(forecast, 12)


# ---- following the patches ----------------------------------------------------


def test_a_track_moves_in_a_straight_line_between_steps_and_holds_after():
    t = track(volumes=(50.0, 30.0))
    place, volume = t.at(5.0)
    assert haversine_km(place, east(15)) < 0.01 and volume == pytest.approx(40.0)
    assert t.at(-1.0) == (east(10), 50.0)
    assert t.at(99.0) == (east(20), 30.0)  # after the last step: held there


def test_particles_grouped_at_dispatch_are_followed_by_their_ids(tmp_path):
    a, b = east(0), east(1)  # same 0.03 degree cell at dispatch
    write_drift(tmp_path, [
        feature(6, [a, b], oil_volume_m3=20, particle_ids=[1, 2]),
        feature(7, [east(3), east(4)], oil_volume_m3=20, particle_ids=[1, 2]),
        feature(8, [east(6)], oil_volume_m3=8, particle_ids=[1]),  # particle 2 stranded, oil weathered
        feature(8, [east(7)], status="stranded", particle_ids=[2], oil_volume_m3=10),
    ])
    patches = build_tracks(load_drift(tmp_path), 6)
    assert patches.follow == "particle_id"
    (t,) = patches.tracks
    assert t.target_id == "T01" and t.hours == (6, 7, 8)
    assert haversine_km(t.positions[1], east(3.5)) < 0.01  # the centre moved with the oil
    assert t.volumes == (20.0, 20.0, 8.0)
    assert patches.oil_afloat_m3 == 20.0


def test_patch_ids_from_the_drift_module_are_used_as_targets(tmp_path):
    write_drift(tmp_path, [
        feature(0, [east(0)], patch_id="north", oil_volume_m3=30),
        feature(0, [east(30)], patch_id="south", oil_volume_m3=50),
        feature(1, [east(2)], patch_id="north", oil_volume_m3=28),
    ])
    patches = build_tracks(load_drift(tmp_path), 0)
    assert patches.follow == "patch_id"
    by_id = {t.target_id: t for t in patches.tracks}
    assert [t.target_id for t in patches.tracks] == ["south", "north"]  # most oil first
    assert by_id["north"].volumes == (30.0, 28.0)
    assert by_id["south"].volumes == (50.0, 0.0)  # gone at 1 h, held where last seen
    assert by_id["south"].positions[1] == by_id["south"].positions[0]


def test_without_ids_the_patches_are_static_and_said_so(tmp_path):
    write_drift(tmp_path, [feature(0, [east(0)], oil_volume_m3=10), feature(1, [east(5)], oil_volume_m3=10)])
    patches = build_tracks(load_drift(tmp_path), 0)
    assert patches.follow == "static"
    assert patches.tracks[0].hours == (0,)


def test_small_patches_are_counted_and_big_ones_split(tmp_path):
    write_drift(tmp_path, [
        feature(0, [east(0)], oil_volume_m3=250, particle_ids=[1]),
        feature(0, [east(20)], oil_volume_m3=20, particle_ids=[2]),
        feature(0, [east(40)], oil_volume_m3=5, particle_ids=[3]),
    ])
    patches = build_tracks(load_drift(tmp_path), 0, DriftTargetConfig(max_targets=2), max_target_m3=100)
    assert [t.target_id for t in patches.tracks] == ["T01-1", "T01-2", "T01-3", "T02"]
    assert sum(t.volumes[0] for t in patches.tracks[:3]) == pytest.approx(250)
    assert patches.untargeted_m3 == 5


# ---- sailing against moving oil ------------------------------------------------


def test_interception_aims_where_the_patch_will_be():
    # vessel at 0 km, 10 km/h; patch at 10 km moving east at 1 km/h -> meets after 10/9 h
    meet, target, km = _intercept(StraightLineDistance().distances_from(east(0)), track(), 0.0, 10 / 3.6)
    assert meet == pytest.approx(10 / 9, abs=1e-3)
    assert km == pytest.approx(10 + 10 / 9, abs=0.01)
    assert haversine_km(target.location, east(km)) < 0.01


def test_a_patch_gone_before_arrival_is_skipped():
    gone = track("GONE", volumes=(50.0, 0.0), hours=(0.0, 0.5))  # all stranded within half an hour
    stays = track("STAYS", km=(5.0, 5.0))
    plan = OptimizationOutput(
        (VesselRoute("V1", ("GONE", "STAYS"), (east(0), east(10), east(5))),), "feasible"
    )
    (voyage,) = sail((vessel(),), plan, (gone, stays), 0.0, StraightLineDistance())
    assert [s.target_id for s in voyage.stops] == ["STAYS"]


def test_cleaning_drifts_the_vessel_with_the_oil():
    first = track("A", km=(10.0, 20.0), volumes=(30.0, 30.0))  # 1 h of cleaning at 30 m3/h
    plan = OptimizationOutput((VesselRoute("V1", ("A",), (east(0), east(10))),), "feasible")
    (voyage,) = sail((vessel(),), plan, (first,), 0.0, StraightLineDistance())
    (stop,) = voyage.stops
    assert voyage.clock == pytest.approx(stop.meet_hours + 1.0)
    assert haversine_km(voyage.here, first.at(voyage.clock)[0]) < 0.01


def test_vessels_sail_back_to_port_and_keep_hours_for_it():
    # 10 km/h, a still patch 30 km out, 1 h of cleanup: 3 h out + 1 h + 3 h back = 7 h
    still = PatchTrack("T01", (0.0,), (east(30),), (30.0,))
    provider = StraightLineDistance()
    short = nearest_first_moving((vessel(hours=5.0),), (still,), 0.0, provider)  # 4 h gets it there, not back
    assert short.plan.routes[0].assigned_target_ids == ()
    assert "sail back to port" in short.plan.message

    result = nearest_first_moving((vessel(hours=8.0),), (still,), 0.0, provider)
    (route,) = result.plan.routes
    assert route.coordinates[-1] == route.coordinates[0] == east(0)
    assert route.estimated_distance_km == pytest.approx(60.0, abs=0.1)
    assert result.last_cleanup_hours == pytest.approx(4.0, abs=0.01)  # back in port 3 h later
    assert check_plan(result.plan, (vessel(hours=8.0),), result.targets) == []


def test_moving_plans_follow_the_rules_and_export_cleanly(tmp_path):
    pytest.importorskip("ortools")
    from optimization.moving_targets import solve_moving

    tracks = tuple(
        track(f"T{i:02d}", hours=(6.0, 18.0), km=(8.0 + 4 * i, 14.0 + 4 * i), volumes=(30.0, 24.0))
        for i in range(1, 6)
    )
    vessels = (vessel("V1", capacity=100.0), vessel("V2", location=east(40), capacity=100.0))
    provider = StraightLineDistance()
    optimized = solve_moving(vessels, tracks, 6.0, provider)
    baseline = nearest_first_moving(vessels, tracks, 6.0, provider)

    for result in (optimized, baseline):
        assert result.plan.status == "feasible"
        assert check_plan(result.plan, vessels, result.targets) == []
        by_id = {t.target_id: t for t in tracks}
        for target in result.targets:  # every served target is where its patch is at the meeting
            if target.target_id in result.meet_hours:
                place, volume = by_id[target.target_id].at(result.meet_hours[target.target_id])
                assert haversine_km(place, target.location) < 0.01
                assert target.oil_volume_m3 == pytest.approx(volume)
    assert "moving oil" in optimized.plan.message and "round" in optimized.plan.message

    out = tmp_path / "routing"
    export_for_dashboard(optimized.plan, vessels, optimized.targets, out, source_hours=12,
                         target_properties={"T01": {"meet_hours": 7.5}})
    export_for_dashboard(baseline.plan, vessels, baseline.targets, out / "baseline")
    export_comparison(optimized.plan, baseline.plan, vessels, optimized.targets, out,
                      baseline_targets=baseline.targets, details={"drift": {"dispatch_hours": 6}})

    features = {f["properties"]["target_id"]: f["properties"] for f in _read(out / "targets.geojson")["features"]}
    assert features["T01"]["meet_hours"] == 7.5 and features["T01"]["source_hours"] == 12
    assert _read(out / "summary.json")["source_hours"] == 12
    assert _read(out / "baseline" / "summary.json")["message"].startswith("baseline")
    comparison = _read(out / "comparison.json")
    assert comparison["drift"]["dispatch_hours"] == 6
    assert comparison["optimized"]["rule_violations"] == [] and comparison["baseline"]["rule_violations"] == []
    expected = sum(t.oil_volume_m3 for t in baseline.targets if t.target_id in baseline.meet_hours)
    assert comparison["metrics"]["baseline_oil_recovered_m3"] == pytest.approx(expected)


def test_static_patches_need_only_one_round():
    pytest.importorskip("ortools")
    from optimization.moving_targets import solve_moving

    still = PatchTrack("T01", (6.0,), (east(10),), (30.0,))
    result = solve_moving((vessel(),), (still,), 6.0, StraightLineDistance())
    assert result.rounds == 1
    assert result.meet_hours["T01"] == pytest.approx(6.0 + travel_hours(10, 10 / 3.6), abs=1e-3)


def test_a_failed_plan_still_writes_an_honest_comparison(tmp_path):
    v = vessel()
    targets = (track().target_at(0),)
    failed = OptimizationOutput(routes=(), status="error", message="boom")
    export_comparison(failed, failed, (v,), targets, tmp_path)
    comparison = _read(tmp_path / "comparison.json")
    assert comparison["metrics"] is None
    assert "error" in comparison["metrics_error"]
