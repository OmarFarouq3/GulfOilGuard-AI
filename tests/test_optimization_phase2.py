"""Phase 2 tests: navigable-water distances.

Run from the repository root:
    python -m pytest tests/test_optimization_phase2.py

These tests build tiny fake seas in code. They never need the real land file.
"""

import json

import numpy as np
import pytest

from optimization.config import GridRegion
from optimization.sea_distance import StraightLineDistance, haversine_km
from optimization.sea_grid import (
    UNREACHABLE_KM,
    LandMask,
    SeaGridDistance,
    SeaRoutingError,
    find_land_file,
)
from shared.schemas import GeoCoordinate, ResponseTarget, Vessel

# A 1 x 1 degree sea at the equator. 100 x 100 cells of about 1.1 km.
REGION = GridRegion(lat_min=0.0, lat_max=1.0, lon_min=0.0, lon_max=1.0, cell_deg=0.01)


def point(lat, lon):
    return GeoCoordinate(lat, lon)


def rectangle(lon0, lon1, lat0, lat1):
    return [[(lon0, lat0), (lon1, lat0), (lon1, lat1), (lon0, lat1), (lon0, lat0)]]


def open_sea():
    return SeaGridDistance(LandMask(REGION, np.zeros((100, 100), dtype=bool)))


def sea_with_wall():
    """A tall island wall in the middle, from lat 0.1 to lat 0.9."""
    mask = LandMask.from_polygons(REGION, [rectangle(0.45, 0.55, 0.1, 0.9)])
    return SeaGridDistance(mask)


def test_region_shape():
    assert (REGION.rows, REGION.cols) == (100, 100)
    from optimization.config import GULF_REGION

    assert (GULF_REGION.rows, GULF_REGION.cols) == (450, 650)


def test_open_sea_is_close_to_straight_line():
    a, b = point(0.3, 0.2), point(0.7, 0.8)
    sea = open_sea().matrix_km([a, b])[0][1]
    straight = haversine_km(a, b)
    assert 0.99 * straight <= sea <= 1.09 * straight  # a grid is slightly longer, never shorter


def test_matrix_is_symmetric_with_zero_diagonal():
    points = [point(0.3, 0.2), point(0.7, 0.8), point(0.5, 0.5)]
    m = sea_with_wall().matrix_km(points)
    for i in range(3):
        assert m[i][i] == 0.0
        for j in range(3):
            assert m[i][j] == pytest.approx(m[j][i], rel=1e-9)


def test_route_goes_around_an_island():
    a, b = point(0.5, 0.2), point(0.5, 0.8)
    straight = haversine_km(a, b)
    sea = sea_with_wall().matrix_km([a, b])[0][1]
    assert sea > 1.4 * straight  # must go around the wall
    assert sea < 1.9 * straight  # but not absurdly far


def test_path_follows_water_and_matches_distance():
    provider = sea_with_wall()
    a, b = point(0.5, 0.2), point(0.5, 0.8)
    waypoints = provider.path(a, b)
    assert waypoints[0] == a and waypoints[-1] == b
    for wp in waypoints[1:-1]:
        row, col = provider.mask.cell_of(wp)
        assert not provider.mask.land[row, col]
    length = sum(haversine_km(p, q) for p, q in zip(waypoints, waypoints[1:]))
    assert length == pytest.approx(provider.matrix_km([a, b])[0][1], rel=0.03)


def test_diagonal_cannot_squeeze_between_two_touching_land_cells():
    land = np.zeros((10, 10), dtype=bool)
    land[4, 5] = True
    land[5, 4] = True  # the two land cells touch only at a corner
    provider = SeaGridDistance(LandMask(GridRegion(0, 0.1, 0, 0.1, 0.01), land))
    a = provider.mask.center_of(4, 4)
    b = provider.mask.center_of(5, 5)
    d = provider.matrix_km([a, b])[0][1]
    assert d > 4.0  # the direct diagonal would be only about 1.6 km


def test_point_on_land_is_moved_to_water_with_a_warning():
    land = np.zeros((100, 100), dtype=bool)
    land[48:52, 48:52] = True  # a 4 x 4 cell island
    provider = SeaGridDistance(LandMask(REGION, land))
    on_land, far = point(0.5, 0.5), point(0.5, 0.9)
    d = provider.matrix_km([on_land, far], ["V1", "T1"])[0][1]
    assert any("V1" in w and "moved" in w for w in provider.warnings)
    assert d > haversine_km(on_land, far)  # includes the move to the water


