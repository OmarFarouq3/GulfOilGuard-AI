"""The simple comparison method: "nearest target first".

Rules of the baseline, in plain words:
  Look at every vessel and every target that is still open. Pick the pair with the
  shortest trip from where that vessel is now. Send the vessel there. Repeat until
  no vessel can take another target. Then every vessel sails back to its port; a
  target is only taken if there are still hours left to get back after it.

It follows EXACTLY the same rules as our plan (same distances, tank size, speed,
working hours and cleanup time), so the comparison is fair. It returns the same
OptimizationOutput type, so the same checks and the same dashboard code work on it.
"""

from optimization.checks import early_result
from optimization.config import DEFAULT_CONFIG, RoutingConfig
from optimization.limits import leg_minutes, minutes_down, service_minutes, unserved_reason
from optimization.routing_model import RETURN_NOTE
from optimization.sea_distance import DistanceProvider, default_provider
from optimization.units import travel_hours
from shared.schemas import OptimizationOutput, ResponseTarget, Vessel, VesselRoute


def nearest_first_routes(
    vessels: tuple[Vessel, ...],
    targets: tuple[ResponseTarget, ...],
    config: RoutingConfig = DEFAULT_CONFIG,
    distance_provider: DistanceProvider | None = None,
) -> OptimizationOutput:
    """Greedy baseline plan. Never raises: problems come back in `status` and `message`.

    Pass the SAME distance_provider that the optimized plan used, so both plans measure
    distance the same way.
    """
    early = early_result(vessels, targets)
    if early is not None:
        return early
    try:
        provider = distance_provider or default_provider(config)
        return _plan(vessels, targets, config, provider)
    except Exception as exc:
        return OptimizationOutput(
            routes=(), status="error", message=f"baseline failed: {type(exc).__name__}: {exc}"
        )


def _plan(
    vessels: tuple[Vessel, ...],
    targets: tuple[ResponseTarget, ...],
    config: RoutingConfig,
    provider: DistanceProvider,
) -> OptimizationOutput:
    n_vessels = len(vessels)
    points = [v.location for v in vessels] + [t.location for t in targets]
    labels = [v.vessel_id for v in vessels] + [t.target_id for t in targets]
    km = provider.matrix_km(points, labels)

    where = list(range(n_vessels))  # the node each vessel is at now
    tank_left = [v.capacity_m3 for v in vessels]
    minutes_left = [minutes_down(v.available_hours) for v in vessels]
    paths = [[v] for v in range(n_vessels)]
    open_targets = list(range(len(targets)))

    while open_targets:
        best = None  # (trip km, vessel, target, minutes needed)
        for v, vessel in enumerate(vessels):
            for t in open_targets:
                volume = targets[t].oil_volume_m3
                trip_km = km[where[v]][n_vessels + t]
                needed = leg_minutes(trip_km, vessel.speed_m_per_s) + service_minutes(volume, config)
                home = leg_minutes(km[n_vessels + t][v], vessel.speed_m_per_s)  # and back to port after it
                if volume <= tank_left[v] + 1e-9 and needed + home <= minutes_left[v]:
                    if best is None or (trip_km, v, t) < best[:3]:
                        best = (trip_km, v, t, needed)
        if best is None:
            break
        _, v, t, needed = best
        tank_left[v] -= targets[t].oil_volume_m3
        minutes_left[v] -= needed
        where[v] = n_vessels + t
        paths[v].append(n_vessels + t)
        open_targets.remove(t)

    routes = []
    for v, vessel in enumerate(vessels):
        path = paths[v] + ([v] if len(paths[v]) > 1 else [])  # back to port
        distance_km = sum(km[a][b] for a, b in zip(path, path[1:]))
        routes.append(
            VesselRoute(
                vessel_id=vessel.vessel_id,
                assigned_target_ids=tuple(targets[n - n_vessels].target_id for n in paths[v][1:]),
                coordinates=tuple(points[n] for n in path),
                estimated_distance_km=distance_km,
                estimated_travel_hours=travel_hours(distance_km, vessel.speed_m_per_s),
            )
        )

    unserved = [
        f"{targets[t].target_id} ({unserved_reason(targets[t], vessels, [km[v][n_vessels + t] for v in range(n_vessels)], config)})"
        for t in open_targets
    ]
    notes = [
        "baseline: nearest target first",
        provider.description,
        *provider.warnings,
        RETURN_NOTE,
        f"cleanup rate {config.recovery_rate_m3_per_hour:g} m3/h (assumed)",
        f"unserved: {', '.join(unserved) if unserved else 'none'}",
    ]
    return OptimizationOutput(routes=tuple(routes), status="feasible", message="; ".join(notes))
