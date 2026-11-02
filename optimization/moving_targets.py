"""Cleanup routing when the oil MOVES (drift), for both our plan and the baseline.

OR-Tools plans to fixed points, but a patch keeps drifting while a vessel sails to it.
So the moving problem is wrapped around the fixed-point model:

  1. guess when each patch will be reached (first guess: at dispatch)
  2. solve with OR-Tools, using where each patch will be AT that time (routing_model.py)
  3. SAIL the plan in time against the moving oil (sail below). Every leg aims at where the
     patch will be when the vessel arrives (an interception, _intercept). This gives the real
     meeting times
  4. if the solver aimed more than replan_tolerance_km away from where a patch was really
     met, go back to 2 with the real meeting times (at most max_replans rounds, config.py)

Of all rounds, the best SAILED plan is kept (most oil, then earliest finish, then fewest km):
a new round can reorder the stops, so the last round is not always the best one.

The plan we keep is a SAILED one (step 3), not the solver's guess. Sailing applies the
same rules as everywhere else (tank, hours with the limits.py rounding, cleanup time at the
oil volume found on arrival), and a stop that no longer fits is skipped. So the kept plan
always follows the rules, even if the rounds did not fully settle.

The baseline gets the same moving oil: "nearest target first" where nearest means the
shortest interception trip from where the vessel is now (nearest_first_moving).

While a vessel cleans a patch it drifts with it, so its next leg starts from where the
patch is when cleaning ends. After its last patch every vessel sails back to the port it
started from, and a patch is only taken if the hours still cover that trip back.

Honest limits:
  - between forecast steps a patch moves in a straight line (hourly steps are best)
  - after the last forecast step a patch is held where that step put it (flagged in the message)
  - a patch is one point, not a shape: a vessel "meets" it at its oil-weighted centre
"""

from dataclasses import dataclass
from statistics import mean

from optimization.checks import early_result
from optimization.config import DEFAULT_CONFIG, DEFAULT_DRIFT_CONFIG, DriftTargetConfig, RoutingConfig
from optimization.drift_targets import PatchTrack
from optimization.limits import leg_minutes, minutes_down, service_hours, service_minutes
from optimization.routing_model import RETURN_NOTE, solve_routes
from optimization.sea_distance import DistanceProvider, distances_from, haversine_km
from optimization.units import travel_hours
from shared.schemas import OptimizationOutput, ResponseTarget, Vessel, VesselRoute

INTERCEPT_ROUNDS = 8  # oil drifts far slower than a vessel sails, so 2-3 rounds already settle


@dataclass(frozen=True)
class Stop:
    target_id: str
    meet_hours: float  # hours since release when the vessel reaches the patch
    target: ResponseTarget  # the patch as the vessel finds it: place and oil then
    leg_km: float


@dataclass(frozen=True)
class MovingPlan:
    """A plan for moving oil, plus what the dashboard and the comparison need."""

    plan: OptimizationOutput
    targets: tuple[ResponseTarget, ...]  # served: as met; unserved: where they were at dispatch
    meet_hours: dict[str, float]  # target_id -> meeting time, for the served targets
    moved_km: dict[str, float]  # how far each served patch drifted from dispatch to its meeting
    rounds: int = 1
    last_cleanup_hours: float | None = None  # hours since release when the last patch is cleaned


def mean_or_zero(values) -> float:
    return mean(values) if values else 0.0


def _intercept(distance_to, track: PatchTrack, depart_hours: float, speed_m_per_s: float):
    """(meet hours, patch as met, leg km): where to sail to catch the patch, not where it is now."""
    meet = depart_hours
    for _ in range(INTERCEPT_ROUNDS):
        target = track.target_at(meet)
        km = distance_to(target.location)
        arrive = depart_hours + travel_hours(km, speed_m_per_s)
        settled = abs(arrive - meet) < 1e-3  # about 4 seconds
        meet = arrive
        if settled:
            break
    return meet, track.target_at(meet), distance_to(track.target_at(meet).location)


