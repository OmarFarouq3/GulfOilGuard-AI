"""Independent check of a cleanup plan made from a drift forecast (Nihal, scenario validation).

Reads what the pipeline already wrote and checks it again from the raw files, without
OR-Tools, so it can be run by anyone who has the outputs:

  outputs/drift/drift.geojson, meta.json        Maqqavi's OpenDrift run
  outputs/routing/{routes,targets}.geojson,     Haris's plan (run_drift_plan)
  summary.json, comparison.json, baseline/
  optimization/fixtures/gulf_standard.json      the fleet (Nihal)

What is checked, in five groups:
  A. drift input    particle ids unique per step (no oil counted twice), oil afloat per step
                    equals meta.json, oil only goes down, the 0/6/12/24 h steps are there
  B. targets        every particle afloat at dispatch is in exactly one patch (targeted +
                    untargeted = afloat), split parts add up to their patch, targets.geojson
                    matches the patches rebuilt from the drift, how spread out each patch is
  C. fleet          ports are known depots (Port Saqr, Hamriyah), speeds and tanks
  D. routes         start and end at the home port, tank and cleanup time (as emulsion when
                    the plan counted it, see tank_basis in comparison.json; else pure oil, with
                    the emulsion as a warning), sailing time = distance / speed, distance no
                    shorter than a straight line, finish_hours = sailing + cleanup, working
                    hours, no target served twice, served_by agrees, unserved
  E. comparison     rule violations, and every metric in comparison.json recalculated from the
                    route and target files (not taken from the file)

Every line is OK, WARN (plausible but an assumption to state) or FAIL (a broken rule).
Run from the repository root:
    python -m optimization.validate_cleanup
    python -m optimization.validate_cleanup --json outputs/routing/validation.json
    python -m optimization.validate_cleanup --synthetic-fixture optimization/fixtures/gulf_drift_t12.json
"""

import argparse
import json
from dataclasses import replace
from datetime import datetime, timedelta
from math import cos, hypot, isnan, radians
from pathlib import Path

from optimization.config import DEFAULT_CONFIG, DEFAULT_DRIFT_CONFIG, REPO_ROOT
from optimization.drift_targets import build_tracks, load_drift
from optimization.scenario import GULF_DEPOTS
from optimization.scenario_io import load_scenario
from shared.schemas import GeoCoordinate

KNOTS_PER_M_PER_S = 1.943844
VOLUME_TOL = 0.01  # m3: files round volumes to 3 decimals
SPREAD_WARN_KM = 1.5  # a patch wider than this is not one skimming position
EMULSION_TOL = 0.001  # share: meet_hours is rounded to 0.01 h, which moves the water fraction a little


def _water_at(water: dict[float, float], hours: float) -> float | None:
    """Water fraction at any time: straight line between the hourly values, held outside them."""
    if not water:
        return None
    steps = sorted(water)
    if hours <= steps[0]:
        return water[steps[0]]
    if hours >= steps[-1]:
        return water[steps[-1]]
    i = next(k for k in range(1, len(steps)) if steps[k] > hours)
    a, b = steps[i - 1], steps[i]
    return water[a] + (hours - a) / (b - a) * (water[b] - water[a])


class Report:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, group: str, level: str, text: str) -> None:
        self.rows.append({"group": group, "level": level, "text": text})

    def ok(self, group, text):
        self.add(group, "OK", text)

    def warn(self, group, text):
        self.add(group, "WARN", text)

    def fail(self, group, text):
        self.add(group, "FAIL", text)

    def check(self, group, passed: bool, text: str, level_if_not: str = "FAIL") -> bool:
        self.add(group, "OK" if passed else level_if_not, text)
        return passed

    def counts(self) -> dict[str, int]:
        return {lvl: sum(r["level"] == lvl for r in self.rows) for lvl in ("OK", "WARN", "FAIL")}


def _km(a: GeoCoordinate, b: GeoCoordinate) -> float:
    """Flat-earth km: plenty for distances of a few km inside a patch."""
    north = (a.latitude - b.latitude) * 111.2
    east = (a.longitude - b.longitude) * 111.2 * cos(radians((a.latitude + b.latitude) / 2))
    return hypot(north, east)


def _line_km(coords) -> float:
    """Length of a [[lon, lat], ...] line, straight between its points."""
    return sum(_km(_point(a), _point(b)) for a, b in zip(coords, coords[1:]))


