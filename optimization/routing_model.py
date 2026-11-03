"""The OR-Tools model for cleanup routing.

What the model enforces now:
  - vessel capacity (a vessel never takes more than its tank: emulsion when the target
    knows it, see limits.tank_m3, otherwise pure oil)
  - working hours (sailing + cleanup time must fit inside `available_hours`)
  - every vessel sails back to the port it started from (the schema has no home port,
    so its start position is taken as its port). The trip back counts for the hours
  - one trip per vessel: a vessel fills its tank once, it does not unload and go again
  - skipping: any target may be left out, but at a very high cost
  - distances through navigable water when the land file exists (otherwise straight
    lines, and the plan's `message` says so)

What the model aims for, most important first (weights in config.py):
  1. recover the most oil (skipping a target costs more the more oil it holds)
  2. finish the whole response early (the time the LAST vessel is back in port)
  3. sail the fewest km

NOT done here: risk and deadlines (Phase 7). Moving oil (drift) is handled AROUND this
model, by re-planning in moving_targets.py: this model always sees fixed points.

How the model is laid out (the "school bus" picture):
  nodes 0 .. V-1        the start position of each vessel (one bus, one start). It is
                        also where that vessel ends: the bus goes back to its own garage
  nodes V .. V+T-1      the oil targets (the students waiting)
"""

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from optimization.checks import early_result
from optimization.config import DEFAULT_CONFIG, RoutingConfig
from optimization.limits import leg_minutes, minutes_down, service_minutes, tank_m3, unserved_reason
from optimization.sea_distance import DistanceProvider, default_provider
from optimization.units import km_to_metres, travel_hours, volume_to_units
from shared.schemas import (
    OptimizationOutput,
    ResponseTarget,
    Vessel,
    VesselRoute,
)

# ASSUMPTION approved by the team lead: the schema has no home port, so each vessel is
# taken back to where it started. Every plan says so in its message.
RETURN_NOTE = "every vessel sails back to the port it started from (assumed home port), one trip each"


def solve_routes(
    vessels: tuple[Vessel, ...],
    targets: tuple[ResponseTarget, ...],
    config: RoutingConfig = DEFAULT_CONFIG,
    distance_provider: DistanceProvider | None = None,
) -> OptimizationOutput:
    """Plan routes. Never raises: problems come back in `status` and `message`.

    If no distance_provider is given, navigable-water distances are used when the
    land file exists, otherwise straight lines with a warning in the message.
    """
    early = early_result(vessels, targets)
    if early is not None:
        return early

    try:
        provider = distance_provider or default_provider(config)
        return _solve(vessels, targets, config, provider)
    except Exception as exc:  # keep the dashboard alive, but say what happened
        return OptimizationOutput(
            routes=(), status="error", message=f"solver failed: {type(exc).__name__}: {exc}"
        )