class _Voyage:
    """One vessel sailing in time: where it is, what time it is, what tank and hours are left."""

    def __init__(self, vessel: Vessel, dispatch_hours: float, provider: DistanceProvider) -> None:
        self.vessel = vessel
        # km from the port, which is also the km back to it (sea distances are symmetric)
        self.port_km = distances_from(provider, vessel.location)
        self.here = vessel.location
        self.clock = dispatch_hours
        self.tank = vessel.capacity_m3
        self.minutes_left = minutes_down(vessel.available_hours)
        self.stops: list[Stop] = []

    def reach(self, track: PatchTrack, distance_to, config: RoutingConfig, gone_below_m3: float):
        """(the stop, None) if this vessel can still catch, hold and clean the patch, and then get
        back to port in its hours; else (None, why)."""
        speed = self.vessel.speed_m_per_s
        meet, target, km = _intercept(distance_to, track, self.clock, speed)
        if target.oil_volume_m3 < gone_below_m3:
            return None, "the oil is gone (stranded or weathered) by the time a vessel gets there"
        if target.oil_volume_m3 > self.tank + 1e-9:
            return None, "not enough room left in the tank"
        done = track.target_at(meet + service_hours(target.oil_volume_m3, config)).location
        needed = leg_minutes(km, speed) + service_minutes(target.oil_volume_m3, config) + leg_minutes(self.port_km(done), speed)
        if needed > self.minutes_left:
            return None, "not enough working hours left to reach it, clean it and sail back to port"
        return Stop(track.target_id, meet, target, km), None

    def take(self, stop: Stop, track: PatchTrack, config: RoutingConfig) -> None:
        volume = stop.target.oil_volume_m3
        self.stops.append(stop)
        self.tank -= volume
        self.minutes_left -= leg_minutes(stop.leg_km, self.vessel.speed_m_per_s) + service_minutes(volume, config)
        self.clock = stop.meet_hours + service_hours(volume, config)
        self.here = track.target_at(self.clock).location  # it drifted with the oil while cleaning

    @property
    def return_km(self) -> float:
        return self.port_km(self.here) if self.stops else 0.0

    @property
    def back_hours(self) -> float:
        """Hours since release when the vessel is back in port."""
        return self.clock + travel_hours(self.return_km, self.vessel.speed_m_per_s)

    def route(self) -> VesselRoute:
        distance_km = sum(s.leg_km for s in self.stops) + self.return_km
        port = (self.vessel.location,) if self.stops else ()
        return VesselRoute(
            vessel_id=self.vessel.vessel_id,
            assigned_target_ids=tuple(s.target_id for s in self.stops),
            coordinates=(self.vessel.location, *(s.target.location for s in self.stops), *port),
            estimated_distance_km=distance_km,
            estimated_travel_hours=travel_hours(distance_km, self.vessel.speed_m_per_s),
        )


def _unserved_reason(track, vessels, dispatch_hours, provider, config, drift_config) -> str:
    """Why nobody serves this patch: could even a fresh vessel, straight from port, do it?"""
    reasons = []
    for vessel in vessels:
        voyage = _Voyage(vessel, dispatch_hours, provider)
        stop, why = voyage.reach(track, distances_from(provider, vessel.location), config, drift_config.gone_below_m3)
        if stop is not None:
            return "vessels were full or out of hours after serving other targets"
        reasons.append(why)
    return reasons[0] if len(set(reasons)) == 1 else "no vessel can reach it and clean it in its hours"


