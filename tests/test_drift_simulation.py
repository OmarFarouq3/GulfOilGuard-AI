"""Tests for drift/simulate_drift.py and drift/export_outputs.py.

All forcing here is a tiny SYNTHETIC wind/current file written for these tests (constant 0.2 m/s
eastward current, no wind). Nothing below is a real simulation result.
The OpenDrift tests are skipped when OpenDrift is not installed.
Run from the repo root: python -m unittest discover -s tests -v
"""

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from contract_checks import check_drift
from drift.export_outputs import build_drift_geojson, build_meta, convex_hull, write_drift_outputs
from drift.simulate_drift import (
    DriftSettings,
    drift_output_from_run,
    environment_from_files,
    hourly_summary,
    run_oil_drift,
)
from shared.schemas import DriftOutput, EnvironmentalData, GeoCoordinate

HAS_OPENDRIFT = importlib.util.find_spec("opendrift") is not None and importlib.util.find_spec("xarray") is not None
RELEASE = GeoCoordinate(latitude=25.85, longitude=55.65)
START = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
EAST_M_PER_S = 0.2
HOURS = 6


class ConvexHullTests(unittest.TestCase):
    def test_square_with_inner_points(self):
        points = [(0, 0), (2, 0), (2, 2), (0, 2), (1, 1), (0.5, 1.5), (1, 0)]
        hull = convex_hull(points)
        self.assertEqual(set(hull), {(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)})

    def test_counter_clockwise(self):
        hull = convex_hull([(0, 0), (4, 0), (4, 3), (0, 3)])
        area2 = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(hull, hull[1:] + hull[:1]))
        self.assertGreater(area2, 0)

    def test_fewer_than_three_points_are_returned_as_they_are(self):
        self.assertEqual(convex_hull([(1, 1), (1, 1)]), [(1.0, 1.0)])


def _write_forcing(directory: Path, stokes_east: float = 0.0, add_utotal: bool = False) -> EnvironmentalData:
    """Two small files shaped like Joud's cleaned ones: constant eastward current, no wind.

    stokes_east is a constant eastward wave drift; add_utotal adds the provider variable that
    the cleaned file must NOT contain.
    """
    import xarray as xr

    directory.mkdir(parents=True, exist_ok=True)
    times = np.arange(np.datetime64("2026-10-23T00:00"), np.datetime64("2026-10-24T13:00"), np.timedelta64(1, "h"))
    lon = np.arange(55.0, 56.31, 0.1)
    lat = np.arange(25.0, 26.71, 0.1)
    shape = (len(times), len(lat), len(lon))

    def dataset(values: dict[str, float]) -> "xr.Dataset":
        ds = xr.Dataset(
            {name: (("time", "latitude", "longitude"), np.full(shape, value)) for name, value in values.items()},
            coords={"time": times, "latitude": lat, "longitude": lon},
        )
        for name in values:
            ds[name].attrs = {"standard_name": name, "units": "m s-1"}
        ds["latitude"].attrs.update(standard_name="latitude", units="degrees_north")
        ds["longitude"].attrs.update(standard_name="longitude", units="degrees_east")
        ds["time"].attrs.update(standard_name="time")
        return ds

    wind, current = directory / "wind_clean.nc", directory / "currents_clean.nc"
    dataset({"x_wind": 0.0, "y_wind": 0.0}).to_netcdf(wind)
    currents = {
        "x_sea_water_velocity": EAST_M_PER_S, "y_sea_water_velocity": 0.0,
        "sea_surface_wave_stokes_drift_x_velocity": stokes_east, "sea_surface_wave_stokes_drift_y_velocity": 0.0,
    }
    if add_utotal:
        currents["utotal"] = EAST_M_PER_S + stokes_east
    dataset(currents).to_netcdf(current)
    return environment_from_files(wind, current)