def _point(coords) -> GeoCoordinate:
    return GeoCoordinate(latitude=coords[1], longitude=coords[0])


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


# --- A. drift input -------------------------------------------------------------------------


def check_drift(drift_dir: Path, r: Report) -> dict:
    g = "A drift"
    collection = _read(drift_dir / "drift.geojson")
    meta = _read(drift_dir / "meta.json") if (drift_dir / "meta.json").exists() else {}
    r.check(g, meta.get("synthetic") is True, "meta.json is labelled synthetic (release point is a test point)")

    by_step: dict[float, dict[str, list]] = {}
    for f in collection["features"]:
        geom, props = f.get("geometry") or {}, f.get("properties") or {}
        if geom.get("type") not in ("Point", "MultiPoint"):
            continue
        ids = props.get("particle_ids") or ([props["particle_id"]] if "particle_id" in props else [])
        step = by_step.setdefault(float(props["hours"]), {"ids": [], "active_m3": 0.0, "timestamps": set()})
        step["ids"] += [str(i) for i in ids]
        if props.get("timestamp"):
            step["timestamps"].add(props["timestamp"])
        if props.get("status", "active") == "active":
            step["active_m3"] += props.get("oil_volume_m3", 0.0)

    hours = sorted(by_step)
    r.check(g, all(h in by_step for h in (0, 6, 12, 24)), f"forecast steps 0, 6, 12, 24 h present ({len(hours)} steps, "
            f"{hours[0]:g} to {hours[-1]:g} h)")

    dupes = {h: len(s["ids"]) - len(set(s["ids"])) for h, s in by_step.items()}
    r.check(g, not any(dupes.values()), "every particle appears once per step (no oil counted twice)"
            + ("" if not any(dupes.values()) else f": duplicates at {[h for h, d in dupes.items() if d]}"))

    n = meta.get("n_particles")
    if n:
        wrong = [h for h, s in by_step.items() if len(s["ids"]) != n]
        r.check(g, not wrong, f"all {n} released particles accounted for at every step (any status)"
                + ("" if not wrong else f": not at {wrong}"))

    start = meta.get("start_time")
    if start:
        t0 = datetime.fromisoformat(start.replace("Z", "+00:00"))
        bad = [h for h, s in by_step.items()
               if s["timestamps"] and s["timestamps"] != {(t0 + timedelta(hours=h)).isoformat().replace("+00:00", "Z")}]
        r.check(g, not bad, f"timestamps equal start_time {start} + hours" + ("" if not bad else f": not at {bad}"))

    summary = {float(row["hours"]): row for row in meta.get("summary_by_hour", [])}
    off = [h for h in hours if h in summary and abs(by_step[h]["active_m3"] - summary[h]["oil_afloat_m3"]) > 0.05]
    if summary:
        r.check(g, not off, "oil afloat per step in drift.geojson equals meta.json summary_by_hour"
                + ("" if not off else f": differs at {off}"))

    afloat = [by_step[h]["active_m3"] for h in hours]
    rises = [hours[i] for i in range(1, len(hours)) if afloat[i] > afloat[i - 1] + VOLUME_TOL]
    r.check(g, not rises, f"oil afloat only goes down ({afloat[0]:.1f} -> {afloat[-1]:.1f} m3)"
            + ("" if not rises else f": rises at {rises}"))
    release = meta.get("release_volume_m3")
    if release:
        r.check(g, abs(afloat[0] - release) <= 0.5, f"oil afloat at 0 h ({afloat[0]:.1f}) equals release_volume_m3 ({release:g})")

    return {"meta": meta, "afloat_by_hour": dict(zip(hours, afloat)),
            "water_fraction_by_hour": {h: row.get("mean_water_fraction") for h, row in summary.items()}}


# --- B. targets -----------------------------------------------------------------------------


def _patch_spread_km(forecast, track_particle_ids: set[str], hours: float) -> float:
    """Radius (km) around the oil-weighted centre that holds 90 % of a patch's oil."""
    ps = [p for p in forecast.steps.get(hours, ()) if p.particle_id in track_particle_ids]
    vol = sum(p.volume_m3 for p in ps)
    if not ps or vol <= 0:
        return 0.0
    centre = GeoCoordinate(latitude=sum(p.location.latitude * p.volume_m3 for p in ps) / vol,
                           longitude=sum(p.location.longitude * p.volume_m3 for p in ps) / vol)
    dists = sorted((_km(p.location, centre), p.volume_m3) for p in ps)
    acc = 0.0
    for d, v in dists:
        acc += v
        if acc >= 0.9 * vol:
            return d
    return dists[-1][0]


