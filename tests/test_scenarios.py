"""Check that every demo scenario is labelled synthetic and follows the shared contracts.

Run from the repo root: python -m unittest discover -s tests -v
"""

import unittest

from contract_checks import GULF_REGION, check_in_region, check_drift, check_target, check_vessel
from scenario_loader import load_all


class ScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenarios = load_all()

    def test_scenarios_found(self):
        self.assertGreaterEqual(len(self.scenarios), 1)

    def test_ids_unique(self):
        ids = [s.scenario_id for s in self.scenarios]
        self.assertEqual(len(ids), len(set(ids)))

    def test_all_labelled_synthetic(self):
        for s in self.scenarios:
            with self.subTest(s.scenario_id):
                self.assertTrue(s.synthetic)
                self.assertIn("synthetic", s.note.lower())

    def test_contracts(self):
        for s in self.scenarios:
            with self.subTest(s.scenario_id):
                # Demo scenarios are in the Gulf, so the optional regional check is applied.
                problems = check_in_region(s.release_location, GULF_REGION, "release_location")
                problems += check_drift(s.drift, region=GULF_REGION)
                for t in s.targets:
                    problems += check_target(t, region=GULF_REGION)
                for v in s.vessels:
                    problems += check_vessel(v, region=GULF_REGION)
                for site in s.sensitive_sites:
                    problems += check_in_region(site.location, GULF_REGION, site.name)
                self.assertEqual(problems, [])

    def test_drift_starts_at_release(self):
        for s in self.scenarios:
            with self.subTest(s.scenario_id):
                self.assertEqual(s.drift.positions[0].coordinate, s.release_location)
                self.assertEqual(s.drift.positions[0].timestamp, s.release_time)

    def test_target_volumes_match_estimate(self):
        for s in self.scenarios:
            with self.subTest(s.scenario_id):
                total = sum(t.oil_volume_m3 for t in s.targets)
                self.assertAlmostEqual(total, s.estimated_oil_volume_m3)

    def test_ids_unique_within_scenario(self):
        for s in self.scenarios:
            with self.subTest(s.scenario_id):
                tids = [t.target_id for t in s.targets]
                vids = [v.vessel_id for v in s.vessels]
                self.assertEqual(len(tids), len(set(tids)))
                self.assertEqual(len(vids), len(set(vids)))

    def test_targets_share_one_forecast_time_within_drift(self):
        for s in self.scenarios:
            with self.subTest(s.scenario_id):
                start = s.drift.positions[0].timestamp
                end = s.drift.positions[-1].timestamp
                self.assertTrue(start <= s.targets_forecast_time <= end)
                self.assertIn("same forecast time", s.targets_note)

    def test_capacity_shortfall_must_expect_infeasible(self):
        # Enough capacity is necessary, not sufficient. Only the shortfall case is decidable here.
        for s in self.scenarios:
            with self.subTest(s.scenario_id):
                capacity = sum(v.capacity_m3 for v in s.vessels)
                if capacity < s.estimated_oil_volume_m3:
                    self.assertIn("infeasible", s.expected.lower())
                else:
                    self.assertIn("does not guarantee", s.expected.lower())


if __name__ == "__main__":
    unittest.main()
