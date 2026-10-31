"""Interface for comparing optimized plans with baseline methods."""

from shared.schemas import OptimizationOutput


def evaluate_routes(
    optimized: OptimizationOutput, baseline: OptimizationOutput
) -> dict[str, float]:
    """Compare distance (km), travel time (hours), and target coverage."""
    raise NotImplementedError("Implement fair comparisons under identical constraints.")
