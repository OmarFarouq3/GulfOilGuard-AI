"""All tunable settings for cleanup routing, in one place.

Anything marked ASSUMPTION is a placeholder, not a fact. Say so in the report.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RoutingConfig:
    # How long OR-Tools may search before it returns the best plan it has.
    time_limit_seconds: int = 5

    # Cost (in km) of leaving one target unserved. It is large on purpose, so the
    # solver serves every target it can and only skips one when it must.
    drop_penalty_km: int = 10_000

    # OR-Tools works with whole numbers, so oil is counted in tenths of a m3.
    volume_scale: int = 10


DEFAULT_CONFIG = RoutingConfig()