def check_targets(drift_dir: Path, routing_dir: Path, vessels, comparison: dict, drift_info: dict, r: Report) -> dict:
    g = "B targets"
    emulsion = drift_info["tank_basis"] == "emulsion"
    r.ok(g, f"tank basis of the plan: {drift_info['tank_basis']}"
         + ("" if (comparison.get("drift") or {}).get("tank_basis")
            else " (comparison.json has no tank_basis: made before emulsion counting)"))
    forecast = load_drift(drift_dir, replace(DEFAULT_DRIFT_CONFIG, count_emulsion=emulsion))
    dispatch = float((comparison.get("drift") or {}).get("dispatch_hours", DEFAULT_DRIFT_CONFIG.dispatch_hours))
    if not comparison:
        r.warn(g, f"no comparison.json, so the dispatch hour is taken as the default {dispatch:g} h")
    max_tank = max(v.capacity_m3 for v in vessels)
    patches = build_tracks(forecast, dispatch, max_target_m3=max_tank)
    r.check(g, patches.follow == "particle_id", f"patches follow the oil by particle id (follow = {patches.follow})",
            level_if_not="WARN")

    # Every particle afloat at dispatch lands in exactly one cell, so targeted + untargeted = afloat.
    targeted = sum(t.volumes[0] for t in patches.tracks)
    total = targeted + patches.untargeted_m3
    r.check(g, abs(total - patches.oil_afloat_m3) <= VOLUME_TOL,
            f"at dispatch ({dispatch:g} h): targeted {targeted:.2f} + untargeted {patches.untargeted_m3:.2f} "
            f"= afloat {patches.oil_afloat_m3:.2f} m3 (each particle in one patch only)")
    share = targeted / patches.oil_afloat_m3 if patches.oil_afloat_m3 else 0
    r.check(g, share >= 0.95, f"{share:.1%} of the oil afloat at dispatch is in a target", level_if_not="WARN")

    # Split parts: same track, equal shares, sum = parent.
    parents: dict[str, list] = {}
    for t in patches.tracks:
        parents.setdefault(t.target_id.split("-")[0], []).append(t)
    for name, parts in parents.items():
        if len(parts) > 1:
            same = all(p.positions == parts[0].positions for p in parts)
            r.check(g, same, f"{name} is split into {len(parts)} parts (it would fill more than the largest "
                    f"tank, {max_tank:g} m3, {'as emulsion ' if emulsion else ''}at some step) that move together, "
                    f"{parts[0].volumes[0]:.1f} m3 oil each at dispatch")

    # Particles of each patch (rebuilt the same way drift_targets does it).
    cell = DEFAULT_DRIFT_CONFIG.cell_deg
    at_dispatch = forecast.steps[dispatch]
    cells: dict[tuple, set[str]] = {}
    for p in at_dispatch:
        cells.setdefault((int(p.location.latitude // cell), int(p.location.longitude // cell)), set()).add(p.particle_id)
    ranked = sorted(cells, key=lambda k: (-sum(q.volume_m3 for q in at_dispatch if q.particle_id in cells[k]), str(k)))
    ids_by_name = {f"T{rank:02d}": cells[k] for rank, k in enumerate(ranked[: DEFAULT_DRIFT_CONFIG.max_targets], 1)}

    # targets.geojson vs the rebuilt tracks.
    tfile = _read(routing_dir / "targets.geojson")["features"]
    file_ids = {f["properties"]["target_id"] for f in tfile}
    track_by_id = {t.target_id: t for t in patches.tracks}
    r.check(g, file_ids == set(track_by_id), f"targets.geojson has the same {len(file_ids)} target ids as the "
            "patches rebuilt from drift.geojson" + ("" if file_ids == set(track_by_id) else
            f": file only {sorted(file_ids - set(track_by_id))}, rebuilt only {sorted(set(track_by_id) - file_ids)}"))

    rows = []
    for f in tfile:
        p = f["properties"]
        tid = p["target_id"]
        track = track_by_id.get(tid)
        if track is None:
            continue
        when = p.get("position_hours", dispatch)
        place, vol = track.at(when)
        loc = _point(f["geometry"]["coordinates"])
        pos_err = _km(loc, place)
        vol_err = abs(p["oil_volume_m3"] - vol)
        r.check(g, pos_err < 0.05 and vol_err < VOLUME_TOL,
                f"{tid}: {p['oil_volume_m3']:.2f} m3 at {when:g} h, {loc.latitude:.4f} N {loc.longitude:.4f} E "
                f"matches the drift (off by {pos_err * 1000:.0f} m, {vol_err:.3f} m3); served by {p.get('served_by')}")
        pids = ids_by_name.get(tid.split("-")[0], set())
        spread = _patch_spread_km(forecast, pids, min(forecast.steps, key=lambda h: abs(h - when)))
        rows.append({"target_id": tid, "oil_m3": p["oil_volume_m3"], "dispatch_m3": track.volumes[0],
                     "position_hours": when, "meet_hours": p.get("meet_hours"), "served_by": p.get("served_by"),
                     "drifted_km": p.get("drifted_km"), "particles": len(pids), "spread90_km": round(spread, 2),
                     "lat": loc.latitude, "lon": loc.longitude})

    wide = [row["target_id"] for row in rows if row["spread90_km"] > SPREAD_WARN_KM]
    spreads = [row["spread90_km"] for row in rows]
    r.check(g, not wide, f"patch size where it is met: 90 % of a patch's oil lies within {min(spreads):.1f} to "
            f"{max(spreads):.1f} km of the point the vessel aims at" + ("" if not wide else
            f"; {len(wide)} patch(es) wider than {SPREAD_WARN_KM:g} km, so 'one skimming position' is an assumption"),
            level_if_not="WARN")

    # At any time the targets together cannot hold more than the oil afloat.
    for step in sorted({min(forecast.steps, key=lambda s: abs(s - row["position_hours"])) for row in rows}):
        held = sum(t.at(step)[1] for t in patches.tracks)
        afloat = sum(p.volume_m3 for p in forecast.steps[step])
        r.check(g, held <= afloat + VOLUME_TOL, f"at {step:g} h all targets hold {held:.1f} m3 <= {afloat:.1f} m3 afloat")
    return {"dispatch_hours": dispatch, "follow": patches.follow, "oil_afloat_at_dispatch_m3": patches.oil_afloat_m3,
            "targeted_m3": targeted, "untargeted_m3": patches.untargeted_m3, "targets": rows}


# --- C. fleet -------------------------------------------------------------------------------


def check_fleet(vessels, release: GeoCoordinate | None, plan_message: str, r: Report) -> list[dict]:
    g = "C fleet"
    # The router moves a port that its 2.2 km land grid counts as land, and says so in the plan's message.
    snapped = {part.split(" (")[0]: part for part in plan_message.split("; ") if "was on land and moved" in part}
    rows = []
    for v in vessels:
        depot, dist = min(((name, _km(v.location, c)) for name, c in GULF_DEPOTS.items()), key=lambda x: x[1])
        # Not a broken rule: a fleet file made before GULF_DEPOTS last changed is still a valid plan input.
        r.check(g, dist < 0.1, f"{v.vessel_id} is based at {depot} ({dist * 1000:.0f} m from its point in GULF_DEPOTS"
                + (")" if dist < 0.1 else "; the fleet file is older than GULF_DEPOTS, re-run scenario.py)"),
                level_if_not="WARN")
        r.check(g, v.vessel_id not in snapped, f"{v.vessel_id}: the router used its port as given (not moved off land)"
                if v.vessel_id not in snapped else f"{v.vessel_id}: port is land in the routing grid: "
                f"{snapped[v.vessel_id].split(') ', 1)[-1]}, so sailing from it is approximate",
                level_if_not="WARN")
        knots = v.speed_m_per_s * KNOTS_PER_M_PER_S
        r.check(g, knots <= 25, f"{v.vessel_id}: {knots:.1f} kn transit, {v.capacity_m3:g} m3 tank, "
                f"{v.available_hours:g} h shift", level_if_not="WARN")
        out_km = _km(v.location, release) if release else None
        rows.append({"vessel_id": v.vessel_id, "depot": depot, "knots": round(knots, 1), "capacity_m3": v.capacity_m3,
                     "available_hours": v.available_hours,
                     "straight_km_to_release": None if out_km is None else round(out_km, 1)})
    depots = {row["depot"] for row in rows}
    r.check(g, {"port_saqr_rak", "hamriyah_sharjah"} <= depots, "fleet includes Port Saqr and Hamriyah vessels")
    return rows


# --- D. routes ------------------------------------------------------------------------------


def check_routes(routing_dir: Path, vessels, drift_info: dict, r: Report, label: str = "optimized") -> dict:
    g = f"D routes ({label})"
    rate = DEFAULT_CONFIG.recovery_rate_m3_per_hour
    by_id = {v.vessel_id: v for v in vessels}
    targets = {f["properties"]["target_id"]: f["properties"] for f in _read(routing_dir / "targets.geojson")["features"]}
    summary = _read(routing_dir / "summary.json")
    routes_path = routing_dir / "routes.geojson"
    routes = _read(routes_path)["features"] if routes_path.exists() else []
    wf = {h: w for h, w in drift_info["water_fraction_by_hour"].items() if w is not None}
    basis = drift_info["tank_basis"]

    def emulsion_of(t: str) -> float | None:
        meet = targets[t].get("meet_hours")
        w = _water_at(wf, meet) if meet is not None else None
        return None if w is None else targets[t]["oil_volume_m3"] / (1 - w)

    seen: dict[str, str] = {}
    out = []
    for f in routes:
        p = f["properties"]
        vid, coords = p["vessel_id"], f["geometry"]["coordinates"]
        v = by_id[vid]
        assigned = p["assigned_target_ids"]
        port = [v.location.longitude, v.location.latitude]
        r.check(g, coords[0] == port and coords[-1] == port and len(coords) == len(assigned) + 2,
                f"{vid}: starts and ends at its home port, {len(assigned)} stop(s) {assigned}")
        for tid in assigned:
            if tid in seen:
                r.fail(g, f"{tid} is served by both {seen[tid]} and {vid}")
            seen[tid] = vid
            if targets.get(tid, {}).get("served_by") != vid:
                r.fail(g, f"{tid}: targets.geojson says served_by {targets.get(tid, {}).get('served_by')}, routes say {vid}")
        oil = sum(targets[t]["oil_volume_m3"] for t in assigned)
        r.check(g, abs(oil - p["oil_collected_m3"]) < VOLUME_TOL,
                f"{vid}: recovers {oil:.1f} m3 pure oil (oil_collected_m3 {p['oil_collected_m3']:.1f})")
        # Emulsion: the oil takes up water (meta.json, at the meeting time), so the tank takes more.
        each = [emulsion_of(t) for t in assigned]
        emulsion = sum(e for e in each if e is not None) if all(e is not None for e in each) else 0.0
        if basis == "emulsion":
            for t, e in zip(assigned, each):
                if e is not None and "emulsion_m3" in targets[t]:
                    r.check(g, abs(e - targets[t]["emulsion_m3"]) <= max(VOLUME_TOL, EMULSION_TOL * e),
                            f"{t}: emulsion {targets[t]['emulsion_m3']:.2f} m3 = {targets[t]['oil_volume_m3']:.2f} m3 "
                            f"oil / (1 - {targets[t].get('water_fraction', 0):.3f} water) at {targets[t]['meet_hours']:g} h"
                            f" (rechecked {e:.2f} m3)")
            if "emulsion_collected_m3" in p:
                r.check(g, abs(emulsion - p["emulsion_collected_m3"]) <= max(VOLUME_TOL, EMULSION_TOL * emulsion),
                        f"{vid}: emulsion_collected_m3 {p['emulsion_collected_m3']:.1f} equals its targets' emulsion "
                        f"(rechecked {emulsion:.1f} m3)")
            load = emulsion
        else:
            load = oil
            if emulsion:
                r.check(g, emulsion <= v.capacity_m3, f"{vid}: planned as pure oil; as emulsion (water uptake "
                        f"from meta.json) about {emulsion:.0f} m3, {emulsion / v.capacity_m3:.0%} of the tank",
                        level_if_not="WARN")
        r.check(g, load <= v.capacity_m3 + 1e-9,
                f"{vid}: tank {load:.1f} m3 {basis} of {v.capacity_m3:g} m3 ({load / v.capacity_m3:.0%})")
        cleanup = load / rate
        r.check(g, abs(cleanup - p["cleanup_hours"]) <= max(0.01, EMULSION_TOL * cleanup),
                f"{vid}: cleanup {p['cleanup_hours']:.2f} h = {load:.1f} m3 {basis} / {rate:g} m3/h")
        # Sailing: the route's distance at the vessel's speed (out, between stops and back to port).
        km = p["estimated_distance_km"]
        sailing = km * 1000 / v.speed_m_per_s / 3600
        r.check(g, abs(sailing - p["estimated_travel_hours"]) < 0.01,
                f"{vid}: sailing {p['estimated_travel_hours']:.2f} h = {km:.1f} km / "
                f"{v.speed_m_per_s * KNOTS_PER_M_PER_S:.1f} kn (rechecked {sailing:.2f} h)")
        # The distance cannot be shorter than straight lines through the stops; the drawn sea path
        # (grid cell centres) is a little longer than the routed distance, so it is an upper bound.
        straight = _line_km(f["geometry"]["coordinates"])
        drawn = _line_km(p["sea_path"]) if p.get("sea_path") else None
        r.check(g, km >= 0.99 * straight and (drawn is None or km <= drawn * 1.01),
                f"{vid}: {km:.1f} km is between the straight line through its stops ({straight:.1f} km)"
                + ("" if drawn is None else f" and its drawn sea path ({drawn:.1f} km)"), level_if_not="WARN")
        # finish_hours must be sailing + cleanup, both as rechecked above.
        finish = p["estimated_travel_hours"] + cleanup
        r.check(g, abs(finish - p["finish_hours"]) <= max(0.01, EMULSION_TOL * finish),
                f"{vid}: finish_hours {p['finish_hours']:.2f} h = sailing {p['estimated_travel_hours']:.2f} h + "
                f"cleanup {cleanup:.2f} h (rechecked {finish:.2f} h)")
        r.check(g, finish <= v.available_hours + 1e-6,
                f"{vid}: finishes in {finish:.2f} h of a {v.available_hours:g} h shift ({km:.1f} km, "
                "trip back to port included)")
        out.append({"vessel_id": vid, "targets": assigned, "oil_m3": round(oil, 2), "emulsion_m3": round(emulsion, 1),
                    "capacity_m3": v.capacity_m3, "distance_km": round(km, 1),
                    "travel_hours": round(p["estimated_travel_hours"], 2), "cleanup_hours": round(cleanup, 2),
                    "finish_hours": round(finish, 2), "available_hours": v.available_hours,
                    "_exact": {"oil": oil, "km": km, "sailing": p["estimated_travel_hours"], "finish": finish}})

    unserved = summary.get("unserved_target_ids", [])
    unserved_m3 = sum(targets[t]["oil_volume_m3"] for t in unserved if t in targets)
    reasons = next((part for part in summary.get("message", "").split("; ") if part.startswith("unserved:")), "")
    r.check(g, not unserved, f"unserved targets: {unserved or 'none'} ({unserved_m3:.1f} m3). {reasons}",
            level_if_not="WARN")
    r.check(g, set(summary.get("idle_vessel_ids", [])) | {row["vessel_id"] for row in out} == set(by_id),
            f"every vessel either has a route or is listed idle (idle: {summary.get('idle_vessel_ids') or 'none'})")
    late = [t for t, p in targets.items() if (p.get("meet_hours") or 0) > max(drift_info["afloat_by_hour"])]
    r.check(g, not late, "every meeting is inside the forecast window" + ("" if not late else f": not {late}"), "WARN")
    return {"routes": out, "unserved": unserved, "unserved_m3": unserved_m3, "idle": summary.get("idle_vessel_ids", []),
            "status": summary.get("status"), "message": summary.get("message"),
            "total_oil_m3": sum(t["oil_volume_m3"] for t in targets.values())}


# --- E. comparison --------------------------------------------------------------------------


def _recalculated(plan: dict) -> dict:
    """The comparison metrics of one plan, from its own route and target files (evaluate_routes' definitions)."""
    rows = [row["_exact"] for row in plan["routes"]]
    covered = {t for row in plan["routes"] for t in row["targets"]}
    km = sum(x["km"] for x in rows)
    return {"oil_recovered_m3": sum(x["oil"] for x in rows), "response_hours": max((x["finish"] for x in rows), default=0.0),
            "distance_km": km, "travel_hours": sum(x["sailing"] for x in rows),
            "longest_route_hours": max((x["sailing"] for x in rows), default=0.0), "targets_covered": len(covered),
            "distance_km_per_target": km / len(covered) if covered else float("nan"), "_covered": covered}


def _not_applicable(x) -> bool:
    """A metric with no value: null in the file, or NaN (distance per target of a plan that serves nothing)."""
    return x is None or (isinstance(x, float) and isnan(x))


def check_comparison(comparison: dict, optimized: dict, baseline: dict | None, r: Report) -> dict:
    """Recalculate every metric in comparison.json from the plan files; none is taken on trust."""
    g = "E comparison"
    for side in ("optimized", "baseline"):
        v = (comparison.get(side) or {}).get("rule_violations", [])
        r.check(g, not v, f"{side}: comparison.json lists no rule violations" + ("" if not v else f": {v}"))
    m = comparison.get("metrics") or {}
    if not m:
        r.warn(g, f"no metrics: {comparison.get('metrics_error')}")
        return {}
    if baseline is None:
        r.warn(g, "no baseline plan files, so the comparison metrics are only reported, not recalculated")
        return {"reported": m}

    opt, base = _recalculated(optimized), _recalculated(baseline)
    mine = {f"{side}_{k}": v for side, plan in (("optimized", opt), ("baseline", base))
            for k, v in plan.items() if not k.startswith("_")}

    def change(a, b):
        return 0.0 if b == 0 else (a - b) / b * 100.0

    for k in ("oil_recovered", "response_hours", "distance", "travel_hours"):
        key = {"oil_recovered": "oil_recovered_m3", "distance": "distance_km"}.get(k, k)
        mine[f"{k}_change_percent"] = change(mine[f"optimized_{key}"], mine[f"baseline_{key}"])
    mine["targets_covered_difference"] = opt["targets_covered"] - base["targets_covered"]
    mine["same_targets_covered"] = 1.0 if opt["_covered"] == base["_covered"] else 0.0
    mine["total_oil_m3"] = optimized["total_oil_m3"]  # all targets in the optimized plan's targets.geojson

    labels = {
        "total_oil_m3": ("oil in all targets", "m3"), "oil_recovered_m3": ("oil recovered", "m3"),
        "response_hours": ("response time, last vessel back in port", "h"), "distance_km": ("distance", "km"),
        "travel_hours": ("sailing time, all vessels", "h"), "longest_route_hours": ("longest single route", "h"),
        "targets_covered": ("targets covered", ""), "distance_km_per_target": ("distance per target", "km"),
    }
    mismatched, not_applicable = [], []
    for key in m:
        if key not in mine:
            mismatched.append(f"{key} (not recalculated)")
            continue
        a, b = m[key], mine[key]
        if _not_applicable(a) or _not_applicable(b):
            if _not_applicable(a) and _not_applicable(b):
                not_applicable.append(key)  # both say there is no value: they agree
            else:
                mismatched.append(f"{key}: file {'n/a' if _not_applicable(a) else f'{a:.3f}'}, recalculated "
                                  f"{'n/a' if _not_applicable(b) else f'{b:.3f}'}")
            continue
        tol = 0.05 if key.endswith("_percent") else max(0.01, 0.001 * abs(b))
        if not (a == b or abs(a - b) <= tol):
            mismatched.append(f"{key}: file {a:.3f}, recalculated {b:.3f}")
    r.check(g, not mismatched, f"all {len(m)} metrics in comparison.json recalculated from the route and target "
            "files and equal" + ("" if not mismatched else f": {'; '.join(mismatched)}")
            + ("" if not not_applicable else f" ({', '.join(not_applicable)} not applicable in both)"))
    for key, (label, unit) in labels.items():
        if key == "total_oil_m3":
            r.ok(g, f"{label}: {mine[key]:.1f} {unit} (recalculated)")
            continue
        o, b = mine[f"optimized_{key}"], mine[f"baseline_{key}"]
        extra = f", {change(o, b):+.1f} %" if key in ("oil_recovered_m3", "response_hours", "distance_km", "travel_hours") else ""
        def shown(x):
            if _not_applicable(x):
                return "n/a (no targets covered)"
            return ("{:g}" if key == "targets_covered" else "{:.2f}").format(x) + (f" {unit}" if unit else "")
        r.ok(g, f"{label}: optimized {shown(o)} vs baseline {shown(b)}{extra} (recalculated)")
    r.ok(g, "same targets covered by both plans" if mine["same_targets_covered"] else
         "the plans cover different targets, so read coverage before distance and time")
    return {"reported": m, "recalculated": mine}


# --- synthetic fixture vs real --------------------------------------------------------------


def describe_fixture(path: Path) -> dict:
    _, _, targets = load_scenario(path)
    vols = [t.oil_volume_m3 for t in targets]
    pts = [t.location for t in targets]
    far = max((_km(a, b) for a in pts for b in pts), default=0.0)
    return {"targets": len(targets), "total_m3": round(sum(vols), 2), "min_m3": min(vols), "max_m3": max(vols),
            "max_km_between_targets": round(far, 2)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--drift-dir", default=str(REPO_ROOT / "outputs" / "drift"))
    ap.add_argument("--routing-dir", default=str(REPO_ROOT / "outputs" / "routing"))
    ap.add_argument("--fleet", default=str(REPO_ROOT / "optimization" / "fixtures" / "gulf_standard.json"))
    ap.add_argument("--synthetic-fixture", default=str(REPO_ROOT / "optimization" / "fixtures" / "gulf_drift_t12.json"))
    ap.add_argument("--json", help="also write every check and number to this file")
    args = ap.parse_args()
    drift_dir, routing_dir = Path(args.drift_dir), Path(args.routing_dir)
    # run_drift_plan writes the plan into routing_dir and the baseline into baseline/; a copy
    # shared by hand may hold them as Optimized/ and Baseline/ instead
    plan_dir = next((d for d in (routing_dir / "Optimized", routing_dir / "optimized") if d.is_dir()), routing_dir)
    baseline_dir = next((d for d in (routing_dir / "baseline", routing_dir / "Baseline") if d.is_dir()), None)

    r = Report()
    _, vessels, _ = load_scenario(args.fleet)
    # comparison.json (dispatch hour, baseline) is optional: the dashboard needs only the three files
    comparison = _read(routing_dir / "comparison.json") if (routing_dir / "comparison.json").exists() else {}
    drift = check_drift(drift_dir, r)
    # what the plan put in the tanks; plans made before emulsion counting have no tank_basis
    drift["tank_basis"] = (comparison.get("drift") or {}).get("tank_basis") or "pure oil"
    init = drift["meta"].get("initial_location")
    release = GeoCoordinate(**init) if init else None
    result = {
        "drift_dir": str(drift_dir), "routing_dir": str(routing_dir), "fleet": args.fleet,
        "simulation_id": drift["meta"].get("simulation_id"),
        "targets": check_targets(drift_dir, plan_dir, vessels, comparison, drift, r),
        "fleet_rows": check_fleet(vessels, release, _read(plan_dir / "summary.json").get("message", ""), r),
        "optimized": check_routes(plan_dir, vessels, drift, r),
    }
    if baseline_dir is not None and (baseline_dir / "summary.json").exists():
        result["baseline"] = check_routes(baseline_dir, vessels, drift, r, label="baseline")
    if comparison:
        result["metrics"] = check_comparison(comparison, result["optimized"], result.get("baseline"), r)
    else:
        r.warn("E comparison", f"no comparison.json in {routing_dir}: baseline not checked")
    if args.synthetic_fixture and Path(args.synthetic_fixture).exists():
        result["synthetic_fixture"] = describe_fixture(Path(args.synthetic_fixture))
    result["afloat_by_hour"] = drift["afloat_by_hour"]
    result["water_fraction_by_hour"] = drift["water_fraction_by_hour"]
    result["tank_basis"] = drift["tank_basis"]

    group = None
    for row in r.rows:
        if row["group"] != group:
            group = row["group"]
            print(f"\n{group.upper()}")
        print(f"  [{row['level']:4}] {row['text']}")
    c = r.counts()
    print(f"\n{c['OK']} OK, {c['WARN']} WARN, {c['FAIL']} FAIL")
    if args.json:
        Path(args.json).write_text(json.dumps({"checks": r.rows, "counts": c, **result}, indent=2, default=str),
                                   encoding="utf-8")
        print(f"wrote {args.json}")
    raise SystemExit(1 if c["FAIL"] else 0)


if __name__ == "__main__":
    main()
