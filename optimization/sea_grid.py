"""Navigable-water distances (Phase 2).

The idea, in simple words: draw the sea as a chess board. Each square is either
land or water. A vessel can only move between neighbouring water squares, so the
shortest path goes AROUND islands and peninsulas instead of across them. We add up
the real length of every step, and that is the distance the solver uses.

Where the land comes from (Natural Earth "land" polygons, free, public domain):
  1. Download the shapefile zip (10m land):
     https://www.naturalearthdata.com/http//www.naturalearthdata.com/download/10m/physical/ne_10m_land.zip
     (all Natural Earth physical data: https://www.naturalearthdata.com/downloads/10m-physical-vectors/)
  2. Unzip it into  <repo>/data/land/  so that  data/land/ne_10m_land.shp  exists.
     Reading .shp files needs the small package `pyshp`:  python -m pip install pyshp
  OR use a GeoJSON copy of the same data, saved as  data/land/ne_10m_land.geojson
  (no extra package needed). Do NOT commit these files; data/ is ignored by Git.

Honest limits (say these in the report):
  - The grid gives a path slightly longer than the true shortest sea path. In open
    water we measured 0 to 9 percent longer. Each end of a leg can also be off by up to
    about one cell (2 km with the default 0.02 degree cell), so very short legs are less
    accurate. A smaller cell_deg in config.py (for example 0.01) is more exact but slower.
  - Narrow channels thinner than a grid cell can be closed by the grid.
  - This is not a validated operational route: it ignores depth, shipping lanes,
    exclusion zones and weather.
"""

import hashlib
import json
import os
from functools import lru_cache
from math import ceil, cos, pi, radians
from pathlib import Path
from typing import Callable, Iterable, Iterator, Sequence

import numpy as np
from PIL import Image, ImageDraw
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from optimization.config import GridRegion, RoutingConfig
from optimization.sea_distance import EARTH_RADIUS_KM, haversine_km
from shared.schemas import GeoCoordinate

KM_PER_DEGREE = EARTH_RADIUS_KM * pi / 180  # about 111.2 km
UNREACHABLE_KM = 100_000.0  # bigger than the drop penalty, so the solver skips such targets
LAND_FILE_NAMES = ("ne_10m_land.shp", "ne_10m_land.geojson", "ne_10m_land.json", "land.geojson")

# A polygon is a list of rings. Each ring is a list of (longitude, latitude).
# The first ring is the outer edge, any other rings are holes.
Polygon = list[list[tuple[float, float]]]


class SeaRoutingError(ValueError):
    """A point cannot be placed on the sea grid (outside the region, or too far from water)."""


# ---------------------------------------------------------------------------
# Reading land polygons
# ---------------------------------------------------------------------------


def _polygons_from_geometry(geometry: dict) -> Iterator[Polygon]:
    kind = geometry.get("type")
    if kind == "Polygon":
        yield [[(p[0], p[1]) for p in ring] for ring in geometry["coordinates"]]
    elif kind == "MultiPolygon":
        for polygon in geometry["coordinates"]:
            yield [[(p[0], p[1]) for p in ring] for ring in polygon]
    elif kind == "GeometryCollection":
        for inner in geometry.get("geometries", []):
            yield from _polygons_from_geometry(inner)


def _polygons_from_geojson(data: dict) -> Iterator[Polygon]:
    kind = data.get("type")
    if kind == "FeatureCollection":
        for feature in data.get("features", []):
            if feature.get("geometry"):
                yield from _polygons_from_geometry(feature["geometry"])
    elif kind == "Feature":
        if data.get("geometry"):
            yield from _polygons_from_geometry(data["geometry"])
    else:
        yield from _polygons_from_geometry(data)


def read_land_polygons(path: str | Path) -> list[Polygon]:
    """Read land polygons from a GeoJSON file or a shapefile (.shp)."""
    path = Path(path)
    if path.suffix.lower() == ".shp":
        try:
            import shapefile  # the package is called pyshp
        except ImportError as exc:
            raise ImportError(
                "reading a .shp file needs pyshp: python -m pip install pyshp "
                "(or use a GeoJSON copy of the land file instead)"
            ) from exc
        polygons: list[Polygon] = []
        with shapefile.Reader(str(path)) as reader:
            for shape in reader.shapes():
                polygons.extend(_polygons_from_geometry(shape.__geo_interface__))
        return polygons
    return list(_polygons_from_geojson(json.loads(path.read_text(encoding="utf-8"))))