@unittest.skipUnless(HAS_OPENDRIFT, "OpenDrift or xarray is not installed")
class DriftRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.environment = _write_forcing(Path(cls._tmp.name))
        cls.settings = DriftSettings(n_particles=60, horizontal_diffusivity_m2_per_s=0.0)
        cls.sim = run_oil_drift(RELEASE, START, cls.environment, HOURS, cls.settings)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_environment_window_comes_from_the_files(self):
        self.assertEqual(self.environment.start_time, datetime(2026, 10, 23, 0, tzinfo=timezone.utc))
        self.assertEqual(self.environment.end_time, datetime(2026, 10, 24, 12, tzinfo=timezone.utc))

    def test_hourly_output_and_particle_arrays(self):
        self.assertEqual(list(self.sim.hours), [float(h) for h in range(HOURS + 1)])
        self.assertEqual(self.sim.lon.shape, (60, HOURS + 1))
        self.assertEqual(self.sim.status_names[0], "active")
        self.assertTrue(self.sim.active(HOURS).all())

    def test_oil_moves_east_with_the_current(self):
        summary = hourly_summary(self.sim)
        expected_km = EAST_M_PER_S * HOURS * 3.6
        self.assertAlmostEqual(summary[-1]["centre_east_km"], expected_km, delta=0.6)
        self.assertAlmostEqual(summary[-1]["centre_north_km"], 0.0, delta=0.6)
        self.assertAlmostEqual(summary[0]["centre_east_km"], 0.0, delta=0.3)

    def test_wave_drift_is_added_once_on_top_of_the_current(self):
        stokes = 0.05
        waves = _write_forcing(Path(self._tmp.name) / "waves", stokes_east=stokes)
        wavy = run_oil_drift(RELEASE, START, waves, HOURS, self.settings)
        east_km = hourly_summary(wavy)[-1]["centre_east_km"]
        self.assertAlmostEqual(east_km, (EAST_M_PER_S + stokes) * HOURS * 3.6, delta=0.6)  # current + wave drift
        self.assertGreater(east_km, hourly_summary(self.sim)[-1]["centre_east_km"] + 0.6)  # more than without waves

    def test_provider_current_file_with_utotal_is_refused(self):
        raw = _write_forcing(Path(self._tmp.name) / "raw", stokes_east=0.05, add_utotal=True)
        with self.assertRaisesRegex(ValueError, "utotal"):
            run_oil_drift(RELEASE, START, raw, HOURS, self.settings)

    def test_released_volume_is_the_requested_one(self):
        self.assertAlmostEqual(self.sim.volume_m3(0), self.settings.release_volume_m3, places=1)

    def test_oil_mass_is_not_created(self):
        self.assertLessEqual(float(self.sim.mass_oil_kg[:, -1].sum()), self.sim.released_mass_kg * 1.0001)

    def test_same_seed_gives_the_same_run(self):
        again = run_oil_drift(RELEASE, START, self.environment, HOURS, self.settings)
        np.testing.assert_allclose(again.lon, self.sim.lon)

    def test_run_outside_the_data_window_is_refused(self):
        with self.assertRaises(ValueError):
            run_oil_drift(RELEASE, START + timedelta(hours=20), self.environment, HOURS, self.settings)

    def test_naive_start_time_is_refused(self):
        with self.assertRaises(ValueError):
            run_oil_drift(RELEASE, datetime(2026, 10, 23, 12), self.environment, HOURS, self.settings)

    def test_centre_path_meets_the_shared_contract(self):
        output = drift_output_from_run(self.sim)
        self.assertIsInstance(output, DriftOutput)
        self.assertEqual(len(output.positions), HOURS + 1)
        self.assertEqual(check_drift(output), [])

    def test_geojson_follows_the_routing_and_dashboard_format(self):
        collection = build_drift_geojson(self.sim)
        particles = [f for f in collection["features"] if f["properties"]["kind"] == "particles"]
        envelopes = [f for f in collection["features"] if f["properties"]["kind"] == "envelope"]
        self.assertEqual([f["properties"]["hours"] for f in particles], list(range(HOURS + 1)))
        self.assertEqual(len(envelopes), HOURS + 1)
        first_ids = particles[0]["properties"]["particle_ids"]
        for feature in particles:
            props = feature["properties"]
            self.assertEqual(feature["geometry"]["type"], "MultiPoint")
            self.assertEqual(props["status"], "active")
            self.assertTrue(props["synthetic"])
            self.assertEqual(props["particle_ids"], first_ids)  # the same particle keeps its id
            self.assertEqual(len(props["particle_ids"]), len(feature["geometry"]["coordinates"]))
            expected = START + timedelta(hours=props["hours"])
            self.assertEqual(props["timestamp"], expected.strftime("%Y-%m-%dT%H:%M:%SZ"))
        ring = envelopes[-1]["geometry"]["coordinates"][0]
        self.assertEqual(ring[0], ring[-1])
        self.assertGreaterEqual(len(ring), 4)
        self.assertAlmostEqual(particles[0]["properties"]["oil_volume_m3"], self.settings.release_volume_m3, places=1)

    def test_meta_has_what_routing_and_the_dashboard_read(self):
        meta = build_meta(self.sim)
        for key in ("simulation_id", "synthetic", "initial_location", "positions", "duration_hours", "start_time",
                    "oil_type", "n_particles", "release_volume_m3", "model", "wind_speed_m_per_s",
                    "wind_from_deg", "current_speed_m_per_s", "current_to_deg"):
            self.assertIn(key, meta)
        self.assertTrue(meta["synthetic"])
        self.assertEqual(meta["n_particles"], 60)
        self.assertEqual(meta["release_volume_m3"], self.settings.release_volume_m3)
        self.assertEqual(meta["start_time"], "2026-10-23T12:00:00Z")
        # OpenDrift wobbles the current by about 0.05 m/s (its data-uncertainty setting), which makes the
        # mean speed a little higher than the 0.2 m/s in the file.
        self.assertAlmostEqual(meta["current_speed_m_per_s"], EAST_M_PER_S, delta=0.03)
        self.assertAlmostEqual(meta["current_to_deg"], 90.0, delta=1.0)  # flowing east
        self.assertTrue(0 <= meta["wind_from_deg"] <= 360)

    def test_files_are_written_and_readable(self):
        with tempfile.TemporaryDirectory() as out:
            geojson_path, meta_path = write_drift_outputs(self.sim, Path(out) / "drift")
            self.assertEqual(json.loads(geojson_path.read_text())["type"], "FeatureCollection")
            self.assertEqual(json.loads(meta_path.read_text())["n_particles"], 60)


if __name__ == "__main__":
    unittest.main()
