"""OpenDrift oil-drift simulation. Nothing runs at import; OpenDrift is loaded when a run starts.

SYNTHETIC scenarios only: the release point and time are agreed test inputs, not a detection result.

`run_oil_drift` runs the model and returns the particles at every output hour (`DriftRun`).
`simulate_drift` keeps the shared-contract interface: it returns a `DriftOutput` holding the
hourly centre of the oil afloat. `drift/export_outputs.py` writes the particle files that the
routing and dashboard teams read (outputs/drift/).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import cos, isfinite, radians
from pathlib import Path

import numpy as np

from shared.schemas import DriftOutput, EnvironmentalData, GeoCoordinate, TimedPosition

KM_PER_DEG_LAT = 110.54
KM_PER_DEG_LON_EQUATOR = 111.32

# The current file must be the CLEANED one from drift/environmental_data.py: current = uo + utide,
# wave (Stokes) drift as separate variables. utotal/vtotal already contain the wave drift, so using
# them while OpenDrift also adds Stokes drift would count it twice.
PROVIDER_CURRENT_VARIABLES = ("uo", "vo", "utide", "vtide", "utotal", "vtotal")
REQUIRED_CURRENT_VARIABLES = (
    "x_sea_water_velocity", "y_sea_water_velocity",
    "sea_surface_wave_stokes_drift_x_velocity", "sea_surface_wave_stokes_drift_y_velocity",
)


@dataclass(frozen=True)
class DriftSettings:
    """Run settings. The defaults are the team's agreed synthetic Gulf scenario."""

    n_particles: int = 1000
    release_volume_m3: float = 300.0
    release_radius_m: float = 500.0
    oil_type: str = "GENERIC MEDIUM CRUDE"
    time_step_s: int = 900
    output_step_s: int = 3600
    seed: int = 42  # fixed so a run can be repeated exactly
    vertical_mixing: bool = False  # surface oil only; the cleanup targets are surface oil
    # ASSUMPTIONS, not data. Joud's files have no water temperature or salinity (OpenDrift would
    # use 10 C and 34) and no diffusion. The diffusivity gives the cloud a realistic width.
    sea_water_temperature_c: float = 28.0
    sea_water_salinity_psu: float = 40.0
    horizontal_diffusivity_m2_per_s: float = 10.0

    def __post_init__(self) -> None:
        if self.n_particles < 1:
            raise ValueError("n_particles must be at least 1")
        if self.release_volume_m3 <= 0 or self.release_radius_m < 0:
            raise ValueError("release_volume_m3 must be above 0 and release_radius_m 0 or more")
        if self.time_step_s < 1 or self.output_step_s < self.time_step_s or self.output_step_s % self.time_step_s:
            raise ValueError("output_step_s must be a whole multiple of time_step_s")
        if self.horizontal_diffusivity_m2_per_s < 0:
            raise ValueError("horizontal_diffusivity_m2_per_s must be 0 or more")


@dataclass(frozen=True, eq=False)
class DriftRun:
    """The particles at every output hour. Arrays are (particle, output step)."""

    settings: DriftSettings
    release: GeoCoordinate
    start_time: datetime  # timezone-aware UTC
    hours: np.ndarray  # hours since release, one per output step
    particle_ids: np.ndarray  # OpenDrift particle number; the same particle keeps its id
    lon: np.ndarray
    lat: np.ndarray
    status: np.ndarray  # index into status_names
    status_names: tuple[str, ...]  # "active" is always first
    mass_oil_kg: np.ndarray  # pure oil still held by each particle
    density_kg_m3: np.ndarray
    water_fraction: np.ndarray
    wind_x: np.ndarray  # m/s at each particle
    wind_y: np.ndarray
    current_x: np.ndarray
    current_y: np.ndarray
    released_mass_kg: float
    opendrift_version: str

    @property
    def n_particles(self) -> int:
        return int(self.lon.shape[0])

    @property
    def timestamps(self) -> tuple[datetime, ...]:
        return tuple(self.start_time + timedelta(hours=float(h)) for h in self.hours)

    def active(self, step: int) -> np.ndarray:
        """Particles still on the water at this output step."""
        return self.status[:, step] == self.status_names.index("active")

    def volume_m3(self, step: int, mask: np.ndarray | None = None) -> float:
        """Pure oil volume (mass / density) of the selected particles; all of them if no mask."""
        pick = np.ones(self.n_particles, dtype=bool) if mask is None else mask
        return float(np.sum(self.mass_oil_kg[pick, step] / self.density_kg_m3[pick, step]))

    def centre(self, step: int) -> GeoCoordinate:
        """Centre of the oil afloat (of all particles if none is afloat)."""
        pick = self.active(step)
        if not pick.any():
            pick = np.ones(self.n_particles, dtype=bool)
        return GeoCoordinate(latitude=float(self.lat[pick, step].mean()), longitude=float(self.lon[pick, step].mean()))


