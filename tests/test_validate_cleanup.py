"""Tests for the cleanup validator itself (Nihal): every check must catch the error it is for,
pass a correct plan, and report a bad input as FAIL instead of crashing.

Run from the repository root:
    python -m pytest tests/test_validate_cleanup.py

The files are small made-up drift runs and plans written to a temporary folder, so the tests
never depend on anyone's outputs. No OR-Tools needed.
"""

import json
from math import cos, radians

import pytest

from optimization.validate_cleanup import Report, check_comparison, check_drift, check_provenance, check_routes
from optimization.validate_sites import compare_sites, summary_markdown
from shared.schemas import GeoCoordinate, Vessel

KM_PER_DEG = 111.2
RELEASE = (25.85, 55.65)
SIM_ID = "openoil-25.85N-55.65E-20261023T1200Z"


def at(north_km=0.0, east_km=0.0, lat=RELEASE[0], lon=RELEASE[1]):
    return GeoCoordinate(lat + north_km / KM_PER_DEG, lon + east_km / (KM_PER_DEG * cos(radians(lat))))


def failed(r: Report) -> list[str]:
    return [row["text"] for row in r.rows if row["level"] == "FAIL"]


def warned(r: Report) -> list[str]:
    return [row["text"] for row in r.rows if row["level"] == "WARN"]


# --- drift files ---------------------------------------------------------------------------------


