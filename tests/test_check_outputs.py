"""Tests for tests/check_outputs.py.

Every file here is a tiny synthetic fixture written into a temporary folder. None of
it is a real detection, drift or routing result.
Run from the repo root: python -m unittest discover -s tests -v
"""

import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from check_outputs import check_outputs, check_sites, main
from contract_checks import GULF_REGION

RELEASE = "2026-10-20T06:00:00Z"


def _feature(geometry_type, coordinates, **properties):
    return {"type": "Feature", "geometry": {"type": geometry_type, "coordinates": coordinates},
            "properties": properties}


def _collection(*features):
    return {"type": "FeatureCollection", "features": list(features)}


def valid_outputs():
    """A complete, contract-following set of files (synthetic, northern UAE coast)."""
    particles = {
        h: _feature("MultiPoint", [[55.65 + 0.01 * h, 25.85 - 0.002 * h], [55.66 + 0.01 * h, 25.86 - 0.002 * h]],
                    hours=h, timestamp=f"2026-10-20T{6 + h:02d}:00:00Z" if h < 18 else "2026-10-21T06:00:00Z",
                    kind="particles")
        for h in (0, 6, 12, 24)
    }
    return {
        "detection/metrics.json": {"dice": 0.7, "iou": 0.55, "precision": 0.72, "recall": 0.68,
                                   "split": "val", "synthetic": True},
        "detection/scene1_mask.png": b"png",
        "detection/scene1_image.png": b"png",
        "drift/drift.geojson": _collection(*particles.values()),
        "drift/meta.json": {
            "simulation_id": "synthetic-run", "synthetic": True,
            "initial_location": {"latitude": 25.85, "longitude": 55.65},
            "positions": [{"timestamp": RELEASE, "coordinate": {"latitude": 25.85, "longitude": 55.65}},
                          {"timestamp": "2026-10-21T06:00:00Z", "coordinate": {"latitude": 25.80, "longitude": 55.90}}],
            "duration_hours": 24,
        },
        "routing/summary.json": {"status": "feasible", "message": "synthetic test", "synthetic": True},
        "routing/routes.geojson": _collection(
            _feature("LineString", [[56.05, 25.97], [55.77, 25.83]], vessel_id="V1", assigned_target_ids=["T1"],
                     estimated_distance_km=30.0, estimated_travel_hours=1.5,
                     speed_m_per_s=6.0, capacity_m3=100.0, available_hours=10.0)),
        "routing/targets.geojson": _collection(
            _feature("Point", [55.77, 25.83], target_id="T1", oil_volume_m3=40.0, source_hours=12),
            _feature("Point", [55.78, 25.84], target_id="T2", oil_volume_m3=20.0, source_hours=12)),
    }