def _finish(
    voyages: list[_Voyage],
    tracks: tuple[PatchTrack, ...],
    vessels: tuple[Vessel, ...],
    dispatch_hours: float,
    provider: DistanceProvider,
    config: RoutingConfig,
    drift_config: DriftTargetConfig,
    notes: list[str],
    rounds: int = 1,
) -> MovingPlan:
    met = {s.target_id: s for v in voyages for s in v.stops}
    unserved = [t for t in tracks if t.target_id not in met]
    last_step = max(t.hours[-1] for t in tracks)
    late = [s.target_id for s in met.values() if s.meet_hours > last_step + 1e-9]
    message = [
        *notes,
        f"moving oil: vessels leave {dispatch_hours:g} h after the release; each target is where "
        "the vessel meets its patch, with the oil left then",
    ]
    if late:
        message.append(f"{len(late)} meeting(s) after the last forecast step ({last_step:g} h); "
                       "those patches were held at their last forecast place")
    message += [
        RETURN_NOTE,
        f"cleanup rate {config.recovery_rate_m3_per_hour:g} m3/h (assumed)",
        "unserved: " + (", ".join(
            f"{t.target_id} ({_unserved_reason(t, vessels, dispatch_hours, provider, config, drift_config)})"
            for t in unserved
        ) or "none"),
    ]
    plan = OptimizationOutput(routes=tuple(v.route() for v in voyages), status="feasible", message="; ".join(message))
    by_id = {t.target_id: t for t in tracks}
    return MovingPlan(
        plan=plan,
        targets=tuple(met[t.target_id].target if t.target_id in met else t.target_at(dispatch_hours) for t in tracks),
        meet_hours={i: s.meet_hours for i, s in met.items()},
        moved_km={i: haversine_km(by_id[i].target_at(dispatch_hours).location, s.target.location) for i, s in met.items()},
        rounds=rounds,
        last_cleanup_hours=max((v.clock for v in voyages if v.stops), default=None),
    )


def _failed(plan: OptimizationOutput, tracks, dispatch_hours) -> MovingPlan:
    return MovingPlan(plan, tuple(t.target_at(dispatch_hours) for t in tracks), {}, {})


def sail(
    vessels: tuple[Vessel, ...],
    plan: OptimizationOutput,
    tracks: tuple[PatchTrack, ...],
    dispatch_hours: float,
    provider: DistanceProvider,
    config: RoutingConfig = DEFAULT_CONFIG,
    drift_config: DriftTargetConfig = DEFAULT_DRIFT_CONFIG,
) -> list[_Voyage]:
    """Sail each vessel's visiting order against the moving oil. Stops that no longer fit are skipped."""
    by_id = {t.target_id: t for t in tracks}
    order = {r.vessel_id: r.assigned_target_ids for r in plan.routes}
    voyages = []
    for vessel in vessels:
        voyage = _Voyage(vessel, dispatch_hours, provider)
        for target_id in order.get(vessel.vessel_id, ()):
            track = by_id[target_id]
            stop, _ = voyage.reach(track, distances_from(provider, voyage.here), config, drift_config.gone_below_m3)
            if stop is not None:
                voyage.take(stop, track, config)
        voyages.append(voyage)
    return voyages


def solve_moving(
    vessels: tuple[Vessel, ...],
    tracks: tuple[PatchTrack, ...],
    dispatch_hours: float,
    provider: DistanceProvider,
    config: RoutingConfig = DEFAULT_CONFIG,
    drift_config: DriftTargetConfig = DEFAULT_DRIFT_CONFIG,
) -> MovingPlan:
    """Our plan for moving oil: OR-Tools inside a re-planning loop (see the top of this file).

    Never raises: problems come back in `plan.status` and `plan.message`.
    """
    try:
        return _solve_moving(vessels, tracks, dispatch_hours, provider, config, drift_config)
    except Exception as exc:  # keep the dashboard alive, but say what happened
        error = OptimizationOutput((), "error", f"moving solver failed: {type(exc).__name__}: {exc}")
        return _failed(error, tracks, dispatch_hours)


def _score(voyages: list["_Voyage"], dispatch_hours: float) -> tuple[float, float, float]:
    """The solver's goals, in order: most oil, then everyone back in port earliest, then the fewest km."""
    oil = sum(s.target.oil_volume_m3 for v in voyages for s in v.stops)
    finish = max((v.back_hours - dispatch_hours for v in voyages if v.stops), default=0.0)
    km = sum(s.leg_km for v in voyages for s in v.stops) + sum(v.return_km for v in voyages)
    return -round(oil, 3), round(finish, 3), round(km, 3)


