"""The working-time rules, in one place, shared by the solver, the baseline and the checks.

A vessel's work time on a route = sailing time (out, between targets AND back to the port
it started from) + cleanup time at every target. It must fit inside `available_hours`.

What fills the tank, and what the skimmer pumps, is `tank_m3(target)`: the emulsion (oil plus
the water mixed into it) when the target knows it (EmulsionTarget, from a drift forecast),
otherwise its pure oil. Oil recovered is always counted as `oil_volume_m3`.

OR-Tools needs whole minutes, so every leg and every cleanup is rounded UP and the
available hours are rounded DOWN. That makes the rule slightly strict, so a plan that
passes here never breaks the real (unrounded) limit. The baseline uses the same
rounding, so the comparison with our plan stays fair.
"""

from dataclasses import dataclass
from math import ceil, floor
from typing import Sequence

from optimization.config import RoutingConfig
from optimization.units import travel_hours
from shared.schemas import ResponseTarget, Vessel


@dataclass(frozen=True)
class EmulsionTarget(ResponseTarget):
    """A target that knows how much it fills a tank. oil_volume_m3 stays the pure oil (what
    counts as recovered); emulsion_m3 = oil / (1 - water_fraction) is what the vessel takes on."""

    emulsion_m3: float = 0.0
    water_fraction: float = 0.0


def tank_m3(target: ResponseTarget) -> float:
    """m3 this target puts in a tank and through the skimmer: emulsion if known, else pure oil."""
    return target.emulsion_m3 if isinstance(target, EmulsionTarget) else target.oil_volume_m3


def service_hours(volume_m3: float, config: RoutingConfig) -> float:
    """Hours a vessel needs to skim this much (pass tank_m3 of the target)."""
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
    if tank_m3(target) > max(v.capacity_m3 for v in vessels) + 1e-9:
        return "larger than every vessel tank"
    cleanup = service_minutes(tank_m3(target), config)
    if all(
        2 * leg_minutes(km, v.speed_m_per_s) + cleanup > minutes_down(v.available_hours)
        for v, km in zip(vessels, km_from_each_vessel)
    ):
        return "no vessel has enough hours to reach it, clean it and sail back to port"
    return "vessels were full or out of hours after serving other targets"
