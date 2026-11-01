"""Unit tests for tests/contract_checks.py.

All inputs are small synthetic fixtures written for these tests.
They are not real detections, drift results or routes.
Run from the repo root: python -m unittest discover -s tests -v
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from shared.schemas import (
    DetectionOutput,
    DriftOutput,
    EnvironmentalData,
    GeoCoordinate,
    OptimizationOutput,
    ResponseTarget,
    TimedPosition,
    Vessel,
    VesselRoute,
)
from contract_checks import (
    GULF_REGION,
    check_coordinate,
    check_in_region,
    check_detection,
    check_drift,
    check_environment,
    check_optimization,
    check_target,
    check_vessel,
)

UTC = timezone.utc
T0 = datetime(2026, 11, 2, 6, 0, tzinfo=UTC)
# Synthetic point offshore Abu Dhabi (latitude, longitude).
OFFSHORE_AD = GeoCoordinate(24.60, 54.20)


def make_drift(hours=(0, 6, 12), duration=12.0):
    positions = tuple(
        TimedPosition(T0 + timedelta(hours=h), GeoCoordinate(24.60 + 0.01 * h, 54.20 + 0.01 * h))
        for h in hours
    )
    return DriftOutput("synthetic-drift-1", OFFSHORE_AD, positions, duration)


class CoordinateTests(unittest.TestCase):
    def test_valid_gulf_point(self):
        self.assertEqual(check_coordinate(OFFSHORE_AD), [])

    def test_swapped_lat_lon_is_flagged_with_region(self):
        problems = check_in_region(GeoCoordinate(54.20, 24.60), GULF_REGION)
        self.assertTrue(any("swapped" in p for p in problems))

    def test_region_check_is_optional(self):
        # A valid point outside the Gulf passes global validation.
        outside = GeoCoordinate(54.20, 24.60)
        self.assertEqual(check_coordinate(outside), [])
        self.assertEqual(check_drift(make_drift()), [])

    def test_point_inside_region(self):
        self.assertEqual(check_in_region(OFFSHORE_AD, GULF_REGION), [])

    def test_out_of_range_latitude(self):
        self.assertTrue(check_coordinate(GeoCoordinate(120.0, 54.0)))

    def test_nan_rejected(self):
        self.assertTrue(check_coordinate(GeoCoordinate(float("nan"), 54.0)))

    def test_pixel_values_rejected(self):
        # Row/column pixel indices must never be used as coordinates.
        self.assertTrue(check_coordinate(GeoCoordinate(512.0, 256.0)))


class DetectionTests(unittest.TestCase):
    def test_missing_georeferencing_is_allowed(self):
        out = DetectionOutput("img-001", Path("masks/img-001.png"), None, 0.9)
        self.assertEqual(check_detection(out), [])

    def test_empty_coordinate_tuple_flagged(self):
        out = DetectionOutput("img-001", Path("masks/img-001.png"), (), 0.9)
        self.assertTrue(check_detection(out))

    def test_confidence_out_of_range(self):
        out = DetectionOutput("img-001", Path("masks/img-001.png"), (OFFSHORE_AD,), 1.4)
        self.assertTrue(check_detection(out))


class EnvironmentTests(unittest.TestCase):
    def test_valid_window(self):
        env = EnvironmentalData(Path("wind.nc"), Path("cur.nc"), T0, T0 + timedelta(hours=24))
        self.assertEqual(check_environment(env), [])

    def test_naive_time_flagged(self):
        env = EnvironmentalData(Path("wind.nc"), Path("cur.nc"), datetime(2026, 11, 2), T0 + timedelta(hours=24))
        self.assertTrue(any("UTC" in p for p in check_environment(env)))

    def test_dubai_time_flagged(self):
        dubai = timezone(timedelta(hours=4))
        env = EnvironmentalData(Path("w"), Path("c"), T0.astimezone(dubai), T0 + timedelta(hours=1))
        self.assertTrue(check_environment(env))

    def test_none_timestamp_does_not_crash(self):
        env = EnvironmentalData(Path("w"), Path("c"), None, T0)
        self.assertTrue(any("datetime" in p for p in check_environment(env)))

    def test_string_timestamp_does_not_crash(self):
        env = EnvironmentalData(Path("w"), Path("c"), "2026-11-02T06:00:00Z", T0)
        self.assertTrue(check_environment(env))

    def test_reversed_window(self):
        env = EnvironmentalData(Path("w"), Path("c"), T0 + timedelta(hours=1), T0)
        self.assertTrue(check_environment(env))


class DriftTests(unittest.TestCase):
    def test_valid_drift(self):
        self.assertEqual(check_drift(make_drift()), [])

    def test_unordered_timestamps(self):
        self.assertTrue(any("increasing" in p for p in check_drift(make_drift(hours=(0, 12, 6)))))

    def test_duration_mismatch(self):
        self.assertTrue(check_drift(make_drift(duration=24.0)))

    def test_none_timestamp_in_drift_does_not_crash(self):
        d = make_drift()
        bad = (TimedPosition(None, OFFSHORE_AD),) + d.positions[1:]
        out = DriftOutput(d.simulation_id, d.initial_location, bad, d.duration_hours)
        self.assertTrue(any("datetime" in p for p in check_drift(out)))

    def test_single_position(self):
        self.assertTrue(check_drift(make_drift(hours=(0,), duration=1.0)))


class FleetTests(unittest.TestCase):
    def test_valid_vessel_and_target(self):
        self.assertEqual(check_vessel(Vessel("v1", OFFSHORE_AD, 6.0, 200.0, 12.0)), [])
        self.assertEqual(check_target(ResponseTarget("t1", OFFSHORE_AD, 50.0)), [])

    def test_zero_speed(self):
        self.assertTrue(check_vessel(Vessel("v1", OFFSHORE_AD, 0.0, 200.0, 12.0)))

    def test_negative_volume(self):
        self.assertTrue(check_target(ResponseTarget("t1", OFFSHORE_AD, -5.0)))


class OptimizationTests(unittest.TestCase):
    def setUp(self):
        self.vessels = [Vessel("v1", OFFSHORE_AD, 6.0, 200.0, 12.0), Vessel("v2", OFFSHORE_AD, 5.0, 150.0, 8.0)]
        self.targets = [ResponseTarget("t1", GeoCoordinate(24.7, 54.3), 40.0),
                        ResponseTarget("t2", GeoCoordinate(24.8, 54.4), 30.0)]

    def route(self, vid, tids, hours=2.0):
        coords = (OFFSHORE_AD,) + tuple(t.location for t in self.targets if t.target_id in tids)
        return VesselRoute(vid, tuple(tids), coords, 25.0, hours)

    def test_valid_plan(self):
        out = OptimizationOutput((self.route("v1", ["t1"]), self.route("v2", ["t2"])), "optimal")
        self.assertEqual(check_optimization(out, self.vessels, self.targets), [])

    def test_target_assigned_twice(self):
        out = OptimizationOutput((self.route("v1", ["t1"]), self.route("v2", ["t1"])), "feasible")
        self.assertTrue(check_optimization(out, self.vessels, self.targets))

    def test_unknown_vessel(self):
        out = OptimizationOutput((self.route("ghost", ["t1"]),), "optimal")
        self.assertTrue(check_optimization(out, self.vessels, self.targets))

    def test_exceeds_available_hours(self):
        out = OptimizationOutput((self.route("v2", ["t1"], hours=9.0),), "feasible")
        self.assertTrue(check_optimization(out, self.vessels, self.targets))

    def test_nan_travel_hours(self):
        out = OptimizationOutput((self.route("v1", ["t1"], hours=float("nan")),), "feasible")
        self.assertTrue(any("finite" in p for p in check_optimization(out, self.vessels, self.targets)))

    def test_infinite_travel_hours(self):
        out = OptimizationOutput((self.route("v1", ["t1"], hours=float("inf")),), "feasible")
        self.assertTrue(any("finite" in p for p in check_optimization(out, self.vessels, self.targets)))

    def test_negative_travel_hours(self):
        out = OptimizationOutput((self.route("v1", ["t1"], hours=-1.0),), "feasible")
        self.assertTrue(check_optimization(out, self.vessels, self.targets))

    def test_negative_distance(self):
        r = self.route("v1", ["t1"])
        bad = VesselRoute(r.vessel_id, r.assigned_target_ids, r.coordinates, -5.0, r.estimated_travel_hours)
        self.assertTrue(check_optimization(OptimizationOutput((bad,), "feasible"), self.vessels, self.targets))

    def test_partial_coverage_allowed_by_default(self):
        out = OptimizationOutput((self.route("v1", ["t1"]),), "feasible")
        self.assertEqual(check_optimization(out, self.vessels, self.targets), [])

    def test_full_coverage_flags_missing_target(self):
        out = OptimizationOutput((self.route("v1", ["t1"]),), "feasible")
        problems = check_optimization(out, self.vessels, self.targets, require_full_coverage=True)
        self.assertTrue(any("t2" in p for p in problems))

    def test_full_coverage_passes_when_all_assigned(self):
        out = OptimizationOutput((self.route("v1", ["t1"]), self.route("v2", ["t2"])), "optimal")
        self.assertEqual(check_optimization(out, self.vessels, self.targets, require_full_coverage=True), [])

    def test_infeasible_needs_message_and_no_routes(self):
        self.assertTrue(check_optimization(OptimizationOutput((), "infeasible"), self.vessels, self.targets))
        ok = OptimizationOutput((), "infeasible", "Fleet capacity below total oil volume")
        self.assertEqual(check_optimization(ok, self.vessels, self.targets), [])


if __name__ == "__main__":
    unittest.main()
