"""All tunable settings for cleanup routing, in one place.

Anything marked ASSUMPTION is a placeholder, not a fact. Say so in the report.
"""

from dataclasses import dataclass
from math import ceil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class GridRegion:
    """The sea area we build the water grid for, and how fine the grid is.

    Points outside this box cannot be routed. cell_deg=0.02 is about 2.2 km.
    A smaller cell is more exact but slower and uses more memory.
    """

    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    cell_deg: float = 0.02

    def __post_init__(self) -> None:
        if not (self.lat_min < self.lat_max and self.lon_min < self.lon_max):
            raise ValueError("region needs lat_min < lat_max and lon_min < lon_max")
        if self.cell_deg <= 0:
            raise ValueError("cell_deg must be above 0")

    @property
    def rows(self) -> int:
        return ceil(round((self.lat_max - self.lat_min) / self.cell_deg, 6))

    @property
    def cols(self) -> int:
        return ceil(round((self.lon_max - self.lon_min) / self.cell_deg, 6))


# Arabian Gulf, Strait of Hormuz and the Gulf of Oman side.
GULF_REGION = GridRegion(lat_min=22.0, lat_max=31.0, lon_min=47.0, lon_max=60.0, cell_deg=0.02)


@dataclass(frozen=True)
class RoutingConfig:
    # How long OR-Tools may search before it returns the best plan it has.
    time_limit_seconds: int = 5

    # --- what the solver aims for, most important first ---
    # 1. Recover as much oil as possible. Leaving a target unserved costs drop_penalty_km
    #    plus drop_penalty_km_per_m3 for every m3 of its oil. Both are large on purpose, so
    #    the solver serves every target it can, and when it must skip one it skips the
    #    smallest oil patch, not just the one that is farthest away.
    drop_penalty_km: int = 10_000
    drop_penalty_km_per_m3: int = 1_000
    # 2. Finish the whole response early. Every hour until the LAST vessel is done costs
    #    this many km, so the solver uses all vessels instead of sending one far and leaving
    #    a fast one idle. Oil keeps spreading while it waits, so time beats fuel.
    #    ASSUMPTION: a judgement call, not a measured value. Keep it small next to
    #    drop_penalty_km (hours x this must stay below it) so goal 1 always comes first.
    response_hour_cost_km: int = 100
    # 3. Sail as little as possible: the total distance is the rest of the cost.

    # OR-Tools works with whole numbers, so oil is counted in tenths of a m3.
    volume_scale: int = 10

    # --- cleanup time (Phase 3) ---
    # How fast one vessel removes oil. ASSUMPTION: a placeholder, not a fact about any real
    # vessel. 30 m3 per hour is the skimmer pump rate used in the Khark Island case study
    # (Ranjbar et al.), so it is a reasonable starting point to cite and then replace.
    # The same rate applies to every vessel until the schema has a per-vessel rate.
    recovery_rate_m3_per_hour: float = 30.0

    # --- navigable-water distances (Phase 2) ---
    # Folder (inside the ignored data/ folder) that holds the land polygons file.
    # Download steps are in optimization/sea_grid.py. The environment variable
    # GULFOILGUARD_LAND_DIR can point somewhere else.
    land_dir: str = str(REPO_ROOT / "data" / "land")
    region: GridRegion = GULF_REGION
    # A point on land (for example a coarse coastline) is moved to the nearest water,
    # but only if the water is closer than this. Farther than this is reported as an error.
    max_snap_km: float = 15.0
    # Where the built land grid is cached, so the next run starts fast.
    cache_dir: str = str(REPO_ROOT / "data" / "cache")

    def __post_init__(self) -> None:
        if self.recovery_rate_m3_per_hour <= 0:
            raise ValueError("recovery_rate_m3_per_hour must be above 0")
        if self.time_limit_seconds < 1:
            raise ValueError("time_limit_seconds must be at least 1")
        if min(self.drop_penalty_km, self.drop_penalty_km_per_m3, self.response_hour_cost_km) < 0:
            raise ValueError("drop penalties and response_hour_cost_km must be 0 or more")


DEFAULT_CONFIG = RoutingConfig()
