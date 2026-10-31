"""OpenDrift interface; no simulation runs during import."""

from datetime import datetime

from shared.schemas import DriftOutput, EnvironmentalData, GeoCoordinate


def simulate_drift(
    initial_location: GeoCoordinate,
    start_time: datetime,
    environmental_data: EnvironmentalData,
    duration_hours: int = 24,
) -> DriftOutput:
    """Simulate a georeferenced release for a planned 6, 12, or 24 hour horizon."""
    raise NotImplementedError("Implement OpenDrift configuration and trajectory export.")
