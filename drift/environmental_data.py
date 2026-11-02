"""Interface for obtaining compatible local wind and current files.

Provider files are downloaded manually (see drift/DATA_SOURCES.md) and kept in the
ignored data/ folder. This module checks them and writes OpenDrift-ready copies.

Choice to avoid double counting:
- current    = uo + utide        (ocean circulation + tides)
- wave drift = vsdx, vsdy        (OpenDrift adds Stokes drift itself)
- utotal/vtotal are NOT used     (they already contain uo + utide + Stokes drift)
"""

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import xarray as xr

from shared.schemas import EnvironmentalData

DEFAULT_RAW_WIND = Path("data/era5_wind_gulf_2026-10-19_26.nc")
DEFAULT_RAW_CURRENT = Path("data/cmems_currents_gulf_2026-10-19_26.nc")

SPEED_UNITS = "m s-1"


def _to_utc_numpy(t: datetime) -> np.datetime64:
    """Convert a timezone-aware datetime to a naive UTC numpy datetime."""
    if t.tzinfo is None:
        raise ValueError("start_time and end_time must be timezone-aware UTC datetimes.")
    return np.datetime64(t.astimezone(timezone.utc).replace(tzinfo=None), "ns")


def _check_coverage(ds: xr.Dataset, label: str, bounds, start, end) -> None:
    """Raise ValueError if the dataset does not cover the area and time window."""
    west, south, east, north = bounds
    lon = ds["longitude"].values
    lat = ds["latitude"].values
    # Allow one grid step of tolerance at the edges (grids rarely land exactly on the bounds).
    step_lon = float(np.abs(np.diff(lon)).max())
    step_lat = float(np.abs(np.diff(lat)).max())
    if (west < lon.min() - step_lon or east > lon.max() + step_lon
            or south < lat.min() - step_lat or north > lat.max() + step_lat):
        raise ValueError(
            f"{label}: data covers lon {lon.min():.2f}-{lon.max():.2f}, "
            f"lat {lat.min():.2f}-{lat.max():.2f}, which does not cover bounds {bounds}."
        )

    times = ds["time"].values
    if start < times[0] or end > times[-1]:
        raise ValueError(f"{label}: data covers {times[0]} to {times[-1]}, not {start} to {end}.")
    window = ds["time"].sel(time=slice(start, end)).values
    gaps = np.diff(window)
    if not (gaps == np.timedelta64(1, "h")).all():
        raise ValueError(f"{label}: time steps are not hourly without gaps.")


def _label_coords(ds: xr.Dataset) -> xr.Dataset:
    ds["latitude"].attrs.update(standard_name="latitude", units="degrees_north")
    ds["longitude"].attrs.update(standard_name="longitude", units="degrees_east")
    ds["time"].attrs.update(standard_name="time")
    return ds


def _normalize_wind(raw_path: Path, start, end) -> xr.Dataset:
    ds = xr.open_dataset(raw_path)
    if "valid_time" in ds.variables:  # new ERA5 files use valid_time
        ds = ds.rename({"valid_time": "time"})
    ds = ds.drop_vars(["number", "expver"], errors="ignore").sortby("latitude")
    ds = ds.sel(time=slice(start, end))

    out = xr.Dataset({"x_wind": ds["u10"], "y_wind": ds["v10"]})
    out["x_wind"].attrs = {"standard_name": "x_wind", "units": SPEED_UNITS,
                           "long_name": "10 m eastward wind (ERA5 u10)"}
    out["y_wind"].attrs = {"standard_name": "y_wind", "units": SPEED_UNITS,
                           "long_name": "10 m northward wind (ERA5 v10)"}
    out.attrs = {"source": "ERA5 hourly data on single levels (Copernicus Climate Change Service)",
                 "note": "Recent days may be preliminary ERA5T data."}
    return _label_coords(out)


def _normalize_current(raw_path: Path, start, end) -> xr.Dataset:
    ds = xr.open_dataset(raw_path)
    if "depth" in ds.dims:
        ds = ds.isel(depth=0, drop=True)  # surface layer only
    ds = ds.sortby("latitude").sel(time=slice(start, end))

    out = xr.Dataset({
        "x_sea_water_velocity": ds["uo"] + ds["utide"],
        "y_sea_water_velocity": ds["vo"] + ds["vtide"],
        "sea_surface_wave_stokes_drift_x_velocity": ds["vsdx"],
        "sea_surface_wave_stokes_drift_y_velocity": ds["vsdy"],
    })
    long_names = {
        "x_sea_water_velocity": "eastward current: ocean circulation + tide (uo + utide)",
        "y_sea_water_velocity": "northward current: ocean circulation + tide (vo + vtide)",
        "sea_surface_wave_stokes_drift_x_velocity": "eastward Stokes (wave) drift (vsdx)",
        "sea_surface_wave_stokes_drift_y_velocity": "northward Stokes (wave) drift (vsdy)",
    }
    for name, long_name in long_names.items():
        out[name].attrs = {"standard_name": name, "units": SPEED_UNITS, "long_name": long_name}
    out.attrs = {"source": "Copernicus Marine GLOBAL_ANALYSISFORECAST_PHY_001_024, "
                           "cmems_mod_glo_phy_anfc_merged-uv_PT1H-i",
                 "note": "utotal/vtotal excluded to avoid double counting tides and Stokes drift."}
    return _label_coords(out)


def collect_environmental_data(
    bounds: tuple[float, float, float, float],
    start_time: datetime,
    end_time: datetime,
    output_dir: Path,
    raw_wind_path: Path = DEFAULT_RAW_WIND,
    raw_current_path: Path = DEFAULT_RAW_CURRENT,
) -> EnvironmentalData:
    """Collect ERA5/Copernicus data; bounds are west, south, east, north degrees.

    Reads manually downloaded provider files, checks area/time coverage, normalizes
    variable names for OpenDrift and writes clean copies to output_dir.
    """
    if start_time >= end_time:
        raise ValueError("start_time must be before end_time.")
    start, end = _to_utc_numpy(start_time), _to_utc_numpy(end_time)

    wind = _normalize_wind(Path(raw_wind_path), start, end)
    current = _normalize_current(Path(raw_current_path), start, end)
    _check_coverage(wind, "Wind (ERA5)", bounds, start, end)
    _check_coverage(current, "Currents (Copernicus Marine)", bounds, start, end)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    wind_path = output_dir / "wind_clean.nc"
    current_path = output_dir / "currents_clean.nc"
    wind.to_netcdf(wind_path)
    current.to_netcdf(current_path)

    return EnvironmentalData(
        wind_path=wind_path,
        current_path=current_path,
        start_time=start_time,
        end_time=end_time,
    )


if __name__ == "__main__":
    # Team B demo region: northern UAE coast, 19-26 Oct 2026 (see drift/DATA_SOURCES.md).
    env = collect_environmental_data(
        bounds=(55.0, 24.75, 57.0, 27.0),
        start_time=datetime(2026, 10, 19, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 10, 26, 23, tzinfo=timezone.utc),
        output_dir=Path("data/processed"),
    )
    print("Clean files ready:")
    print("  wind:   ", env.wind_path)
    print("  current:", env.current_path)
    print("  from", env.start_time, "to", env.end_time)
