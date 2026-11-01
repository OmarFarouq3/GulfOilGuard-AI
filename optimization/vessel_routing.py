"""Interface for cleanup routing with OR-Tools."""

from optimization.routing_model import solve_routes
from shared.schemas import OptimizationOutput, ResponseTarget, Vessel


def optimize_routes(
    vessels: tuple[Vessel, ...], targets: tuple[ResponseTarget, ...]
) -> OptimizationOutput:
    """Assign targets subject to vessel capacity, speed, and availability.

    Same name and inputs as the original interface. The settings live in
    optimization/config.py and the details in optimization/routing_model.py.
    """
    return solve_routes(vessels, targets)
