"""Tests for optimization scenario generation and marine routing helpers."""

from datetime import datetime, timezone
import tempfile
import unittest
from pathlib import Path

from shared.schemas import DriftOutput, GeoCoordinate, ResponseTarget, TimedPosition, Vessel
from optimization.scenario import (
    GULF_DEPOTS,
    build_distance_matrix,
    build_time_matrix,
    compute_travel_time_hours,
    create_constrained_triage_scenario,
    create_gulf_standard_scenario,
    create_gulf_wide_scenario,
    create_rak_standard_scenario,
    create_smoke_test_scenario,
    export_scenario_to_json,
    haversine_distance_km,
    load_scenario_from_json,
    trajectory_to_targets,
)


class TestOptimizationScenarios(unittest.TestCase):
    def test_haversine_distance(self):
        mina_zayed = GULF_DEPOTS["mina_zayed_abu_dhabi"]
        jebel_ali = GULF_DEPOTS["jebel_ali_dubai"]
        dist = haversine_distance_km(mina_zayed, jebel_ali)
        self.assertAlmostEqual(dist, 87.78, delta=1.0)

    def test_travel_time_hours(self):
        # 10 m/s is 36 km/h. For 72 km, travel time is 2 hours.
        travel_time = compute_travel_time_hours(distance_km=72.0, speed_m_per_s=10.0)
        self.assertAlmostEqual(travel_time, 2.0, delta=1e-3)

    def test_scenario_generation_types(self):
        vessels, targets = create_rak_standard_scenario()
        self.assertIsInstance(vessels, tuple)
        self.assertIsInstance(targets, tuple)
        self.assertEqual(len(vessels), 3)
        self.assertEqual(len(targets), 10)

        # Alias compatibility
        v_alias, t_alias = create_gulf_standard_scenario()
        self.assertEqual(vessels, v_alias)
        self.assertEqual(targets, t_alias)

        for v in vessels:
            self.assertIsInstance(v, Vessel)
            self.assertGreater(v.speed_m_per_s, 0)
            self.assertGreater(v.capacity_m3, 0)
            self.assertGreater(v.available_hours, 0)

        for t in targets:
            self.assertIsInstance(t, ResponseTarget)
            self.assertGreater(t.oil_volume_m3, 0)

    def test_gulf_wide_scenario(self):
        vessels, targets = create_gulf_wide_scenario()
        self.assertEqual(len(vessels), 3)
        self.assertEqual(len(targets), 4)

    def test_json_roundtrip(self):
        vessels, targets = create_smoke_test_scenario()
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test_scenario.json"
            export_scenario_to_json(vessels, targets, file_path, name="test")
            self.assertTrue(file_path.exists())

            loaded_vessels, loaded_targets = load_scenario_from_json(file_path)
            self.assertEqual(loaded_vessels, vessels)
            self.assertEqual(loaded_targets, targets)

    def test_matrices_generation(self):
        coords = [
            GULF_DEPOTS["port_saqr_rak"],
            GULF_DEPOTS["hamriyah_sharjah"],
            GULF_DEPOTS["jebel_ali_dubai"],
        ]
        dist_mat = build_distance_matrix(coords)
        self.assertEqual(len(dist_mat), 3)
        self.assertEqual(dist_mat[0][0], 0.0)
        self.assertEqual(dist_mat[0][1], dist_mat[1][0])

        time_mat = build_time_matrix(coords, speed_m_per_s=10.0)
        self.assertEqual(len(time_mat), 3)
        self.assertEqual(time_mat[0][0], 0.0)

    def test_trajectory_to_targets(self):
        initial = GeoCoordinate(latitude=25.0, longitude=54.0)
        t0 = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
        t6 = datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)
        t12 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)

        # Simulation with moving particles: 1 patch at t0, 1 at t6, and 3 spread patches at t12
        positions = (
            TimedPosition(timestamp=t0, coordinate=GeoCoordinate(latitude=25.0, longitude=54.0)),
            TimedPosition(timestamp=t6, coordinate=GeoCoordinate(latitude=25.1, longitude=54.1)),
            TimedPosition(timestamp=t12, coordinate=GeoCoordinate(latitude=25.20, longitude=54.20)),
            TimedPosition(timestamp=t12, coordinate=GeoCoordinate(latitude=25.22, longitude=54.23)),
            TimedPosition(timestamp=t12, coordinate=GeoCoordinate(latitude=25.24, longitude=54.21)),
        )
        drift = DriftOutput(
            simulation_id="SIM-101",
            initial_location=initial,
            positions=positions,
            duration_hours=12.0,
        )

        # Default: takes patches at the latest forecast timestamp (t12)
        targets = trajectory_to_targets(drift, total_volume_m3=150.0, max_targets=3)
        self.assertEqual(len(targets), 3)
        total_vol = sum(t.oil_volume_m3 for t in targets)
        self.assertAlmostEqual(total_vol, 150.0, delta=1.0)
        # All targets must be at the t12 coordinates, not t0 or t6
        for t in targets:
            self.assertGreaterEqual(t.location.latitude, 25.19)

        # Explicit forecast_time selection at t6
        targets_t6 = trajectory_to_targets(drift, total_volume_m3=100.0, forecast_time=t6)
        self.assertEqual(len(targets_t6), 1)
        self.assertAlmostEqual(targets_t6[0].oil_volume_m3, 100.0)
        self.assertEqual(targets_t6[0].location.latitude, 25.1)


if __name__ == "__main__":
    unittest.main()
