"""Turn raw observations into per-team match facts and cross-match reports.

Everything here is computed from the database, so thresholds can be tuned without
re-processing video.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field

import numpy as np

from . import db
from .db import select

TRACK_BIN = 10.0  # s: team positions are binned to this resolution
DROP_WINDOW = 90.0  # s after a team first appears
EDGE_BAND = 0.10  # within +-10% of radius = "edge"


# ---------------------------------------------------------------------------
# match level
# ---------------------------------------------------------------------------


@dataclass
class TrackPoint:
    t: float
    x: float
    y: float
    n: int  # observations behind this point


@dataclass
class Phase:
    idx: int
    t_start: float  # when this next-zone circle first appeared
    t_end: float  # when the following circle appeared (or last seen)
    cx: float
    cy: float
    r: float


@dataclass
class TeamPhase:
    phase: int
    status_at_reveal: str  # inside | edge | outside | unknown
    status_at_close: str
    dist_at_reveal: float | None  # km from zone centre, in radii
    entered_after: float | None  # seconds after reveal the team was first inside


@dataclass
class TeamMatchFacts:
    team: str
    color: str
    players: list[str]
    placement: int | None
    kills: int | None
    eliminated_at: float | None
    drop: tuple[float, float] | None
    drop_contested: bool
    track: list[TrackPoint] = field(default_factory=list)
    phases: list[TeamPhase] = field(default_factory=list)
    player_drops: dict[str, tuple[float, float]] = field(default_factory=dict)


def team_tracks(observations: list[db.Observation]) -> dict[str, list[TrackPoint]]:
    """Team centroid per time bin (median of its player tags, weighted by confidence)."""
    by: dict[str, dict[int, list[tuple[float, float, float]]]] = defaultdict(lambda: defaultdict(list))
    for o in observations:
        by[o.team][int(o.t // TRACK_BIN)].append((o.x, o.y, o.conf))
    out = {}
    for team, bins in by.items():
        pts = []
        for b in sorted(bins):
            arr = np.array(bins[b])
            pts.append(TrackPoint(t=b * TRACK_BIN, x=float(np.median(arr[:, 0])), y=float(np.median(arr[:, 1])), n=len(arr)))
        out[team] = _despike(pts)
    return out


def _despike(pts: list[TrackPoint], max_speed_kmps: float = 0.06) -> list[TrackPoint]:
    """Drop points implying impossible speed (> ~215 km/h) vs both neighbours: OCR/assignment errors."""
    if len(pts) < 3:
        return pts
    keep = [pts[0]]
    for i in range(1, len(pts) - 1):
        a, b, c = keep[-1], pts[i], pts[i + 1]
        v1 = np.hypot(b.x - a.x, b.y - a.y) / max(b.t - a.t, 1)
        v2 = np.hypot(c.x - b.x, c.y - b.y) / max(c.t - b.t, 1)
        if v1 > max_speed_kmps and v2 > max_speed_kmps:
            continue
        keep.append(b)
    keep.append(pts[-1])
    return keep


def zone_phases(zones: list[db.ZoneObs]) -> list[Phase]:
    """Successive next-zone (white) circles. A new phase starts when the circle shrinks."""
    whites = sorted((z for z in zones if z.kind == "white" and z.support >= 0.45), key=lambda z: z.t)
    phases: list[Phase] = []
    group: list[db.ZoneObs] = []

    def close(g: list[db.ZoneObs]) -> None:
        if len(g) < 2:
            return
        arr = np.array([[z.cx, z.cy, z.r] for z in g])
        cx, cy, r = np.median(arr, axis=0)
        phases.append(Phase(len(phases) + 1, g[0].t, g[-1].t, float(cx), float(cy), float(r)))

    for z in whites:
        if group:
            ref = np.median(np.array([[g.cx, g.cy, g.r] for g in group]), axis=0)
            moved = np.hypot(z.cx - ref[0], z.cy - ref[1])
            if z.r < ref[2] * 0.85 and moved < ref[2]:
                close(group)
                group = []
            elif abs(z.r - ref[2]) > ref[2] * 0.15 or moved > ref[2] * 0.15:
                continue  # outlier detection
        group.append(z)
    close(group)
    for a, b in zip(phases, phases[1:]):
        a.t_end = b.t_start
    return phases


def _status(x: float, y: float, ph: Phase) -> tuple[str, float]:
    d = float(np.hypot(x - ph.cx, y - ph.cy)) / ph.r
    if d < 1 - EDGE_BAND:
        return "inside", d
    if d <= 1 + EDGE_BAND:
        return "edge", d
    return "outside", d


def _at(track: list[TrackPoint], t: float, tol: float = 45.0) -> TrackPoint | None:
    best = min(track, key=lambda p: abs(p.t - t), default=None)
    return best if best is not None and abs(best.t - t) <= tol else None


def match_facts(match_id: int) -> dict:
    with db.session() as s:
        m = s.get(db.Match, match_id)
        obs = s.exec(select(db.Observation).where(db.Observation.match_id == match_id)).all()
        zones = s.exec(select(db.ZoneObs).where(db.ZoneObs.match_id == match_id)).all()
        teams = s.exec(select(db.TeamInMatch).where(db.TeamInMatch.match_id == match_id)).all()
    tracks = team_tracks(obs)
    phases = zone_phases(zones)

    # drops: median position in the first DROP_WINDOW s after first sighting
    first_seen = {t: tr[0].t for t, tr in tracks.items() if tr}
    drops: dict[str, tuple[float, float]] = {}
    for team, tr in tracks.items():
        early = [p for p in tr if p.t <= first_seen[team] + DROP_WINDOW]
        if early:
            drops[team] = (float(np.median([p.x for p in early])), float(np.median([p.y for p in early])))
    player_drops: dict[str, dict[str, tuple[float, float]]] = defaultdict(dict)
    by_player: dict[tuple[str, str], list[db.Observation]] = defaultdict(list)
    for o in obs:
        if o.player:
            by_player[(o.team, o.player)].append(o)
    for (team, pl), lst in by_player.items():
        lst.sort(key=lambda o: o.t)
        early = [o for o in lst if o.t <= lst[0].t + DROP_WINDOW]
        player_drops[team][pl] = (float(np.median([o.x for o in early])), float(np.median([o.y for o in early])))

    facts = []
    meta = {t.tag: t for t in teams}
    for team in sorted(set(tracks) | set(meta)):
        tr = tracks.get(team, [])
        d = drops.get(team)
        contested = bool(d) and any(o != team and np.hypot(d[0] - p[0], d[1] - p[1]) < 0.35 for o, p in drops.items())
        tphases = []
        for ph in phases:
            a = _at(tr, ph.t_start)
            c = _at(tr, ph.t_end)
            sa, da = _status(a.x, a.y, ph) if a else ("unknown", None)
            sc_, _ = _status(c.x, c.y, ph) if c else ("unknown", None)
            entered = None
            for p in tr:
                if p.t >= ph.t_start and _status(p.x, p.y, ph)[0] == "inside":
                    entered = p.t - ph.t_start
                    break
            tphases.append(TeamPhase(ph.idx, sa, sc_, round(da, 2) if da is not None else None, entered))
        mt = meta.get(team)
        facts.append(
            TeamMatchFacts(
                team=team,
                color=mt.color if mt else "",
                players=[p for p in (mt.players.split(",") if mt and mt.players else [])],
                placement=mt.placement if mt else None,
                kills=mt.kills if mt else None,
                eliminated_at=mt.eliminated_at if mt else None,
                drop=d,
                drop_contested=contested,
                track=tr,
                phases=tphases,
                player_drops=player_drops.get(team, {}),
            )
        )
    facts.sort(key=lambda f: (f.placement is None, f.placement or 99, f.team))
    return {
        "match": m.model_dump() if m else None,
        "phases": [asdict(p) for p in phases],
        "zones": [{"t": z.t, "kind": z.kind, "cx": z.cx, "cy": z.cy, "r": z.r} for z in sorted(zones, key=lambda z: z.t)],
        "teams": [asdict(f) for f in facts],
    }


# ---------------------------------------------------------------------------
# team report across matches
# ---------------------------------------------------------------------------


def team_report(tag: str, stream_id: int | None = None) -> dict:
    with db.session() as s:
        q = select(db.Match).where(db.Match.status == "done")
        if stream_id is not None:
            q = q.where(db.Match.stream_id == stream_id)
        matches = s.exec(q).all()
    rows = []
    zone_counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    entered: dict[int, list[float]] = defaultdict(list)
    for m in sorted(matches, key=lambda m: (m.stream_id, m.idx)):
        f = match_facts(m.id)
        tf = next((t for t in f["teams"] if t["team"] == tag), None)
        if tf is None:
            continue
        for p in tf["phases"]:
            zone_counts[p["phase"]][p["status_at_reveal"]] += 1
            if p["entered_after"] is not None:
                entered[p["phase"]].append(p["entered_after"])
        rows.append(
            {
                "match_id": m.id,
                "stream_id": m.stream_id,
                "day": m.day,
                "match_no": m.match_no,
                "map": m.map,
                "placement": tf["placement"],
                "kills": tf["kills"],
                "drop": tf["drop"],
                "drop_contested": tf["drop_contested"],
                "track": tf["track"],
                "phases": tf["phases"],
                "color": tf["color"],
                "players": tf["players"],
            }
        )
    by_phase = []
    for ph in sorted(zone_counts):
        c = zone_counts[ph]
        n = sum(v for k, v in c.items() if k != "unknown")
        by_phase.append(
            {
                "phase": ph,
                "inside": c.get("inside", 0),
                "edge": c.get("edge", 0),
                "outside": c.get("outside", 0),
                "unknown": c.get("unknown", 0),
                "inside_pct": round(100 * c.get("inside", 0) / n) if n else None,
                "avg_entry_s": round(float(np.mean(entered[ph]))) if entered[ph] else None,
            }
        )
    placements = [r["placement"] for r in rows if r["placement"]]
    return {
        "team": tag,
        "matches": rows,
        "zone_by_phase": by_phase,
        "summary": {
            "matches": len(rows),
            "avg_placement": round(float(np.mean(placements)), 1) if placements else None,
            "contested_drop_pct": round(100 * sum(r["drop_contested"] for r in rows) / len(rows)) if rows else None,
        },
    }


def all_teams(stream_id: int | None = None) -> list[str]:
    with db.session() as s:
        q = select(db.TeamInMatch.tag).distinct()
        if stream_id is not None:
            ids = [m.id for m in s.exec(select(db.Match).where(db.Match.stream_id == stream_id)).all()]
            q = q.where(db.TeamInMatch.match_id.in_(ids))  # type: ignore[attr-defined]
        return sorted(set(s.exec(q).all()))
