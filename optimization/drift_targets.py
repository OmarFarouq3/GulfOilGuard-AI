"""Drift forecast in, MOVING cleanup targets out.

Reads the files the drift module writes for the dashboard (outputs/drift/, format in
dashboard/README.md "Drift module", and what routing needs on top in optimization/README.md):

  drift.geojson  features with a numeric `hours` property (hours since release). Point and
                 MultiPoint features are oil. Polygon envelopes are ignored here.
  meta.json      optional: simulation_id, start_time, n_particles, and the extensions
                 `release_volume_m3` (total oil released) and `summary_by_hour`, whose
                 `mean_water_fraction` per hour turns the pure oil into the emulsion a
                 vessel recovers (count_emulsion in config.py).

Optional feature properties (extensions; the dashboard ignores them):
  patch_id       the patch these points belong to. Same id at every step = same patch.
  particle_id    (Point) / particle_ids (MultiPoint, one per point): the OpenDrift particle
                 number, the same at every step. Lets us follow particles we grouped ourselves.
  status         OpenDrift particle status. Only "active" (or no status) is oil on the water.
  oil_volume_m3  oil the feature holds (a MultiPoint shares it equally between its points).
                 This is how weathering reaches the plan. Without it, every particle holds
                 release_volume_m3 / particles released.

How a patch is made and followed, in simple words:
  1. At the dispatch hour (when the vessels leave), cut the oil into patches: Maqqavi's
     patch_id if he gives one, otherwise ~3 km squares (cell_deg in config.py).
  2. Follow each patch through every later step: its place is the oil-weighted centre of
     the same points (same patch_id, or the same particle_ids), its oil is their sum.
  3. In between steps, move it in a straight line (PatchTrack.at). After the last step it
     stays where the last step put it.
  If the files have neither patch_id nor particle ids, nothing can be followed: the patches
  stay where they were at dispatch (static), and the plan says so.

The biggest patches become targets; the oil in the rest is reported as not targeted. A patch
that would fill more than the biggest tank at any later step (as emulsion, when known) is
split into equal parts that move together.

Emulsion: oil volumes in the drift files are pure oil, but weathered oil mixes with sea
water, so a vessel recovers oil / (1 - water fraction). The drift module gives the water
fraction as a slick average per hour (meta.json summary_by_hour), so every patch gets the
same fraction at the same hour, taken at the moment the vessel meets it.
"""

import json
from bisect import bisect_right
from dataclasses import dataclass, field
from math import ceil, floor, isfinite
from pathlib import Path
from typing import Callable, Hashable

from optimization.config import DEFAULT_DRIFT_CONFIG, REPO_ROOT, DriftTargetConfig
from optimization.limits import EmulsionTarget
from shared.schemas import GeoCoordinate, ResponseTarget

DEFAULT_DRIFT_DIR = REPO_ROOT / "outputs" / "drift"


@dataclass(frozen=True)
class Particle:
    location: GeoCoordinate
    volume_m3: float
    particle_id: str | None = None
    patch_id: str | None = None


@dataclass(frozen=True)
class DriftForecast:
    """The oil still on the water at every forecast step, keyed by hours since release."""

    steps: dict[float, tuple[Particle, ...]]
    simulation_id: str
    start_time: str | None
    synthetic: bool
    notes: tuple[str, ...]  # assumptions made while reading, for the plan's report
    # hours -> slick-average water fraction of the oil afloat (0 = pure oil). Empty when the
    # files do not give it for every step, or count_emulsion is off: tanks then take pure oil.
    water_fraction: dict[float, float] = field(default_factory=dict)


@dataclass(frozen=True)
class PatchTrack:
    """One cleanup target that moves with the oil: its place and its oil at each step."""

    target_id: str
    hours: tuple[float, ...]
    positions: tuple[GeoCoordinate, ...]
    volumes: tuple[float, ...]
    water_fractions: tuple[float, ...] = ()  # one per step; empty = unknown, tank takes pure oil

    def _bracket(self, hours: float) -> tuple[int, int, float]:
        """(i, j, f): `hours` lies f of the way from step i to step j; held outside the steps."""
        if hours <= self.hours[0]:
            return 0, 0, 0.0
        if hours >= self.hours[-1]:
            return len(self.hours) - 1, len(self.hours) - 1, 0.0
        k = bisect_right(self.hours, hours)  # hours[k-1] <= hours < hours[k]
        return k - 1, k, (hours - self.hours[k - 1]) / (self.hours[k] - self.hours[k - 1])

    def at(self, hours: float) -> tuple[GeoCoordinate, float]:
        """(place, oil m3) at any time: straight line between steps, held after the last."""
        i, j, f = self._bracket(hours)
        a, b = self.positions[i], self.positions[j]
        place = GeoCoordinate(
            latitude=a.latitude + f * (b.latitude - a.latitude),
            longitude=a.longitude + f * (b.longitude - a.longitude),
        )
        return place, self.volumes[i] + f * (self.volumes[j] - self.volumes[i])

    def water_fraction_at(self, hours: float) -> float | None:
        if not self.water_fractions:
            return None
        i, j, f = self._bracket(hours)
        return self.water_fractions[i] + f * (self.water_fractions[j] - self.water_fractions[i])

    def target_at(self, hours: float) -> ResponseTarget:
        """The patch as a vessel finds it then: with its emulsion when the water fraction is known."""
        place, volume = self.at(hours)
        water = self.water_fraction_at(hours)
        if water is None:
            return ResponseTarget(self.target_id, place, volume)
        return EmulsionTarget(self.target_id, place, volume, emulsion_m3=volume / (1 - water), water_fraction=water)