def test_point_too_far_from_water_is_an_error():
    provider = SeaGridDistance(LandMask(REGION, np.ones((100, 100), dtype=bool)), max_snap_km=5.0)
    with pytest.raises(SeaRoutingError):
        provider.matrix_km([point(0.5, 0.5), point(0.6, 0.6)])


def test_point_outside_region_is_an_error():
    with pytest.raises(SeaRoutingError, match="outside"):
        open_sea().matrix_km([point(0.5, 0.5), point(2.0, 0.5)])


def test_enclosed_water_is_unreachable():
    land = np.zeros((10, 10), dtype=bool)
    land[3:8, 3:8] = True
    land[4:7, 4:7] = False  # a closed pond in the middle
    provider = SeaGridDistance(LandMask(GridRegion(0, 0.1, 0, 0.1, 0.01), land))
    inside, outside = provider.mask.center_of(5, 5), provider.mask.center_of(1, 1)
    d = provider.matrix_km([inside, outside])[0][1]
    assert d == UNREACHABLE_KM
    assert any("no sea route" in w for w in provider.warnings)


def test_polygon_with_a_hole():
    ring_outer = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8), (0.2, 0.2)]
    ring_hole = [(0.4, 0.4), (0.6, 0.4), (0.6, 0.6), (0.4, 0.6), (0.4, 0.4)]
    mask = LandMask.from_polygons(REGION, [[ring_outer, ring_hole]])
    assert not mask.land[mask.cell_of(point(0.5, 0.5))]  # inside the hole is water
    assert mask.land[mask.cell_of(point(0.3, 0.3))]
    assert not mask.land[mask.cell_of(point(0.1, 0.1))]


def test_rasterized_rectangle_has_about_the_right_area():
    mask = LandMask.from_polygons(REGION, [rectangle(0.45, 0.55, 0.1, 0.9)])
    cells = int(mask.land.sum())
    assert 780 <= cells <= 900  # 10 x 80 cells, plus a little for the outline


def test_geojson_file_is_read_and_cached(tmp_path):
    geo = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [[[[0.45, 0.1], [0.55, 0.1], [0.55, 0.9], [0.45, 0.9], [0.45, 0.1]]]],
                },
            }
        ],
    }
    land_file = tmp_path / "ne_10m_land.geojson"
    land_file.write_text(json.dumps(geo), encoding="utf-8")
    cache = tmp_path / "cache"

    first = LandMask.from_file(REGION, land_file, cache)
    assert list(cache.glob("landmask_*.npy"))
    second = LandMask.from_file(REGION, land_file, cache)
    assert np.array_equal(first.land, second.land)
    assert find_land_file(tmp_path) == land_file


def test_missing_land_file_gives_a_helpful_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="no land file"):
        find_land_file(tmp_path)


def test_solver_uses_sea_distance_around_an_island():
    pytest.importorskip("ortools")
    from optimization.routing_model import solve_routes

    vessel = Vessel("V1", point(0.5, 0.2), 5.0, 200.0, 20.0)  # hours for around the wall and back
    target = ResponseTarget("T1", point(0.5, 0.8), 100.0)
    straight = haversine_km(vessel.location, target.location)

    plan = solve_routes((vessel,), (target,), distance_provider=sea_with_wall())
    assert plan.status == "feasible", plan.message
    assert plan.routes[0].estimated_distance_km > 1.4 * 2 * straight  # there and back
    assert "sea-grid" in plan.message

    flat = solve_routes((vessel,), (target,), distance_provider=StraightLineDistance())
    assert flat.routes[0].estimated_distance_km == pytest.approx(2 * straight, rel=1e-6)


def test_solver_reports_a_point_that_is_outside_the_region():
    pytest.importorskip("ortools")
    from optimization.routing_model import solve_routes

    vessel = Vessel("V1", point(0.5, 0.2), 5.0, 200.0, 12.0)
    target = ResponseTarget("T9", point(5.0, 5.0), 100.0)
    plan = solve_routes((vessel,), (target,), distance_provider=open_sea())
    assert plan.status == "error"
    assert "T9" in plan.message and "outside" in plan.message