def _solve_moving(vessels, tracks, dispatch_hours, provider, config, drift_config) -> MovingPlan:
    guess = {t.target_id: dispatch_hours for t in tracks}
    static = all(len(t.hours) == 1 for t in tracks)  # nothing moves: one round is enough
    best = None  # (score, voyages, round, gap km, warnings)
    for rounds in range(1, drift_config.max_replans + 1):
        snapshot = {
            t.target_id: target for t in tracks
            if (target := t.target_at(guess[t.target_id])).oil_volume_m3 >= drift_config.gone_below_m3
        }
        plan = solve_routes(vessels, tuple(snapshot.values()), config, distance_provider=provider)
        if plan.status not in ("optimal", "feasible") or not snapshot:
            return _failed(plan, tracks, dispatch_hours)
        warnings = list(provider.warnings)  # sailing does not touch them; keep the solver's
        voyages = sail(vessels, plan, tracks, dispatch_hours, provider, config, drift_config)
        # How wrong was the solver's picture? Where it planned to meet each patch vs where it did.
        gaps = [haversine_km(snapshot[s.target_id].location, s.target.location) for v in voyages for s in v.stops]
        gap = max(gaps, default=0.0)
        score = _score(voyages, dispatch_hours)
        if best is None or score < best[0]:
            best = (score, voyages, rounds, gaps, warnings)
        guess |= {s.target_id: s.meet_hours for v in voyages for s in v.stops}
        if static or gap <= drift_config.replan_tolerance_km:
            break
    _, voyages, kept, gaps, warnings = best
    tolerance = drift_config.replan_tolerance_km
    stopped = (
        "nothing moves" if static
        else f"the solver aimed within {tolerance:g} km" if gap <= tolerance
        else f"max_replans reached, the solver still aimed up to {gap:.1f} km off"
    )
    notes = [provider.description, *warnings,
             f"planned {rounds} round(s), stopped because {stopped}; kept round {kept} (the best as sailed), "
             f"where the solver aimed {mean_or_zero(gaps):.1f} km on average ({max(gaps, default=0.0):.1f} km at most) "
             "from where the patches were met"]
    return _finish(voyages, tracks, vessels, dispatch_hours, provider, config, drift_config, notes, kept)


def nearest_first_moving(
    vessels: tuple[Vessel, ...],
    tracks: tuple[PatchTrack, ...],
    dispatch_hours: float,
    provider: DistanceProvider,
    config: RoutingConfig = DEFAULT_CONFIG,
    drift_config: DriftTargetConfig = DEFAULT_DRIFT_CONFIG,
) -> MovingPlan:
    """The baseline for moving oil: always take the shortest interception trip that still fits.

    Same rules, oil and distances as solve_moving, so the comparison is fair. Never raises.
    """
    try:
        return _nearest_first_moving(vessels, tracks, dispatch_hours, provider, config, drift_config)
    except Exception as exc:
        error = OptimizationOutput((), "error", f"baseline failed: {type(exc).__name__}: {exc}")
        return _failed(error, tracks, dispatch_hours)


def _nearest_first_moving(vessels, tracks, dispatch_hours, provider, config, drift_config) -> MovingPlan:
    early = early_result(vessels, tuple(t.target_at(dispatch_hours) for t in tracks))
    if early is not None:
        return _failed(early, tracks, dispatch_hours)
    # Like baseline.py: one table over the start points, so the same land warnings are reported.
    provider.matrix_km(
        [v.location for v in vessels] + [t.target_at(dispatch_hours).location for t in tracks],
        [v.vessel_id for v in vessels] + [t.target_id for t in tracks],
    )
    warnings = list(provider.warnings)
    voyages = [_Voyage(v, dispatch_hours, provider) for v in vessels]
    open_tracks = list(tracks)
    while open_tracks:
        best = None  # (trip km, vessel number, track number, stop)
        for v, voyage in enumerate(voyages):
            distance_to = distances_from(provider, voyage.here)
            for t, track in enumerate(open_tracks):
                stop, _ = voyage.reach(track, distance_to, config, drift_config.gone_below_m3)
                if stop is not None and (best is None or (stop.leg_km, v, t) < best[:3]):
                    best = (stop.leg_km, v, t, stop)
        if best is None:
            break
        _, v, t, stop = best
        voyages[v].take(stop, open_tracks.pop(t), config)
    notes = ["baseline: nearest (interception) target first", provider.description, *warnings]
    return _finish(voyages, tracks, vessels, dispatch_hours, provider, config, drift_config, notes)

