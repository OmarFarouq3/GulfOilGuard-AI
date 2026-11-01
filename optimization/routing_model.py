"""The OR-Tools model for cleanup routing.

PHASE 1 (now): vessel capacity + open routes + skipping with a penalty.
NOT enforced yet: available_hours and cleanup time (Phase 3), navigable water
(Phase 2), risk and deadlines (Phase 7), drift (Phase 8).

How the model is laid out (the "school bus" picture):
  nodes 0 .. V-1        the start position of each vessel (one bus, one start)
  nodes V .. V+T-1      the oil targets (the students waiting)
  node  V+T             a fake "end" node, 0 km from everything, so a vessel
                        does not have to come back (the schema has no end port)
"""

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from optimization.checks import validate_inputs
from optimization.config import DEFAULT_CONFIG, RoutingConfig
from optimization.sea_distance import DistanceProvider, StraightLineDistance
from optimization.units import km_to_metres, travel_hours, volume_to_units
from shared.schemas import (
    OptimizationOutput,
    ResponseTarget,
    Vessel,
    VesselRoute,
)

LIMITS_NOTE = "phase 1: available_hours and cleanup time are not enforced yet"


def solve_routes(
    vessels: tuple[Vessel, ...],
    targets: tuple[ResponseTarget, ...],
    config: RoutingConfig = DEFAULT_CONFIG,
    distance_provider: DistanceProvider | None = None,
) -> OptimizationOutput:
    """Plan routes. Never raises: problems come back in `status` and `message`."""
    provider = distance_provider or StraightLineDistance()

    problems = validate_inputs(vessels, targets)
    if problems:
        return OptimizationOutput(
            routes=(), status="error", message="invalid input: " + "; ".join(problems)
        )
    if not targets:
        return OptimizationOutput(
            routes=tuple(_idle_route(v) for v in vessels),
            status="feasible",
            message="no targets to serve",
        )
    if not vessels:
        return OptimizationOutput(
            routes=(), status="infeasible", message="no vessels available"
        )

    try:
        return _solve(vessels, targets, config, provider)
    except Exception as exc:  # keep the dashboard alive, but say what happened
        return OptimizationOutput(
            routes=(),
            status="error",
            message=f"solver failed: {type(exc).__name__}: {exc}",
        )


def _idle_route(vessel: Vessel) -> VesselRoute:
    return VesselRoute(
        vessel_id=vessel.vessel_id,
        assigned_target_ids=(),
        coordinates=(vessel.location,),
        estimated_distance_km=0.0,
        estimated_travel_hours=0.0,
    )


def _solve(
    vessels: tuple[Vessel, ...],
    targets: tuple[ResponseTarget, ...],
    config: RoutingConfig,
    provider: DistanceProvider,
) -> OptimizationOutput:
    n_vessels, n_targets = len(vessels), len(targets)
    points = [v.location for v in vessels] + [t.location for t in targets]
    n_real = len(points)
    end_node = n_real
    n_nodes = n_real + 1

    km = provider.matrix_km(points)

    # Whole-number distance table in metres. The fake end node is 0 away from all.
    dist_m = [[0] * n_nodes for _ in range(n_nodes)]
    for i in range(n_real):
        for j in range(n_real):
            dist_m[i][j] = km_to_metres(km[i][j])

    demand = [0] * n_nodes
    for t_idx, target in enumerate(targets):
        demand[n_vessels + t_idx] = volume_to_units(
            target.oil_volume_m3, config.volume_scale
        )
    capacities = [volume_to_units(v.capacity_m3, config.volume_scale) for v in vessels]

    manager = pywrapcp.RoutingIndexManager(
        n_nodes, n_vessels, list(range(n_vessels)), [end_node] * n_vessels
    )
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index: int, to_index: int) -> int:
        return dist_m[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

    transit_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_index)

    def demand_callback(from_index: int) -> int:
        return demand[manager.IndexToNode(from_index)]

    demand_index = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_index, 0, capacities, True, "Capacity"
    )

    # Every target may be skipped, but skipping costs a lot.
    penalty = config.drop_penalty_km * 1000
    for t_idx in range(n_targets):
        routing.AddDisjunction([manager.NodeToIndex(n_vessels + t_idx)], penalty)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
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
            if (
                node >= n_vessels
            ):  # starts are below V, the fake end is never visited here
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
                estimated_travel_hours=travel_hours(distance_km, vessel.speed_m_per_s),
            )
        )

    unserved = [t.target_id for i, t in enumerate(targets) if i not in served]
    message = (
        f"{provider.description}; "
        f"unserved: {', '.join(unserved) if unserved else 'none'}; "
        f"{LIMITS_NOTE}"
    )
    # OR-Tools routing does not prove a plan is the best one, so we never say "optimal".
    return OptimizationOutput(routes=tuple(routes), status="feasible", message=message)


def _no_solution(routing: "pywrapcp.RoutingModel") -> OptimizationOutput:
    code = routing.status()
    if code == getattr(routing, "ROUTING_FAIL_TIMEOUT", 3):
        return OptimizationOutput(
            routes=(),
            status="not_solved",
            message="time limit reached before any plan was found",
        )
    if code in (
        getattr(routing, "ROUTING_FAIL", 2),
        getattr(routing, "ROUTING_INFEASIBLE", 5),
    ):
        return OptimizationOutput(
            routes=(), status="infeasible", message="no plan satisfies the rules"
        )
    return OptimizationOutput(
        routes=(), status="error", message=f"OR-Tools returned status code {code}"
    )
