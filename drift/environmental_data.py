"""Interface for obtaining compatible local wind and current files."""

from datetime import datetime
from pathlib import Path

from shared.schemas import EnvironmentalData


def collect_environmental_data(
    bounds: tuple[float, float, float, float],
    start_time: datetime,
    end_time: datetime,
    output_dir: Path,
) -> EnvironmentalData:
    """Collect ERA5/Copernicus data; bounds are west, south, east, north degrees."""
    raise NotImplementedError("Implement authorized provider access and variable normalization.")
