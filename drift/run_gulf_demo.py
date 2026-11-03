"""Run the team's agreed first Gulf oil-drift scenario and write outputs/drift/.

SYNTHETIC: release point 25.85 N, 55.65 E, Generic Medium Crude, 300 m3, 24 hours from
2026-10-23 12:00 UTC (inside Joud's data window). Nothing here is a detection or a measured spill.

Run from the repository root with the cleaned files in data/processed/:
    python -m drift.run_gulf_demo
Then, for the cleanup plan:
    python -m optimization.run_drift_plan
"""

import argparse
from datetime import datetime
from pathlib import Path

from drift.export_outputs import write_drift_outputs
from drift.simulate_drift import DriftSettings, environment_from_files, hourly_summary, run_oil_drift
from shared.schemas import GeoCoordinate

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_START = "2026-10-23T12:00:00Z"


def _parse_utc(text: str) -> datetime:
    moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise argparse.ArgumentTypeError(f"{text!r} needs a time zone: write UTC times like {DEFAULT_START}")
    return moment


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", type=_parse_utc, default=_parse_utc(DEFAULT_START), help="release time, UTC")
    parser.add_argument("--hours", type=int, default=24, help="duration in whole hours")
    parser.add_argument("--lat", type=float, default=25.85)
    parser.add_argument("--lon", type=float, default=55.65)
    parser.add_argument("--particles", type=int, default=DriftSettings.n_particles)
    parser.add_argument("--volume", type=float, default=DriftSettings.release_volume_m3, help="released oil, m3")
    parser.add_argument("--diffusivity", type=float, default=DriftSettings.horizontal_diffusivity_m2_per_s,
                        help="horizontal diffusivity, m2/s (an assumption)")
    parser.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data" / "processed")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "outputs" / "drift")
    args = parser.parse_args(argv)

    settings = DriftSettings(n_particles=args.particles, release_volume_m3=args.volume,
                             horizontal_diffusivity_m2_per_s=args.diffusivity)
    environment = environment_from_files(args.data_dir / "wind_clean.nc", args.data_dir / "currents_clean.nc")
    print(f"Environmental data cover {environment.start_time:%Y-%m-%d %H:%M} to {environment.end_time:%Y-%m-%d %H:%M} UTC")

    release = GeoCoordinate(latitude=args.lat, longitude=args.lon)
    run = run_oil_drift(release, args.start, environment, args.hours, settings)
    geojson_path, meta_path = write_drift_outputs(run, args.out_dir)

    print(f"\nSYNTHETIC run: {settings.oil_type}, {settings.release_volume_m3:g} m3, {run.n_particles} particles, "
          f"release {args.lat} N, {args.lon} E at {args.start:%Y-%m-%d %H:%M} UTC, {args.hours} h")
    print(f"{'hour':>4} {'afloat':>6} {'other':>5} | {'centre E km':>11} {'N km':>6} | {'sd E km':>7} {'sd N km':>7} | {'oil m3':>7}")
    for row in hourly_summary(run):
        if row["hours"] in (0, 6, 12, 18, 24) or row["hours"] == run.hours[-1]:
            print(f"{row['hours']:>4g} {row['active']:>6} {row['stranded_or_other']:>5} | "
                  f"{row.get('centre_east_km', float('nan')):>11.1f} {row.get('centre_north_km', float('nan')):>6.1f} | "
                  f"{row.get('sd_east_km', float('nan')):>7.2f} {row.get('sd_north_km', float('nan')):>7.2f} | "
                  f"{row['oil_afloat_m3']:>7.1f}")
    print(f"\nWrote {geojson_path}\n      {meta_path}")


if __name__ == "__main__":
    main()
