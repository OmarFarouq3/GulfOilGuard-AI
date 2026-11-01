"""The working-time rules, in one place, shared by the solver, the baseline and the checks.

A vessel's work time on a route = sailing time + cleanup time at every target.
It must fit inside the vessel's `available_hours`.

OR-Tools needs whole minutes, so every leg and every cleanup is rounded UP and the
available hours are rounded DOWN. That makes the rule slightly strict, so a plan that
passes here never breaks the real (unrounded) limit. The baseline uses the same
rounding, so the comparison with our plan stays fair.
"""

from math import ceil, floor
from typing import Sequence

from optimization.config import RoutingConfig
from optimization.units import travel_hours
from shared.schemas import ResponseTarget, Vessel


def service_hours(volume_m3: float, config: RoutingConfig) -> float:
    """Hours a vessel needs to clean this much oil."""
    return volume_m3 / config.recovery_rate_m3_per_hour


def minutes_up(hours: float) -> int:
    return max(0, ceil(hours * 60 - 1e-9))


def minutes_down(hours: float) -> int:
    return max(0, floor(hours * 60 + 1e-9))


def leg_minutes(distance_km: float, speed_m_per_s: float) -> int:
    """Sailing minutes for one leg, rounded up."""
    return minutes_up(travel_hours(distance_km, speed_m_per_s))


def service_minutes(volume_m3: float, config: RoutingConfig) -> int:
    """Cleanup minutes for one target, rounded up."""
    return minutes_up(service_hours(volume_m3, config))


def unserved_reason(
    target: ResponseTarget,
    vessels: Sequence[Vessel],
    km_from_each_vessel: Sequence[float],
    config: RoutingConfig,
) -> str:
    """A short, plain reason why nobody served this target (goes into `message`)."""
    if target.oil_volume_m3 > max(v.capacity_m3 for v in vessels) + 1e-9:
        return "larger than every vessel tank"
    cleanup = service_minutes(target.oil_volume_m3, config)
    if all(
        leg_minutes(km, v.speed_m_per_s) + cleanup > minutes_down(v.available_hours)
        for v, km in zip(vessels, km_from_each_vessel)
    ):
        return "no vessel has enough hours to reach it and clean it"
    return "vessels were full or out of hours after serving other targets"