def find_land_file(land_dir: str | Path) -> Path:
    """Find the land file inside a folder. The environment variable overrides the folder."""
    folder = Path(os.environ.get("GULFOILGUARD_LAND_DIR", land_dir))
    for name in LAND_FILE_NAMES:
        candidate = folder / name
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"no land file found in {folder} (looked for {', '.join(LAND_FILE_NAMES)}). "
        "See the download steps at the top of optimization/sea_grid.py"
    )


# ---------------------------------------------------------------------------
# The land / water grid
# ---------------------------------------------------------------------------


class LandMask:
    """A grid over the region. `land[row, col]` is True for land. Row 0 is the north edge."""

    def __init__(self, region: GridRegion, land: np.ndarray) -> None:
        if land.shape != (region.rows, region.cols):
            raise ValueError(f"land grid shape {land.shape} does not match the region")
        self.region = region
        self.land = land.astype(bool)

    @property
    def water_fraction(self) -> float:
        return float(1.0 - self.land.mean())

    def cell_of(self, point: GeoCoordinate) -> tuple[int, int] | None:
        """The (row, col) cell holding a point, or None if the point is outside the region."""
        reg = self.region
        if not (reg.lat_min <= point.latitude <= reg.lat_max):
            return None
        if not (reg.lon_min <= point.longitude <= reg.lon_max):
            return None
        row = min(int((reg.lat_max - point.latitude) / reg.cell_deg), reg.rows - 1)
        col = min(int((point.longitude - reg.lon_min) / reg.cell_deg), reg.cols - 1)
        return row, col

    def center_of(self, row: int, col: int) -> GeoCoordinate:
        reg = self.region
        return GeoCoordinate(
            latitude=reg.lat_max - (row + 0.5) * reg.cell_deg,
            longitude=reg.lon_min + (col + 0.5) * reg.cell_deg,
        )

    @classmethod
    def from_polygons(cls, region: GridRegion, polygons: Iterable[Polygon]) -> "LandMask":
        image = Image.new("L", (region.cols, region.rows), 0)
        draw = ImageDraw.Draw(image)

        def to_pixels(ring: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
            # The -0.5 puts the middle of cell (row, col) on pixel (col, row).
            return [
                (
                    (lon - region.lon_min) / region.cell_deg - 0.5,
                    (region.lat_max - lat) / region.cell_deg - 0.5,
                )
                for lon, lat in ring
            ]

        for rings in polygons:
            if not rings or len(rings[0]) < 3:
                continue
            lons = [p[0] for p in rings[0]]
            lats = [p[1] for p in rings[0]]
            if (
                max(lons) < region.lon_min
                or min(lons) > region.lon_max
                or max(lats) < region.lat_min
                or min(lats) > region.lat_max
            ):
                continue  # far away from our region, skip it
            draw.polygon(to_pixels(rings[0]), fill=1)
            for hole in rings[1:]:
                if len(hole) >= 3:
                    draw.polygon(to_pixels(hole), fill=0)
        return cls(region, np.array(image, dtype=np.uint8).astype(bool))

    @classmethod
    def from_file(
        cls, region: GridRegion, path: str | Path, cache_dir: str | Path | None = None
    ) -> "LandMask":
        """Build the grid from a land file. The result is cached so the next run is fast."""
        path = Path(path)
        cache_file = None
        if cache_dir is not None:
            info = path.stat()
            key = f"{path.resolve()}|{info.st_size}|{info.st_mtime_ns}|{region}"
            digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
            cache_file = Path(cache_dir) / f"landmask_{digest}.npy"
            if cache_file.exists():
                return cls(region, np.load(cache_file))
        mask = cls.from_polygons(region, read_land_polygons(path))
        if cache_file is not None:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            np.save(cache_file, mask.land)
        return mask


# ---------------------------------------------------------------------------
# Distances through water
# ---------------------------------------------------------------------------


class SeaGridDistance:
    """Shortest distance through water between points (the real, navigable-water provider)."""

    def __init__(self, mask: LandMask, max_snap_km: float = 15.0) -> None:
        self.mask = mask
        self.max_snap_km = max_snap_km
        self.warnings: list[str] = []
        self._graph: csr_matrix | None = None

    @property
    def cell_km(self) -> float:
        return self.mask.region.cell_deg * KM_PER_DEGREE

    @property
    def description(self) -> str:
        return (
            f"sea-grid distances around land ({self.cell_km:.1f} km cells, approximate, "
            "not validated operational routes)"
        )

    # -- the graph of water cells -------------------------------------------

    def _get_graph(self) -> csr_matrix:
        """Connect every water cell to its water neighbours. Edge cost = real length in km."""
        if self._graph is not None:
            return self._graph

        reg = self.mask.region
        water = ~self.mask.land
        rows, cols = water.shape
        node = np.arange(rows * cols).reshape(rows, cols)

        dy = self.cell_km  # the height of a cell
        lat_centers = reg.lat_max - (np.arange(rows) + 0.5) * reg.cell_deg
        dx_row = dy * np.cos(np.radians(lat_centers))  # the width of a cell shrinks toward the poles
        dx_mid = 0.5 * (dx_row[:-1] + dx_row[1:])

        sources, targets, costs = [], [], []

        def add(ok: np.ndarray, src: np.ndarray, dst: np.ndarray, cost: np.ndarray) -> None:
            sources.append(src[ok])
            targets.append(dst[ok])
            costs.append(np.broadcast_to(cost, ok.shape)[ok])

        # east
        add(water[:, :-1] & water[:, 1:], node[:, :-1], node[:, 1:], dx_row[:, None])
        # south
        add(water[:-1, :] & water[1:, :], node[:-1, :], node[1:, :], np.float64(dy))
        # south-east. A diagonal step needs BOTH side cells to be water, so a path
        # cannot squeeze between two land cells that only touch at a corner.
        ok_se = water[:-1, :-1] & water[1:, 1:] & water[:-1, 1:] & water[1:, :-1]
        add(ok_se, node[:-1, :-1], node[1:, 1:], np.hypot(dx_mid[:, None], dy))
        # south-west
        ok_sw = water[:-1, 1:] & water[1:, :-1] & water[:-1, :-1] & water[1:, 1:]
        add(ok_sw, node[:-1, 1:], node[1:, :-1], np.hypot(dx_mid[:, None], dy))

        self._graph = csr_matrix(
            (np.concatenate(costs), (np.concatenate(sources), np.concatenate(targets))),
            shape=(rows * cols, rows * cols),
        )
        return self._graph

    # -- placing a point on the grid ----------------------------------------

    def _nearest_water(self, row: int, col: int, latitude: float) -> tuple[int, int] | None:
        dy = self.cell_km
        dx = max(dy * cos(radians(latitude)), 1e-6)
        k_rows = ceil(self.max_snap_km / dy) + 1
        k_cols = ceil(self.max_snap_km / dx) + 1
        r0, r1 = max(0, row - k_rows), min(self.mask.land.shape[0], row + k_rows + 1)
        c0, c1 = max(0, col - k_cols), min(self.mask.land.shape[1], col + k_cols + 1)
        window_rows, window_cols = np.nonzero(~self.mask.land[r0:r1, c0:c1])
        if window_rows.size == 0:
            return None
        distance = np.hypot((window_rows + r0 - row) * dy, (window_cols + c0 - col) * dx)
        best = int(np.argmin(distance))
        return int(window_rows[best] + r0), int(window_cols[best] + c0)

    def _place(self, point: GeoCoordinate, label: str) -> tuple[int, int, float, str | None]:
        """Return (row, col, extra_km, warning). extra_km is the move to the nearest water."""
        where = f"{label} ({point.latitude:.3f}, {point.longitude:.3f})"
        cell = self.mask.cell_of(point)
        if cell is None:
            raise SeaRoutingError(f"{where} is outside the sea-distance region")
        row, col = cell
        if not self.mask.land[row, col]:
            return row, col, 0.0, None
        found = self._nearest_water(row, col, point.latitude)
        if found is None:
            raise SeaRoutingError(f"{where} is on land, no water within {self.max_snap_km:.0f} km")
        row, col = found
        moved_km = haversine_km(point, self.mask.center_of(row, col))
        if moved_km > self.max_snap_km:
            raise SeaRoutingError(
                f"{where} is on land, nearest water is {moved_km:.1f} km away "
                f"(limit {self.max_snap_km:.0f} km)"
            )
        return row, col, moved_km, f"{where} was on land and moved {moved_km:.1f} km to the nearest water"

    # -- the distance table --------------------------------------------------

    def _shortest(self, nodes: Sequence[int]) -> np.ndarray:
        graph = self._get_graph()
        batches = [list(nodes[i : i + 16]) for i in range(0, len(nodes), 16)]
        return np.vstack([dijkstra(graph, directed=False, indices=batch) for batch in batches])

    def matrix_km(
        self, points: Sequence[GeoCoordinate], labels: Sequence[str] | None = None
    ) -> list[list[float]]:
        self.warnings = []
        n = len(points)
        names = list(labels) if labels is not None else [f"point {i}" for i in range(n)]

        cells: list[tuple[int, int]] = []
        extra: list[float] = []
        for point, name in zip(points, names):
            row, col, moved_km, warning = self._place(point, name)
            cells.append((row, col))
            extra.append(moved_km)
            if warning:
                self.warnings.append(warning)

        width = self.mask.land.shape[1]
        nodes = [row * width + col for row, col in cells]
        unique = sorted(set(nodes))
        row_of = {node: k for k, node in enumerate(unique)}
        paths = self._shortest(unique)

        out = [[0.0] * n for _ in range(n)]
        unreachable: list[str] = []
        for i in range(n):
            for j in range(i + 1, n):
                if nodes[i] == nodes[j]:
                    if extra[i] == 0.0 and extra[j] == 0.0:
                        d = haversine_km(points[i], points[j])  # same cell: use the direct distance
                    else:
                        d = extra[i] + extra[j]
                else:
                    base = float(paths[row_of[nodes[i]], nodes[j]])
                    if np.isfinite(base):
                        d = base + extra[i] + extra[j]
                    else:
                        d = UNREACHABLE_KM
                        unreachable.append(f"{names[i]} and {names[j]}")
                out[i][j] = out[j][i] = d

        if unreachable:
            shown = "; ".join(unreachable[:3]) + (" ..." if len(unreachable) > 3 else "")
            self.warnings.append(
                f"no sea route between {len(unreachable)} pair(s) of points ({shown}); "
                f"treated as {UNREACHABLE_KM:.0f} km, so the solver will avoid them"
            )
        return out

    def distances_from(self, origin: GeoCoordinate) -> Callable[[GeoCoordinate], float]:
        """km from `origin` to any point, after ONE shortest-path search (for moving targets).

        Same rules as matrix_km (snap to water, same-cell shortcut, UNREACHABLE_KM), but it
        does not touch `warnings`, so the plan's own warnings stay as the solver left them.
        """
        width = self.mask.land.shape[1]
        row, col, extra, _ = self._place(origin, "origin")
        start = row * width + col
        paths = self._shortest([start])[0]

        def to(point: GeoCoordinate) -> float:
            r, c, moved, _ = self._place(point, "point")
            node = r * width + c
            if node == start:
                return haversine_km(origin, point) if extra == 0.0 and moved == 0.0 else extra + moved
            base = float(paths[node])
            return base + extra + moved if np.isfinite(base) else UNREACHABLE_KM

        return to

    def path(self, a: GeoCoordinate, b: GeoCoordinate) -> list[GeoCoordinate]:
        """The sea path from a to b as a list of points (for drawing a route on a map)."""
        row_a, col_a, _, _ = self._place(a, "start")
        row_b, col_b, _, _ = self._place(b, "end")
        width = self.mask.land.shape[1]
        start, goal = row_a * width + col_a, row_b * width + col_b
        _, predecessors = dijkstra(
            self._get_graph(), directed=False, indices=[start], return_predecessors=True
        )
        chain = [goal]
        while chain[-1] != start:
            previous = int(predecessors[0, chain[-1]])
            if previous < 0:
                raise SeaRoutingError("no sea route between the two points")
            chain.append(previous)
        chain.reverse()
        middle = [self.mask.center_of(n // width, n % width) for n in chain]
        return [a, *middle, b]


# ---------------------------------------------------------------------------
# The default provider used by routing_model.solve_routes
# ---------------------------------------------------------------------------


@lru_cache(maxsize=4)
def _cached_provider(land_file: str, region: GridRegion, max_snap_km: float, cache_dir: str):
    mask = LandMask.from_file(region, land_file, cache_dir)
    return SeaGridDistance(mask, max_snap_km)


def default_sea_provider(config: RoutingConfig) -> SeaGridDistance:
    """Build (once) and return the sea-grid provider described by the config.

    Raises FileNotFoundError if the land file has not been downloaded yet.
    """
    land_file = find_land_file(config.land_dir)
    return _cached_provider(str(land_file), config.region, config.max_snap_km, config.cache_dir)
