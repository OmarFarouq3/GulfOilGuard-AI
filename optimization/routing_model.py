"""The OR-Tools model for cleanup routing.

What the model enforces now:
  - vessel capacity (a vessel never takes more oil than its tank)
  - working hours (sailing + cleanup time must fit inside `available_hours`)
  - open routes (the schema has no end port, so vessels do not come back)
  - skipping: any target may be left out, but at a very high cost
  - distances through navigable water when the land file exists (otherwise straight
    lines, and the plan's `message` says so)

What the model aims for, most important first (weights in config.py):
  1. recover the most oil (skipping a target costs more the more oil it holds)
  2. finish the whole response early (the time the LAST vessel is done)
  3. sail the fewest km

NOT done yet: risk and deadlines (Phase 7), drift (Phase 8).

How the model is laid out (the "school bus" picture):
  nodes 0 .. V-1        the start position of each vessel (one bus, one start)
  nodes V .. V+T-1      the oil targets (the students waiting)
  node  V+T             a fake "end" node, 0 km from everything, so a vessel
                        does not have to come back (the schema has no end port)
"""

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from optimization.checks import early_result
from optimization.config import DEFAULT_CONFIG, RoutingConfig
from optimization.limits import leg_minutes, minutes_down, service_minutes, unserved_reason
from optimization.sea_distance import DistanceProvider, default_provider
from optimization.units import km_to_metres, travel_hours, volume_to_units
from shared.schemas import (
    OptimizationOutput,
    ResponseTarget,
    Vessel,
    VesselRoute,
)


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
    n_real = len(points)
    end_node = n_real
    n_nodes = n_real + 1

    km = provider.matrix_km(points, labels)

    # Whole-number distance table in metres. The fake end node is 0 away from all.
    dist_m = [[0] * n_nodes for _ in range(n_nodes)]
    for i in range(n_real):
        for j in range(n_real):
            dist_m[i][j] = km_to_metres(km[i][j])

    demand = [0] * n_nodes
    cleanup_min = [0] * n_nodes
    for t_idx, target in enumerate(targets):
        demand[n_vessels + t_idx] = volume_to_units(target.oil_volume_m3, config.volume_scale)
        cleanup_min[n_vessels + t_idx] = service_minutes(target.oil_volume_m3, config)
    capacities = [volume_to_units(v.capacity_m3, config.volume_scale) for v in vessels]

    manager = pywrapcp.RoutingIndexManager(
        n_nodes, n_vessels, list(range(n_vessels)), [end_node] * n_vessels
    )
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
        minutes = [
            [
                leg_minutes(km[i][j], speed) if i < n_real and j < n_real else 0
                for j in range(n_nodes)
            ]
            for i in range(n_nodes)
        ]

        def time_callback(from_index: int, to_index: int) -> int:
            a = manager.IndexToNode(from_index)
            b = manager.IndexToNode(to_index)
            return minutes[a][b] + cleanup_min[a]

        return time_callback

    time_indices = [routing.RegisterTransitCallback(make_time_callback(v)) for v in range(n_vessels)]
    hour_limits = [minutes_down(v.available_hours) for v in vessels]
    routing.AddDimensionWithVehicleTransitAndCapacity(time_indices, 0, hour_limits, True, "Time")

    # --- goal 2: finish early. The "span" is the time the last vessel is done. The cost is
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
            if node >= n_vessels:  # starts are below V, the fake end is never visited here
                stops.append(node - n_vessels)
            index = solution.Value(routing.NextVar(index))

        served.update(stops)
        path = [v_idx] + [n_vessels + s for s in stops]
        distance_km = sum(km[a][b] for a, b in zip(path, path[1:]))
        routes.append(
            VesselRoute(
                vessel_id=vessel.vessel_id,
                assigned_target_ids=tuple(targets[s].target_id for s in stops),
                coordinates=tuple(points[n] for n in path),
                estimated_distance_km=distance_km,
                # sailing time only. Cleanup time is counted against available_hours
                # but is not part of this number.
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