def write_drift(folder, lat=RELEASE[0], lon=RELEASE[1], sim_id=SIM_ID, spread=1.0, stranded_from=None, meta_extra=None):
    """Ten particles released at (lat, lon), drifting east 0.5 km/h (particle i also i*0.1 km north
    per hour times `spread`), 30 m3 each, 1 % of the oil weathering away per hour. From hour
    `stranded_from` the first two particles are stranded on the coast."""
    folder.mkdir(parents=True, exist_ok=True)
    features, summary = [], []
    for h in range(25):
        oil = 30.0 * (1 - 0.01 * h)
        points = {"active": [], "stranded": []}
        for i in range(10):
            p = at(north_km=i * 0.1 * h * spread, east_km=0.5 * h, lat=lat, lon=lon)
            status = "stranded" if stranded_from is not None and h >= stranded_from and i < 2 else "active"
            points[status].append((str(i), [p.longitude, p.latitude]))
        for status, pts in points.items():
            if pts:
                features.append({"type": "Feature",
                                 "geometry": {"type": "MultiPoint", "coordinates": [c for _, c in pts]},
                                 "properties": {"hours": h, "status": status, "particle_ids": [i for i, _ in pts],
                                                "oil_volume_m3": oil * len(pts),
                                                "timestamp": f"2026-10-{23 + (12 + h) // 24}T{(12 + h) % 24:02d}:00:00Z"}})
        summary.append({"hours": h, "oil_afloat_m3": oil * len(points["active"]),
                        "stranded_or_other": len(points["stranded"]), "mean_water_fraction": 0.0})
    meta = {"simulation_id": sim_id, "synthetic": True, "initial_location": {"latitude": lat, "longitude": lon},
            "start_time": "2026-10-23T12:00:00Z", "n_particles": 10, "release_volume_m3": 300.0,
            "summary_by_hour": summary, **(meta_extra or {})}
    (folder / "drift.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    (folder / "meta.json").write_text(json.dumps(meta))
    return folder


def test_a_correct_drift_run_passes(tmp_path):
    r = Report()
    check_drift(write_drift(tmp_path / "d"), r, GeoCoordinate(*RELEASE))
    assert failed(r) == []
    assert any("no oil stranded" in row["text"] for row in r.rows)


def test_the_release_point_must_be_the_sites(tmp_path):
    r = Report()
    check_drift(write_drift(tmp_path / "d"), r, GeoCoordinate(25.70, 55.40))
    assert any("is the site's" in t for t in failed(r))


def test_a_simulation_id_naming_another_point_fails(tmp_path):
    r = Report()
    check_drift(write_drift(tmp_path / "d", sim_id="openoil-25.70N-55.40E-20261023T1200Z"), r)
    assert any("names the release point" in t for t in failed(r))


def test_particles_moved_away_from_the_release_point_fail():
    r = Report()
    meta = {"simulation_id": SIM_ID, "initial_location": {"latitude": 25.85, "longitude": 55.65},
            "start_time": "2026-10-23T12:00:00Z"}
    check_provenance(meta, [(at(north_km=-16.7, east_km=-25.0), 300.0)], None, r)  # released 30 km away
    assert any("particles at 0 h" in t for t in failed(r))


def test_a_missing_start_time_is_a_warning_not_a_failure():
    r = Report()
    meta = {"simulation_id": SIM_ID, "initial_location": {"latitude": 25.85, "longitude": 55.65}}
    check_provenance(meta, [(at(), 300.0)], None, r)
    assert failed(r) == []
    assert any("no start_time" in t for t in warned(r))


def test_oil_reaching_the_coast_is_reported(tmp_path):
    r = Report()
    info = check_drift(write_drift(tmp_path / "d", stranded_from=11), r)
    assert failed(r) == []
    assert any("oil reaches the coast: 2 particles" in t and "the first at 11 h" in t for t in warned(r))
    assert info["stranded_by_hour"][24.0]["particles"] == 2


def test_stranded_particles_must_match_meta(tmp_path):
    folder = write_drift(tmp_path / "d", stranded_from=11)
    meta = json.loads((folder / "meta.json").read_text())
    meta["summary_by_hour"][24]["stranded_or_other"] = 5
    (folder / "meta.json").write_text(json.dumps(meta))
    r = Report()
    check_drift(folder, r)
    assert any("stranded_or_other" in t for t in failed(r))


# --- one site is not another site's run moved ----------------------------------------------------


def test_a_translated_copy_of_another_site_is_caught(tmp_path):
    sites = {"S1": write_drift(tmp_path / "S1"), "S2": write_drift(tmp_path / "S2", lat=25.70, lon=55.40)}
    (pair,) = compare_sites(sites)
    assert pair["copy"]
    assert "**NO**" in summary_markdown([], [pair])


def test_a_copy_cut_short_is_still_caught(tmp_path):
    short = write_drift(tmp_path / "S2", lat=25.70, lon=55.40)
    collection = json.loads((short / "drift.geojson").read_text())
    collection["features"] = [f for f in collection["features"] if f["properties"]["hours"] <= 12]
    (short / "drift.geojson").write_text(json.dumps(collection))
    (pair,) = compare_sites({"S1": write_drift(tmp_path / "S1"), "S2": short})
    assert pair["copy"] and pair["until_hours"] == 12


def test_sites_that_drift_differently_are_not_flagged(tmp_path):
    sites = {"S1": write_drift(tmp_path / "S1"), "S2": write_drift(tmp_path / "S2", lat=25.70, lon=55.40, spread=3.0)}
    (pair,) = compare_sites(sites)
    assert not pair["copy"] and not pair["similar"]
    assert "yes." in summary_markdown([], [pair])


def test_sites_with_no_particle_in_common_are_reported_not_compared(tmp_path):
    other = write_drift(tmp_path / "S2", lat=25.70, lon=55.40)
    collection = json.loads((other / "drift.geojson").read_text())
    for f in collection["features"]:
        f["properties"]["particle_ids"] = [f"x{i}" for i in f["properties"]["particle_ids"]]
    (other / "drift.geojson").write_text(json.dumps(collection))
    (pair,) = compare_sites({"S1": write_drift(tmp_path / "S1"), "S2": other})
    assert not pair["comparable"]
    assert "Not compared" in summary_markdown([], [pair])


# --- routes --------------------------------------------------------------------------------------

DISPATCH = 6.0
VESSEL = Vessel("V1", at(east_km=-20.0), 10000 / 3600, 100.0, 10.0)  # 10 km/h, 100 m3, 10 h shift


def write_plan(folder, assigned=("T01", "T02"), meets=(7.0, 8.0), unserved=("T03",), **route_changes):
    """V1 sails 20 km to T01 (10 m3), 0 km on to T02 (5 m3) and 20 km back: 4 h sailing, 0.5 h cleanup."""
    folder.mkdir(parents=True, exist_ok=True)
    places = {"T01": at(), "T02": at(), "T03": at(east_km=5.0)}
    oil = {"T01": 10.0, "T02": 5.0, "T03": 0.4}
    meet = dict(zip(assigned, meets))
    targets = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [p.longitude, p.latitude]},
                "properties": {"target_id": t, "oil_volume_m3": oil[t], "meet_hours": meet.get(t),
                               "position_hours": meet.get(t, DISPATCH), "served_by": "V1" if t in meet else None}}
               for t, p in places.items()]
    port = [VESSEL.location.longitude, VESSEL.location.latitude]
    stops = [[places[t].longitude, places[t].latitude] for t in assigned if t in places]
    km = 40.0
    route = {"vessel_id": "V1", "assigned_target_ids": list(assigned), "estimated_distance_km": km,
             "estimated_travel_hours": 4.0, "oil_collected_m3": sum(oil.get(t, 0) for t in assigned),
             "cleanup_hours": sum(oil.get(t, 0) for t in assigned) / 30, "capacity_m3": 100.0,
             "finish_hours": 4.0 + sum(oil.get(t, 0) for t in assigned) / 30, **route_changes}
    routes = [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": [port, *stops, port]},
               "properties": route}]
    (folder / "targets.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": targets}))
    (folder / "routes.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": routes}))
    (folder / "summary.json").write_text(json.dumps({"status": "feasible", "unserved_target_ids": list(unserved),
                                                     "idle_vessel_ids": [], "message": ""}))
    return folder