def _check_utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be a timezone-aware UTC datetime")


def environment_from_files(wind_path: Path, current_path: Path) -> EnvironmentalData:
    """EnvironmentalData for cleaned wind/current files, covering the time both files share."""
    import xarray as xr

    starts, ends = [], []
    for path in (Path(wind_path), Path(current_path)):
        if not path.exists():
            raise FileNotFoundError(f"environmental file not found: {path}")
        with xr.open_dataset(path) as ds:
            times = ds["time"].values.astype("datetime64[s]")
        starts.append(times.min().astype(datetime).replace(tzinfo=timezone.utc))
        ends.append(times.max().astype(datetime).replace(tzinfo=timezone.utc))
    return EnvironmentalData(Path(wind_path), Path(current_path), max(starts), min(ends))


def _check_current_file(path: Path) -> None:
    """Refuse a raw provider file or one without wave drift (see PROVIDER_CURRENT_VARIABLES)."""
    import xarray as xr

    with xr.open_dataset(path) as ds:
        names = set(ds.variables)
    provider = sorted(names & set(PROVIDER_CURRENT_VARIABLES))
    if provider:
        raise ValueError(
            f"{Path(path).name} still has the provider variables {provider}. Use the cleaned current file made by "
            "drift/environmental_data.py (utotal/vtotal would count the wave drift twice)."
        )
    missing = [v for v in REQUIRED_CURRENT_VARIABLES if v not in names]
    if missing:
        raise ValueError(f"{Path(path).name} is missing {missing}; the wave (Stokes) drift must come from the file.")


def _check_inputs(release: GeoCoordinate, start_time: datetime, env: EnvironmentalData, duration_hours: int,
                  settings: DriftSettings) -> None:
    if not (isfinite(release.latitude) and isfinite(release.longitude)) or not (
        -90 <= release.latitude <= 90 and -180 <= release.longitude <= 180
    ):
        raise ValueError(f"release point {release} is not a valid WGS84 coordinate")
    _check_utc(start_time, "start_time")
    _check_utc(env.start_time, "environmental_data.start_time")
    _check_utc(env.end_time, "environmental_data.end_time")
    if duration_hours < 1 or int(duration_hours) != duration_hours:
        raise ValueError("duration_hours must be a whole number of hours, at least 1")
    if (duration_hours * 3600) % settings.output_step_s:
        raise ValueError("duration_hours must be a whole multiple of the output step")
    end_time = start_time + timedelta(hours=duration_hours)
    if start_time < env.start_time or end_time > env.end_time:
        raise ValueError(
            f"the run {start_time:%Y-%m-%d %H:%M} to {end_time:%Y-%m-%d %H:%M} UTC is not inside the "
            f"environmental data window {env.start_time:%Y-%m-%d %H:%M} to {env.end_time:%Y-%m-%d %H:%M} UTC"
        )
    for path in (env.wind_path, env.current_path):
        if not Path(path).exists():
            raise FileNotFoundError(f"environmental file not found: {path}")
    _check_current_file(Path(env.current_path))


def run_oil_drift(
    release: GeoCoordinate,
    start_time: datetime,
    environmental_data: EnvironmentalData,
    duration_hours: int = 24,
    settings: DriftSettings = DriftSettings(),
) -> DriftRun:
    """Release oil at one point and follow the particles for `duration_hours`, one output per hour.

    Wind comes from ERA5, currents (ocean + tide) and wave (Stokes) drift from Copernicus Marine.
    OpenDrift's own NetCDF output file is not used: results stay in memory.
    """
    _check_inputs(release, start_time, environmental_data, duration_hours, settings)

    from opendrift import __version__ as opendrift_version
    from opendrift.models.openoil import OpenOil
    from opendrift.readers import reader_netCDF_CF_generic as readers

    np.random.seed(settings.seed)  # OpenDrift draws from NumPy's global generator
    model = OpenOil(loglevel=30)  # warnings only
    model.add_reader([
        readers.Reader(str(environmental_data.wind_path)),
        readers.Reader(str(environmental_data.current_path)),
    ])
    model.set_config("drift:vertical_mixing", settings.vertical_mixing)
    model.set_config("drift:stokes_drift", True)  # the current file already holds wave drift
    model.set_config("processes:evaporation", True)
    model.set_config("processes:emulsification", True)
    model.set_config("processes:dispersion", True)
    model.set_config("environment:fallback:sea_water_temperature", settings.sea_water_temperature_c)
    model.set_config("environment:fallback:sea_water_salinity", settings.sea_water_salinity_psu)
    model.set_config("environment:fallback:horizontal_diffusivity", settings.horizontal_diffusivity_m2_per_s)

    # Instantaneous release: total volume = m3_per_hour x 1 h, shared equally by the particles.
    model.seed_elements(
        lon=release.longitude, lat=release.latitude, radius=settings.release_radius_m,
        number=settings.n_particles, time=start_time.astimezone(timezone.utc).replace(tzinfo=None), z=0,
        oil_type=settings.oil_type, m3_per_hour=settings.release_volume_m3,
    )
    model.run(duration=timedelta(hours=duration_hours), time_step=settings.time_step_s,
              time_step_output=settings.output_step_s)
    return _collect(model, release, start_time, settings, opendrift_version)