@dataclass(frozen=True)
class DriftPatches:
    tracks: tuple[PatchTrack, ...]
    dispatch_hours: float
    follow: str  # "patch_id", "particle_id" or "static" (nothing to follow)
    oil_afloat_m3: float  # all oil on the water at dispatch
    untargeted_m3: float  # oil in patches too small to make the target list


def _number(value, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{where}: needs a number")
    return float(value)


def _ids(props: dict, n_points: int, where: str) -> list[str | None]:
    if "particle_ids" in props:
        ids = props["particle_ids"]
        if not isinstance(ids, list) or len(ids) != n_points:
            raise ValueError(f"{where}: 'particle_ids' needs one id per point")
        return [str(i) for i in ids]
    if "particle_id" in props and n_points == 1:
        return [str(props["particle_id"])]
    return [None] * n_points


def load_drift(
    drift_dir: str | Path = DEFAULT_DRIFT_DIR, config: DriftTargetConfig = DEFAULT_DRIFT_CONFIG
) -> DriftForecast:
    """Read drift.geojson (and meta.json if present). Raises FileNotFoundError or ValueError."""
    drift_dir = Path(drift_dir)
    geojson_path = drift_dir / "drift.geojson"
    if not geojson_path.exists():
        raise FileNotFoundError(f"no drift forecast at {geojson_path}")
    collection = json.loads(geojson_path.read_text(encoding="utf-8"))
    meta_path = drift_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    synthetic = meta.get("synthetic") is True

    # hours -> [(points, particle ids, patch id, still on the water?, oil it holds or None)]
    groups: dict[float, list[tuple[list[GeoCoordinate], list, str | None, bool, float | None]]] = {}
    for i, feature in enumerate(collection.get("features", [])):
        where = f"drift.geojson feature {i}"
        props = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        if geometry.get("type") == "Point":
            raw_points = [geometry["coordinates"]]
        elif geometry.get("type") == "MultiPoint":
            raw_points = geometry["coordinates"]
        else:
            continue  # envelopes and anything else are for drawing, not for counting oil
        hours = _number(props.get("hours"), f"{where} 'hours'")
        if hours < 0:
            raise ValueError(f"{where}: 'hours' must be 0 or more")
        points = [
            GeoCoordinate(latitude=_number(p[1], where), longitude=_number(p[0], where))  # GeoJSON is lon, lat
            for p in raw_points
        ]
        volume = props.get("oil_volume_m3")
        if volume is not None:
            volume = _number(volume, f"{where} 'oil_volume_m3'")
        patch = props.get("patch_id")
        synthetic |= props.get("synthetic") is True
        groups.setdefault(hours, []).append((
            points, _ids(props, len(points), where), None if patch is None else str(patch),
            props.get("status", "active") == "active", volume,
        ))
    if not groups:
        raise ValueError(f"{geojson_path} has no particle (Point or MultiPoint) features")

    notes: list[str] = []
    share = None
    if any(volume is None for features in groups.values() for *_, volume in features):
        if "release_volume_m3" in meta:
            release = _number(meta["release_volume_m3"], "meta.json 'release_volume_m3'")
        else:
            release = config.release_volume_m3
            notes.append(f"release volume {release:g} m3 assumed (config.py)")
        first = groups[min(groups)]
        released = meta.get("n_particles") or sum(len(points) for points, *_ in first)
        share = release / _number(released, "meta.json 'n_particles'")
        notes.append("equal oil per particle, so weathering is not included")

    steps = {
        hours: tuple(
            Particle(point, volume / len(points) if volume is not None else share, pid, patch)
            for points, ids, patch, afloat, volume in features
            if afloat and points
            for point, pid in zip(points, ids)
        )
        for hours, features in sorted(groups.items())
    }
    water = _water_fractions(meta, steps, config, notes)
    return DriftForecast(
        steps=steps,
        simulation_id=str(meta.get("simulation_id") or drift_dir.name),
        start_time=meta.get("start_time"),
        synthetic=synthetic,
        notes=tuple(notes),
        water_fraction=water,
    )


def _water_fractions(meta: dict, steps, config: DriftTargetConfig, notes: list[str]) -> dict[float, float]:
    """{hours: water fraction} from meta.json summary_by_hour, or {} (and a note) if not usable."""
    if not config.count_emulsion:
        notes.append("tank use counted as pure oil (emulsion switched off)")
        return {}
    rows = meta.get("summary_by_hour")
    if not isinstance(rows, list):
        rows = []
    water: dict[float, float] = {}
    for i, row in enumerate(rows):
        if isinstance(row, dict) and "hours" in row and "mean_water_fraction" in row:
            where = f"meta.json summary_by_hour[{i}]"
            fraction = _number(row["mean_water_fraction"], f"{where} 'mean_water_fraction'")
            if not 0 <= fraction < 1:
                raise ValueError(f"{where}: 'mean_water_fraction' must be 0 or more and below 1")
            water[_number(row["hours"], f"{where} 'hours'")] = fraction
    missing = [h for h in steps if h not in water]
    if missing:
        notes.append("tank use counted as pure oil: meta.json gives no water fraction"
                     + (f" for {', '.join(f'{h:g}' for h in missing)} h" if water else ""))
        return {}
    notes.append("tank use and cleanup time counted as emulsion, oil / (1 - water fraction), with "
                 "the slick-average water fraction from meta.json at the meeting time (the same "
                 "for every patch); oil recovered is pure oil")
    return {h: water[h] for h in steps}


def particles_at(forecast: DriftForecast, hours: float) -> tuple[Particle, ...]:
    if hours not in forecast.steps:
        have = ", ".join(f"{h:g}" for h in forecast.steps)
        raise ValueError(f"no forecast step at {hours:g} h; the drift files have {have} h")
    return forecast.steps[hours]


def _patches(
    particles: tuple[Particle, ...], group_of: Callable[[Particle], Hashable]
) -> dict[Hashable, tuple[GeoCoordinate, float]]:
    """{patch key: (oil-weighted centre, oil m3)}. Particles whose key is None are left out."""
    members: dict[Hashable, list[Particle]] = {}
    for p in particles:
        key = group_of(p)
        if key is not None:
            members.setdefault(key, []).append(p)
    out = {}
    for key, ps in members.items():
        volume = sum(p.volume_m3 for p in ps)
        if volume > 0:
            out[key] = (
                GeoCoordinate(
                    latitude=sum(p.location.latitude * p.volume_m3 for p in ps) / volume,
                    longitude=sum(p.location.longitude * p.volume_m3 for p in ps) / volume,
                ),
                volume,
            )
    return out


def build_tracks(
    forecast: DriftForecast,
    dispatch_hours: float,
    config: DriftTargetConfig = DEFAULT_DRIFT_CONFIG,
    max_target_m3: float | None = None,
) -> DriftPatches:
    """Cut the oil into patches at dispatch and follow each one through the later steps.

    Pass the largest vessel tank as `max_target_m3` so no target is too big for every vessel,
    whenever it is met: the split uses the most the patch would fill a tank at any later step
    (emulsion grows as the oil takes up water). Target ids are Maqqavi's patch_id, or
    "T<rank>" (rank 01 = most oil at dispatch).
    """
    at_dispatch = particles_at(forecast, dispatch_hours)
    later = tuple(h for h in forecast.steps if h >= dispatch_hours)

    def cell_of(p: Particle) -> tuple[int, int]:
        return floor(p.location.latitude / config.cell_deg), floor(p.location.longitude / config.cell_deg)

    if at_dispatch and all(p.patch_id is not None for p in at_dispatch):
        follow, group_of = "patch_id", (lambda p: p.patch_id)
    elif at_dispatch and all(p.particle_id is not None for p in at_dispatch):
        cell_of_particle = {p.particle_id: cell_of(p) for p in at_dispatch}
        follow, group_of = "particle_id", (lambda p: cell_of_particle.get(p.particle_id))
    else:
        follow, group_of, later = "static", cell_of, (dispatch_hours,)

    by_step = {h: _patches(forecast.steps[h], group_of) for h in later}
    start = by_step[dispatch_hours]
    # Most oil first; the key breaks ties so the same input always gives the same ids.
    ranked = sorted(start, key=lambda key: (-start[key][1], str(key)))
    kept = ranked[: config.max_targets]

    water = tuple(forecast.water_fraction[h] for h in later) if forecast.water_fraction else ()
    tracks: list[PatchTrack] = []
    for rank, key in enumerate(kept, start=1):
        positions: list[GeoCoordinate] = []
        volumes: list[float] = []
        for h in later:
            # a patch that has left the water stays where it was last seen, with no oil
            place, volume = by_step[h].get(key, (positions[-1] if positions else start[key][0], 0.0))
            positions.append(place)
            volumes.append(volume)
        name = str(key) if follow == "patch_id" else f"T{rank:02d}"
        fullest = max(v / (1 - w) for v, w in zip(volumes, water)) if water else start[key][1]
        parts = max(1, ceil(fullest / max_target_m3 - 1e-9)) if max_target_m3 else 1
        for k in range(parts):
            tracks.append(PatchTrack(
                target_id=name if parts == 1 else f"{name}-{k + 1}",
                hours=later,
                positions=tuple(positions),
                volumes=tuple(v / parts for v in volumes),
                water_fractions=water,
            ))
    return DriftPatches(
        tracks=tuple(tracks),
        dispatch_hours=dispatch_hours,
        follow=follow,
        oil_afloat_m3=sum(p.volume_m3 for p in at_dispatch),
        untargeted_m3=sum(start[key][1] for key in ranked[config.max_targets :]),
    )