def drift_info():
    return {"water_fraction_by_hour": {}, "tank_basis": "pure oil", "dispatch_hours": DISPATCH,
            "afloat_by_hour": {0.0: 300.0, 24.0: 250.0}}


def route_check(folder, vessels=(VESSEL,)):
    r = Report()
    out = check_routes(folder, vessels, drift_info(), r)
    return r, out


def test_a_correct_route_passes(tmp_path):
    r, out = route_check(write_plan(tmp_path / "p"))
    assert failed(r) == []
    assert out["routes"][0]["finish_hours"] == pytest.approx(4.5)


def test_finish_hours_must_be_sailing_plus_cleanup(tmp_path):
    r, _ = route_check(write_plan(tmp_path / "p", finish_hours=5.0))
    assert any("finish_hours 5.00 h = sailing" in t for t in failed(r))


def test_sailing_time_must_be_distance_over_speed(tmp_path):
    r, _ = route_check(write_plan(tmp_path / "p", estimated_travel_hours=3.0, finish_hours=3.5))
    assert any("sailing 3.00 h = 40.0 km" in t for t in failed(r))


def test_a_vessel_missing_from_the_fleet_fails_without_crashing(tmp_path):
    other = Vessel("V9", VESSEL.location, VESSEL.speed_m_per_s, 100.0, 10.0)
    r, _ = route_check(write_plan(tmp_path / "p"), vessels=(other,))
    assert any("not in the fleet file" in t for t in failed(r))


def test_a_stop_missing_from_the_targets_fails_without_crashing(tmp_path):
    r, _ = route_check(write_plan(tmp_path / "p", assigned=("T01", "T99"), meets=(7.0, 8.0)))
    assert any("T99" in t and "not in targets.geojson" in t for t in failed(r))


def test_every_target_must_be_in_a_route_or_listed_unserved(tmp_path):
    r, _ = route_check(write_plan(tmp_path / "p", unserved=()))
    assert any("in a route or listed unserved" in t for t in failed(r))


def test_meetings_must_come_after_the_previous_stop_is_cleaned(tmp_path):
    # T01 (10 m3) is cleaned 7.00 to 7.33 h, so T02 cannot be met at 7.1 h
    r, _ = route_check(write_plan(tmp_path / "p", meets=(7.0, 7.1)))
    assert any("meetings in order" in t and "before T01 is cleaned" in t for t in failed(r))


def test_a_meeting_before_dispatch_fails(tmp_path):
    r, _ = route_check(write_plan(tmp_path / "p", meets=(5.0, 8.0)))
    assert any("first meeting before dispatch" in t for t in failed(r))


# --- comparison ----------------------------------------------------------------------------------


def plan_numbers(oil, km, sailing, finish, targets):
    rows = [{"targets": list(targets), "_exact": {"oil": oil, "km": km, "sailing": sailing, "finish": finish}}] if targets else []
    return {"routes": rows, "total_oil_m3": 10.0}


def metrics(**changes):
    m = {"total_oil_m3": 10.0, "optimized_oil_recovered_m3": 10.0, "baseline_oil_recovered_m3": 10.0,
         "optimized_distance_km": 20.0, "baseline_distance_km": 30.0, "distance_change_percent": -100 / 3,
         "optimized_targets_covered": 1.0, "baseline_targets_covered": 1.0,
         "optimized_distance_km_per_target": 20.0, "baseline_distance_km_per_target": 30.0}
    return {"metrics": m | changes}


def test_comparison_metrics_are_recalculated_not_trusted():
    r = Report()
    check_comparison(metrics(distance_change_percent=-50.0), plan_numbers(10, 20, 1, 1.5, ["T01"]),
                     plan_numbers(10, 30, 1.5, 2, ["T01"]), r)
    assert any("distance_change_percent: file -50.000, recalculated -33.333" in t for t in failed(r))


@pytest.mark.parametrize("missing", [None, float("nan")])
def test_a_plan_with_no_targets_has_distance_per_target_not_applicable(missing):
    r = Report()
    check_comparison(metrics(baseline_oil_recovered_m3=0.0, baseline_distance_km=0.0, distance_change_percent=0.0,
                             baseline_targets_covered=0.0, baseline_distance_km_per_target=missing),
                     plan_numbers(10, 20, 1, 1.5, ["T01"]), plan_numbers(0, 0, 0, 0, []), r)
    assert failed(r) == []
    assert any("n/a (no targets covered)" in row["text"] for row in r.rows)


def test_an_optimized_plan_cleaning_less_oil_than_the_baseline_is_flagged():
    r = Report()
    check_comparison(metrics(optimized_oil_recovered_m3=6.0, total_oil_m3=10.0),
                     plan_numbers(6, 20, 1, 1.5, ["T01"]), plan_numbers(10, 30, 1.5, 2, ["T01"]), r)
    assert any("LESS" in t for t in warned(r))