def _collect(model, release: GeoCoordinate, start_time: datetime, settings: DriftSettings,
             opendrift_version: str) -> DriftRun:
    ds = model.result.load()

    def values(name: str) -> np.ndarray:
        # A particle that stops (stranded, ...) keeps its last values from then on.
        return ds[name].ffill(dim="time").values.astype(float)

    status = values("status")
    if np.isnan(status).any():
        raise RuntimeError("OpenDrift result has particles without a status")
    hours = (ds["time"].values - ds["time"].values[0]) / np.timedelta64(1, "h")
    mass = values("mass_oil")
    return DriftRun(
        settings=settings,
        release=release,
        start_time=start_time,
        hours=hours.astype(float),
        particle_ids=ds["trajectory"].values.astype(int),
        lon=values("lon"),
        lat=values("lat"),
        status=np.rint(status).astype(int),
        status_names=tuple(model.status_categories),
        mass_oil_kg=mass,
        density_kg_m3=values("density"),
        water_fraction=values("water_fraction"),
        wind_x=values("x_wind"),
        wind_y=values("y_wind"),
        current_x=values("x_sea_water_velocity"),
        current_y=values("y_sea_water_velocity"),
        released_mass_kg=float(np.nansum(mass[:, 0])),
        opendrift_version=opendrift_version,
    )


def default_simulation_id(release: GeoCoordinate, start_time: datetime) -> str:
    return f"openoil-{release.latitude:.2f}N-{release.longitude:.2f}E-{start_time:%Y%m%dT%H%M}Z"


def drift_output_from_run(run: DriftRun, simulation_id: str | None = None) -> DriftOutput:
    """The shared-contract view: the hourly centre of the oil afloat as one timed trajectory."""
    return DriftOutput(
        simulation_id=simulation_id or default_simulation_id(run.release, run.start_time),
        initial_location=run.release,
        positions=tuple(TimedPosition(timestamp=t, coordinate=run.centre(i)) for i, t in enumerate(run.timestamps)),
        duration_hours=float(run.hours[-1]),
    )


def simulate_drift(
    initial_location: GeoCoordinate,
    start_time: datetime,
    environmental_data: EnvironmentalData,
    duration_hours: int = 24,
) -> DriftOutput:
    """Simulate a georeferenced release and return the hourly centre of the oil as `DriftOutput`.

    For the particles themselves (what routing needs) use `run_oil_drift` and
    `drift.export_outputs.write_drift_outputs`.
    """
    return drift_output_from_run(run_oil_drift(initial_location, start_time, environmental_data, duration_hours))


def hourly_summary(run: DriftRun) -> list[dict]:
    """One row per output hour: particle counts, where the oil centre is and how wide it is."""
    km_per_deg_lon = KM_PER_DEG_LON_EQUATOR * cos(radians(run.release.latitude))
    rows = []
    for i, hour in enumerate(run.hours):
        afloat = run.active(i)
        row = {
            "hours": float(hour),
            "active": int(afloat.sum()),
            "stranded_or_other": int((~afloat).sum()),
            "oil_afloat_m3": round(run.volume_m3(i, afloat), 2),
        }
        if afloat.any():
            east = (run.lon[afloat, i] - run.release.longitude) * km_per_deg_lon
            north = (run.lat[afloat, i] - run.release.latitude) * KM_PER_DEG_LAT
            row.update(
                centre_east_km=round(float(east.mean()), 2), centre_north_km=round(float(north.mean()), 2),
                sd_east_km=round(float(east.std()), 2), sd_north_km=round(float(north.std()), 2),
                mean_water_fraction=round(float(run.water_fraction[afloat, i].mean()), 3),
            )
        rows.append(row)
    return rows