class CheckOutputsTests(unittest.TestCase):
    def run_check(self, files, region=None, expected_release=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, content in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(content, bytes):
                    path.write_bytes(content)
                else:
                    path.write_text(json.dumps(content), encoding="utf-8")
            return check_outputs(root, region, expected_release)

    def problems(self, files, region=None):
        return [f.text for f in self.run_check(files, region) if f.level == "problem"]

    def notes(self, files):
        return [f.text for f in self.run_check(files) if f.level == "note"]

    def assert_problem(self, files, fragment, region=None):
        found = self.problems(files, region)
        self.assertTrue(any(fragment in p for p in found), f"expected {fragment!r} in {found}")

    # --- whole set

    def test_valid_set_has_no_problems(self):
        self.assertEqual(self.problems(valid_outputs()), [])

    def test_valid_set_passes_gulf_region(self):
        self.assertEqual(self.problems(valid_outputs(), GULF_REGION), [])

    def test_empty_folder_is_not_a_problem(self):
        self.assertEqual(self.problems({}), [])

    def test_main_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([tmp]), 0)
            (Path(tmp) / "routing").mkdir()
            (Path(tmp) / "routing" / "summary.json").write_text('{"status": "done"}')
            self.assertEqual(main([tmp]), 1)
            self.assertEqual(main([str(Path(tmp) / "missing")]), 1)

    # --- detection

    def test_nested_metrics_from_evaluate_py(self):
        files = valid_outputs()
        files["detection/metrics.json"] = {"epoch": 12, "threshold": 0.5,
                                           "metrics": {"dice": 0.7, "iou": 0.55, "precision": 0.72, "recall": 0.68}}
        self.assert_problem(files, "nested under 'metrics'")

    def test_nested_metrics_from_report_py(self):
        files = valid_outputs()
        files["detection/metrics.json"] = {"micro": {"dice": 0.7, "iou": 0.55, "precision": 0.72, "recall": 0.68}}
        self.assert_problem(files, "nested under 'micro'")

    def test_metric_out_of_range(self):
        files = valid_outputs()
        files["detection/metrics.json"]["dice"] = 78
        self.assert_problem(files, "dice must be a number in [0, 1]")

    def test_missing_mask(self):
        files = valid_outputs()
        del files["detection/scene1_mask.png"]
        self.assert_problem(files, "no predicted mask")

    def test_mask_without_scene_is_a_note(self):
        files = valid_outputs()
        del files["detection/scene1_image.png"]
        self.assertTrue(any("without the radar scene" in n for n in self.notes(files)))

    def test_spill_polygon_validated_as_detection_output(self):
        files = valid_outputs()
        ring = [[55.6, 25.8], [55.7, 25.8], [55.7, 25.9], [55.6, 25.8]]
        files["detection/spill.geojson"] = _collection(_feature("Polygon", [ring], image_id="scene1", confidence=1.4))
        self.assert_problem(files, "confidence")

    def test_bad_spill_coordinate_reported_once(self):
        files = valid_outputs()
        ring = [[55.6, 125.8], [55.7, 25.8], [55.7, 25.9], [55.6, 125.8]]
        files["detection/spill.geojson"] = _collection(_feature("Polygon", [ring], image_id="scene1"))
        self.assertEqual(len([p for p in self.problems(files) if "latitude" in p]), 1)

    def test_malformed_geometry_does_not_crash(self):
        files = valid_outputs()
        files["detection/spill.geojson"] = _collection(_feature("Polygon", [5], image_id="scene1"))
        files["drift/drift.geojson"]["features"][0]["geometry"]["coordinates"] = 7
        self.assert_problem(files, "must be [longitude, latitude] numbers")

    def test_geometry_that_is_not_an_object(self):
        for bad in ([55.65, 25.85], "Point", 5):
            with self.subTest(geometry=bad):
                files = valid_outputs()
                files["drift/drift.geojson"]["features"][0]["geometry"] = bad
                files["routing/routes.geojson"]["features"][0]["geometry"] = bad
                self.assert_problem(files, "drift.geojson feature 0: geometry must be a GeoJSON object")
                self.assert_problem(files, "routes.geojson feature 0: geometry must be a GeoJSON object")

    # --- drift

    def test_drift_missing_hours(self):
        files = valid_outputs()
        files["drift/drift.geojson"]["features"][0]["properties"].pop("hours")
        self.assert_problem(files, "'hours'")

    def test_drift_naive_timestamp(self):
        files = valid_outputs()
        files["drift/drift.geojson"]["features"][1]["properties"]["timestamp"] = "2026-10-20T12:00:00"
        self.assert_problem(files, "timezone")

    def test_drift_hours_do_not_match_timestamp(self):
        files = valid_outputs()
        # Dubai local time written as if it were UTC: 4 hours off.
        files["drift/drift.geojson"]["features"][1]["properties"]["timestamp"] = "2026-10-20T16:00:00Z"
        self.assert_problem(files, "after the release time")

    def test_drift_meta_runs_contract_checks(self):
        files = valid_outputs()
        files["drift/meta.json"]["positions"].reverse()
        self.assert_problem(files, "strictly increasing")

    def test_release_is_reported(self):
        self.assertTrue(any("release: 2026-10-20T06:00:00Z at 25.85, 55.65" in n for n in self.notes(valid_outputs())))

    def test_release_matches_agreed_time(self):
        agreed = datetime(2026, 10, 20, 6, tzinfo=timezone.utc)
        self.assertEqual([f for f in self.run_check(valid_outputs(), expected_release=agreed)
                          if f.level == "problem"], [])

    def test_release_differs_from_agreed_time(self):
        agreed = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
        found = [f.text for f in self.run_check(valid_outputs(), expected_release=agreed) if f.level == "problem"]
        self.assertTrue(any("not the agreed 2026-10-20T12:00:00Z" in p for p in found), found)

    def test_release_flag_on_command_line(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            for name, content in valid_outputs().items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content) if isinstance(content, bytes) else path.write_text(json.dumps(content))
            self.assertEqual(main([tmp, "--release", "2026-10-20T06:00:00Z"]), 0)
            self.assertEqual(main([tmp, "--release", "2026-10-20T12:00:00Z"]), 1)
            self.assertEqual(main([tmp, "--release", "20 Oct"]), 2)

    def test_unlabelled_drift_gets_a_note(self):
        files = valid_outputs()
        files["drift/meta.json"].pop("synthetic")
        self.assertTrue(any("not labelled synthetic" in n for n in self.notes(files)))

    def test_swapped_geojson_order_caught_with_region(self):
        files = valid_outputs()
        files["drift/drift.geojson"]["features"][0]["geometry"]["coordinates"][0] = [25.85, 55.65]
        self.assertEqual(self.problems(files), [])  # still a valid point on Earth
        self.assert_problem(files, "swapped", GULF_REGION)

    # --- routing

    def test_invalid_status(self):
        files = valid_outputs()
        files["routing/summary.json"]["status"] = "solved"
        self.assert_problem(files, "status must be one of")

    def test_status_that_is_not_text(self):
        for bad in (["feasible"], {"value": "feasible"}, 1):
            with self.subTest(status=bad):
                files = valid_outputs()
                files["routing/summary.json"]["status"] = bad
                self.assert_problem(files, "status must be one of")

    def test_route_to_unknown_target(self):
        files = valid_outputs()
        files["routing/routes.geojson"]["features"][0]["properties"]["assigned_target_ids"] = ["T9"]
        self.assert_problem(files, "unknown target T9")

    def test_partial_vessel_fields(self):
        files = valid_outputs()
        files["routing/routes.geojson"]["features"][0]["properties"].pop("capacity_m3")
        self.assert_problem(files, "all of speed_m_per_s")

    def test_text_vessel_value_does_not_crash(self):
        files = valid_outputs()
        files["routing/routes.geojson"]["features"][0]["properties"]["available_hours"] = "10"
        self.assert_problem(files, "available_hours 10 must be positive")

    def test_travel_hours_over_availability(self):
        files = valid_outputs()
        files["routing/routes.geojson"]["features"][0]["properties"]["estimated_travel_hours"] = 12.0
        self.assert_problem(files, "exceeds available_hours")

    def test_targets_from_hour_missing_in_drift(self):
        files = valid_outputs()
        for f in files["routing/targets.geojson"]["features"]:
            f["properties"]["source_hours"] = 18
        self.assert_problem(files, "forecast hour 18")

    def test_targets_from_several_forecast_hours(self):
        files = valid_outputs()
        files["routing/targets.geojson"]["features"][1]["properties"]["source_hours"] = 24
        self.assert_problem(files, "one forecast time")

    def test_response_time_note_when_cleanup_adds_time(self):
        files = valid_outputs()
        files["routing/routes.geojson"]["features"][0]["properties"]["finish_hours"] = 4.0
        self.assertTrue(any("largest 'finish_hours' is 4.00 h" in n for n in self.notes(files)))

    def test_unserved_targets_note(self):
        files = valid_outputs()
        files["routing/summary.json"]["unserved_target_ids"] = ["T2"]
        self.assertTrue(any("not served (T2)" in n for n in self.notes(files)))


