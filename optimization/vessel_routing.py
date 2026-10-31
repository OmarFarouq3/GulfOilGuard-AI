"""Interface for cleanup routing with OR-Tools."""

from shared.schemas import OptimizationOutput, ResponseTarget, Vessel


def optimize_routes(
    vessels: tuple[Vessel, ...], targets: tuple[ResponseTarget, ...]
) -> OptimizationOutput:
    """Assign targets subject to vessel capacity, speed, and availability."""
    raise NotImplementedError("Implement constraints, travel costs, and routing.")
