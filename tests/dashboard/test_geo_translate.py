"""services.geo translation and services.scenario anchoring of drift and routes to a spill."""

from __future__ import annotations

import copy
import itertools

import pytest

from services import mock_data, scenario
from services.files import iter_positions
from services.geo import offset_deg, translate_coords, translate_features
from services.models import SpillSite
from services.schema import GeoCoordinate

TOL = 1e-5  # coordinates are rounded to 6 decimals


def site(lat: float, lon: float) -> SpillSite:
    return SpillSite("TEST", "Test site (simulated)", GeoCoordinate(lat, lon), True)


def drift_positions(drift) -> list[tuple[float, float]]:
    return [(p[0], p[1]) for h in drift.hours for f in drift.steps[h] for p in iter_positions(f["geometry"]["coordinates"])]


def route_positions(routing) -> list[tuple[float, float]]:
    return ([(c.longitude, c.latitude) for e in routing.routes for c in e.route.coordinates]
            + [(t.location.longitude, t.location.latitude) for t in routing.targets])


def flat(positions: list[tuple[float, float]]) -> list[float]:
    return [float(v) for p in positions for v in p]


def assert_same_shape(before: list, after: list) -> None:
    """Every pairwise difference is unchanged: a pure shift, no rotation or scaling."""
    assert len(before) == len(after)
    sample = list(itertools.islice(itertools.combinations(range(len(before)), 2), 400))
    for i, j in sample:
        for axis in (0, 1):
            assert (after[j][axis] - after[i][axis]) == pytest.approx(before[j][axis] - before[i][axis], abs=2 * TOL)


def test_translate_coords_keeps_extra_dimensions_and_nesting():
    coords = [[[54.0, 24.0, 5.0], [54.5, 24.5]], [[55.0, 25.0]]]
    assert translate_coords(coords, 1.0, -0.5) == [[[53.5, 25.0, 5.0], [54.0, 25.5]], [[54.5, 26.0]]]


def test_translate_features_does_not_mutate_its_input():
    features = mock_data.spill_outline()["features"]
    original = copy.deepcopy(features)
    moved = translate_features(features, 0.5, 0.5)
    moved[0]["properties"]["image_id"] = "changed"
    assert features == original


def test_offset_moves_origin_onto_target():
    dlat, dlon = offset_deg((24.88, 53.98), (25.85, 55.65))
    assert (24.88 + dlat, 53.98 + dlon) == pytest.approx((25.85, 55.65))


@pytest.mark.parametrize("target", [(25.85, 55.65), (26.02, 55.58), (24.0, 52.0)])
def test_drift_is_shifted_to_the_spill_keeping_its_shape(target):
    source = mock_data.drift()
    moved = scenario.selected_drift(site(*target), demo=True)
    start = moved.trajectory.initial_location
    assert (start.latitude, start.longitude) == pytest.approx(target, abs=TOL)
    assert scenario.drift_origin(moved) == pytest.approx(target, abs=TOL)
    assert_same_shape(drift_positions(source), drift_positions(moved))
    assert [p.timestamp for p in moved.trajectory.positions] == [p.timestamp for p in source.trajectory.positions]
    assert moved.meta["initial_location"] == pytest.approx({"latitude": target[0], "longitude": target[1]}, abs=TOL)
    assert moved.synthetic and moved.anchored_to == "TEST"


def test_drift_origin_falls_back_to_the_earliest_step_without_trajectory():
    source = mock_data.drift()
    source.trajectory = None
    origin = scenario.drift_origin(source)
    target = (25.85, 55.65)
    moved = scenario.anchor_drift(source, site(*target), scenario.drift_offset(source, site(*target)))
    assert origin is not None and scenario.drift_origin(moved) == pytest.approx(target, abs=TOL)


def test_routes_move_with_the_drift_keeping_their_shape():
    target = site(25.92, 55.36)
    source = mock_data.routing()
    moved = scenario.selected_routing(target, demo=True)
    assert_same_shape(route_positions(source), route_positions(moved))
    dlat, dlon = scenario.drift_offset(mock_data.drift(), target)
    first = source.targets[0].location
    assert (moved.targets[0].location.latitude, moved.targets[0].location.longitude) == \
        pytest.approx((first.latitude + dlat, first.longitude + dlon), abs=TOL)
    for entry in moved.routes:  # each vessel still starts at its (moved) base
        assert entry.vessel.location == entry.route.coordinates[0]
    assert [e.route.estimated_distance_km for e in moved.routes] == [e.route.estimated_distance_km for e in source.routes]
    assert moved.synthetic and moved.anchored_to == "TEST"


def test_identity_when_already_at_the_spill():
    source = mock_data.drift()
    origin = scenario.drift_origin(source)
    here = site(*origin)
    assert scenario.drift_offset(source, here) == (0.0, 0.0)
    assert flat(drift_positions(scenario.selected_drift(here, demo=True))) == \
        pytest.approx(flat(drift_positions(source)), abs=TOL)
    assert flat(route_positions(scenario.selected_routing(here, demo=True))) == \
        pytest.approx(flat(route_positions(mock_data.routing())), abs=TOL)
    assert scenario.shift_km(source, here) == pytest.approx(0.0, abs=1e-6)


def test_simulated_outline_is_centred_on_the_spill():
    target = site(25.66, 55.42)
    data = scenario.selected_detection(target, None, simulated_accepted=True)
    ring = data.spill["features"][0]["geometry"]["coordinates"][0]
    lat = sum(p[1] for p in ring[:-1]) / (len(ring) - 1)
    lon = sum(p[0] for p in ring[:-1]) / (len(ring) - 1)
    assert (lat, lon) == pytest.approx((25.66, 55.42), abs=0.02)
    assert data.outline_simulated and data.mask_source == "simulated"
    assert all(d.confidence is None for d in data.detections)


def test_no_detection_yet_gives_no_data():
    assert scenario.selected_detection(site(25.0, 55.0), None, simulated_accepted=False) is None