def _solve(
    vessels: tuple[Vessel, ...],
    targets: tuple[ResponseTarget, ...],
    config: RoutingConfig,
    provider: DistanceProvider,
) -> OptimizationOutput:
    n_vessels = len(vessels)
    points = [v.location for v in vessels] + [t.location for t in targets]
    labels = [v.vessel_id for v in vessels] + [t.target_id for t in targets]
    n_nodes = len(points)

    km = provider.matrix_km(points, labels)

    # Whole-number distance table in metres.
    dist_m = [[km_to_metres(km[i][j]) for j in range(n_nodes)] for i in range(n_nodes)]

    demand = [0] * n_nodes
    cleanup_min = [0] * n_nodes
    for t_idx, target in enumerate(targets):  # the tank and the skimmer take emulsion when known
        demand[n_vessels + t_idx] = volume_to_units(tank_m3(target), config.volume_scale)
        cleanup_min[n_vessels + t_idx] = service_minutes(tank_m3(target), config)
    capacities = [volume_to_units(v.capacity_m3, config.volume_scale) for v in vessels]

    ports = list(range(n_vessels))  # each vessel starts and ends at its own node
    manager = pywrapcp.RoutingIndexManager(n_nodes, n_vessels, ports, ports)
    routing = pywrapcp.RoutingModel(manager)

    # --- cost: total distance sailed ---
    def distance_callback(from_index: int, to_index: int) -> int:
        return dist_m[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

    transit_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_index)

    # --- limit 1: oil capacity ---
    def demand_callback(from_index: int) -> int:
        return demand[manager.IndexToNode(from_index)]

    demand_index = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(demand_index, 0, capacities, True, "Capacity")

    # --- limit 2: working hours. Each vessel has its own speed, so each gets its own
    # time callback: minutes to sail the leg, plus minutes to clean the place it leaves.
    def make_time_callback(v_idx: int):
        speed = vessels[v_idx].speed_m_per_s
        minutes = [[leg_minutes(km[i][j], speed) for j in range(n_nodes)] for i in range(n_nodes)]

        def time_callback(from_index: int, to_index: int) -> int:
            a = manager.IndexToNode(from_index)
            b = manager.IndexToNode(to_index)
            return minutes[a][b] + cleanup_min[a]

        return time_callback

    time_indices = [routing.RegisterTransitCallback(make_time_callback(v)) for v in range(n_vessels)]
    hour_limits = [minutes_down(v.available_hours) for v in vessels]
    routing.AddDimensionWithVehicleTransitAndCapacity(time_indices, 0, hour_limits, True, "Time")

    # --- goal 2: finish early. The "span" is the time the last vessel is back. The cost is
    # in metres (like the distance), so km per hour becomes metres per minute.
    routing.GetDimensionOrDie("Time").SetGlobalSpanCostCoefficient(
        round(config.response_hour_cost_km * 1000 / 60)
    )

    # --- goal 1, skipping: every target may be left out, but it costs a lot, and more
    # for a bigger oil patch ---
    for t_idx, target in enumerate(targets):
        penalty_km = config.drop_penalty_km + config.drop_penalty_km_per_m3 * target.oil_volume_m3
        routing.AddDisjunction([manager.NodeToIndex(n_vessels + t_idx)], round(penalty_km * 1000))

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    params.time_limit.FromSeconds(config.time_limit_seconds)

    solution = routing.SolveWithParameters(params)
    if solution is None:
        return _no_solution(routing)

    routes: list[VesselRoute] = []
    served: set[int] = set()
    for v_idx, vessel in enumerate(vessels):
        stops: list[int] = []
        index = routing.Start(v_idx)
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node >= n_vessels:  # the vessel's own port node is below V
                stops.append(node - n_vessels)
            index = solution.Value(routing.NextVar(index))

        served.update(stops)
        path = [v_idx] + [n_vessels + s for s in stops] + ([v_idx] if stops else [])
        distance_km = sum(km[a][b] for a, b in zip(path, path[1:]))
        routes.append(
            VesselRoute(
                vessel_id=vessel.vessel_id,
                assigned_target_ids=tuple(targets[s].target_id for s in stops),
                coordinates=tuple(points[n] for n in path),
                estimated_distance_km=distance_km,
                # sailing time only, the trip back to port included. Cleanup time is
                # counted against available_hours but is not part of this number.
                estimated_travel_hours=travel_hours(distance_km, vessel.speed_m_per_s),
            )
        )

    unserved = [
        f"{t.target_id} ({unserved_reason(t, vessels, [km[v][n_vessels + i] for v in range(n_vessels)], config)})"
        for i, t in enumerate(targets)
        if i not in served
    ]
    notes = [
        provider.description,
        *provider.warnings,
        RETURN_NOTE,
        f"cleanup rate {config.recovery_rate_m3_per_hour:g} m3/h (assumed)",
        f"unserved: {', '.join(unserved) if unserved else 'none'}",
    ]
    # OR-Tools routing does not prove a plan is the best one, so we never say "optimal".
    return OptimizationOutput(routes=tuple(routes), status="feasible", message="; ".join(notes))


def _no_solution(routing: "pywrapcp.RoutingModel") -> OptimizationOutput:
    code = routing.status()
    if code == getattr(routing, "ROUTING_FAIL_TIMEOUT", 3):
        return OptimizationOutput(
            routes=(), status="not_solved", message="time limit reached before any plan was found"
        )
    if code in (getattr(routing, "ROUTING_FAIL", 2), getattr(routing, "ROUTING_INFEASIBLE", 5)):
        return OptimizationOutput(
            routes=(), status="infeasible", message="no plan satisfies the rules"
        )
    return OptimizationOutput(
        routes=(), status="error", message=f"OR-Tools returned status code {code}"
    )