def site_outputs(*site_ids: str, simulation_ids: dict | None = None) -> dict:
    """valid_outputs() as per-site folders sites/<id>/{drift,routing}/; routing carries the drift's scenario_id."""
    files, base = {}, valid_outputs()
    for site_id in site_ids:
        sim = (simulation_ids or {}).get(site_id, f"synthetic-run-{site_id}")
        for name, content in base.items():
            if name.startswith(("drift/", "routing/")):
                files[f"sites/{site_id}/{name}"] = json.loads(json.dumps(content))
        files[f"sites/{site_id}/drift/meta.json"]["simulation_id"] = sim
        files[f"sites/{site_id}/routing/summary.json"]["scenario_id"] = f"{sim}@dispatch6h"
        files[f"sites/{site_id}/routing/comparison.json"] = {"scenario_id": f"{sim}@dispatch6h", "synthetic": True}
    return files


class CheckSitesTests(unittest.TestCase):
    def run_sites(self, files):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, content in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(content), encoding="utf-8")
            return check_sites(root, GULF_REGION)

    def problems(self, files):
        return [f"{f.section}: {f.text}" for f in self.run_sites(files) if f.level == "problem"]

    def test_valid_sites_have_no_problems_and_are_reported_per_site(self):
        findings = self.run_sites(site_outputs("S1", "S2"))
        self.assertEqual([f.text for f in findings if f.level == "problem"], [])
        sections = {f.section for f in findings}
        self.assertTrue({"S1 drift", "S1 routing", "S1 files", "S2 drift", "S2 routing", "S2 files"} <= sections)

    def test_no_site_folders_is_a_problem(self):
        self.assertTrue(any("no site folders" in p for p in self.problems({})))

    def test_each_site_runs_the_existing_checks(self):
        files = site_outputs("S1", "S2")
        files["sites/S2/routing/summary.json"]["status"] = "done"  # not an OptimizationOutput status
        found = self.problems(files)
        self.assertTrue(any(p.startswith("S2 routing") for p in found), found)
        self.assertFalse(any(p.startswith("S1") for p in found), found)

    def test_plan_made_for_another_forecast_is_a_problem(self):
        files = site_outputs("S1")
        files["sites/S1/routing/comparison.json"]["scenario_id"] = "synthetic-run-S2@dispatch6h"
        found = self.problems(files)
        self.assertTrue(any("comparison.json: scenario_id" in p and "another forecast" in p for p in found), found)

    def test_scenario_id_may_extend_the_simulation_id(self):
        files = site_outputs("S1")
        files["sites/S1/routing/comparison.json"]["scenario_id"] = "synthetic-run-S1"  # exact match also fine
        self.assertEqual(self.problems(files), [])

    def test_a_similar_prefix_is_not_a_match(self):
        files = site_outputs("S1")
        files["sites/S1/routing/summary.json"]["scenario_id"] = "synthetic-run-S10@dispatch6h"
        self.assertTrue(any("summary.json: scenario_id" in p for p in self.problems(files)))

    def test_marker_within_1_km_of_the_release_point(self):
        files = site_outputs("S1")
        files["spills.geojson"] = _collection(_feature("Point", [55.655, 25.85], spill_id="S1"))  # ~0.5 km east
        self.assertEqual(self.problems(files), [])

    def test_marker_more_than_1_km_away_is_a_problem(self):
        files = site_outputs("S1")
        files["spills.geojson"] = _collection(_feature("Point", [55.70, 25.85], spill_id="S1"))  # ~5 km east
        self.assertTrue(any("km from marker 'S1'" in p for p in self.problems(files)))

    def test_site_without_a_marker_is_a_problem(self):
        files = site_outputs("S1")
        files["spills.geojson"] = _collection(_feature("Point", [55.65, 25.85], spill_id="S9"))
        self.assertTrue(any("no marker 'S1'" in p for p in self.problems(files)))

    def test_site_without_initial_location_is_a_problem(self):
        files = site_outputs("S1")
        del files["sites/S1/drift/meta.json"]["initial_location"]
        self.assertTrue(any("no valid initial_location" in p for p in self.problems(files)))

    def test_main_with_sites(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as printed:
            for name, content in site_outputs("S1").items():
                path = Path(tmp) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(content), encoding="utf-8")
            self.assertEqual(main([tmp, "--sites"]), 0)
            self.assertIn("S1 DRIFT: OK", printed.getvalue())
            self.assertEqual(main([tmp]), 0)  # without --sites the single folders are checked (absent: notes)

    def test_real_openoil_run_is_announced_with_its_label(self):
        files = site_outputs("S1")
        files["sites/S1/drift/meta.json"]["model"] = "OpenDrift 1.14.11 OpenOil"
        notes = [f.text for f in self.run_sites(files) if f.section == "S1 drift"]
        self.assertTrue(any("Real forecast, simulated release" in n for n in notes), notes)

    def test_release_flag_applies_to_every_site(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as printed:
            for name, content in site_outputs("S1", "S2").items():
                path = Path(tmp) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(content), encoding="utf-8")
            self.assertEqual(main([tmp, "--sites", "--release", RELEASE]), 0)  # both sites start at RELEASE
            self.assertIn(f"agreed release: {RELEASE}; per site", printed.getvalue())
            self.assertEqual(main([tmp, "--sites", "--release", "2026-10-23T12:00:00Z"]), 1)
            output = printed.getvalue()
            for site in ("S1", "S2"):
                self.assertIn(f"{site} DRIFT: 1 problem(s)", output)
            self.assertEqual(output.count("not the agreed 2026-10-23T12:00:00Z"), 2)


if __name__ == "__main__":
    unittest.main()
