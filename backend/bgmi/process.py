"""Pass 2: analyse one match (keyframes between t_start and t_end) and store results."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np

from . import db, profile, scene, source
from .maps.registry import ALL_TOWNS, MAPS, identify
from .markers import detect_tags
from .register import Registrar
from .roster import Book, read_roster
from .zone import blue_edge, white_ring

ROSTER_EVERY = 2  # frames
ZONE_EVERY = 3
MIN_REG_CONF = 0.3


@dataclass
class _Pending:
    t: float
    name: str
    color: tuple[float, float, float]
    x: float
    y: float
    conf: float


def lab_to_hex(lab) -> str:
    px = np.uint8([[list(np.clip(lab, 0, 255))]])
    b, g, r = cv2.cvtColor(px, cv2.COLOR_LAB2BGR)[0, 0]
    return f"#{r:02x}{g:02x}{b:02x}"


def process_match(
    match_id: int,
    url: str,
    profile_name: str,
    t0: float,
    t1: float,
    on_progress: Callable[[float], None] | None = None,
    book: Book | None = None,
    frames=None,
) -> dict:
    """`frames`: optional iterable of source.Frame (tests / cached frames) instead of the URL."""
    P = profile.load(profile_name)
    reg = Registrar()
    book = book or Book()
    map_name: str | None = None
    words: list[str] = []
    obs: list[db.Observation] = []
    zones: list[db.ZoneObs] = []
    status: list[db.TeamStatus] = []
    pending: list[_Pending] = []
    alive_hist: dict[str, list[tuple[float, int]]] = {}
    kills_last: dict[str, int] = {}
    stats = {"frames": 0, "map_frames": 0, "tags": 0, "assigned": 0}
    started = time.time()

    def flush() -> None:
        with db.session() as s:
            s.add_all(obs + zones + status)
            s.commit()
        obs.clear()
        zones.clear()
        status.clear()

    i = 0
    if frames is None:
        info = source.resolve(url)
        frames = source.iter_frames(info.video_url, start=t0, end=t1)
    for fr in frames:
        stats["frames"] += 1
        img = fr.image
        sc = scene.classify(img, P)
        if sc.layout is None:
            continue
        L = sc.layout
        stats["map_frames"] += 1
        i += 1

        # teams + alive bars
        if i % ROSTER_EVERY == 1 or not book.teams:
            rows = read_roster(img, L)
            if len(rows) >= 8:
                canon = book.set_teams([r.tag for r in rows])
                for r, tag in zip(rows, canon):
                    if tag is None:
                        continue
                    status.append(db.TeamStatus(match_id=match_id, t=fr.t, team=tag, alive=r.alive, kills=r.kills))
                    if r.kills is not None:
                        kills_last[tag] = max(r.kills, kills_last.get(tag, 0))
                    if r.alive is not None:
                        alive_hist.setdefault(tag, []).append((fr.t, r.alive))

        res = reg.update(img, L)
        T = res.transform
        towns = set(MAPS[map_name].towns) if map_name else set(ALL_TOWNS)
        w: list[str] = []
        tags = detect_tags(img, L.map_region, T, town_names=towns, words_out=w if map_name is None else None)
        if map_name is None:
            words.extend(w)
            if stats["map_frames"] >= 2:
                map_name = identify(words)
        stats["tags"] += len(tags)
        usable = T is not None and res.confidence >= MIN_REG_CONF
        for tg in tags:
            team, pl = book.assign(tg.text, tg.color)
            if not usable or tg.km is None:
                continue
            x, y = tg.km
            conf = round(float(res.confidence * tg.conf), 3)
            if team is None:
                pending.append(_Pending(fr.t, tg.text, tg.color, x, y, conf))
                continue
            stats["assigned"] += 1
            obs.append(db.Observation(match_id=match_id, t=fr.t, team=team, player=pl.name if pl else "", x=x, y=y, conf=conf))

        if usable and i % ZONE_EVERY == 1:
            boxes = [tg.box for tg in tags]
            wr = white_ring(img, L.map_region, ignore=boxes)
            if wr is not None:
                cx, cy, r = wr.to_km(T)
                zones.append(db.ZoneObs(match_id=match_id, t=fr.t, kind="white", cx=cx, cy=cy, r=r, support=wr.support))
            be = blue_edge(img, L.map_region, ignore=boxes, contains=wr)
            if be is not None:
                cx, cy, r = be.to_km(T)
                zones.append(db.ZoneObs(match_id=match_id, t=fr.t, kind="blue", cx=cx, cy=cy, r=r, support=be.support))

        if len(obs) > 400:
            flush()
        if on_progress and t1 > t0:
            on_progress(min(1.0, (fr.t - t0) / (t1 - t0)))

    # names that only became attributable later (e.g. resolved by elimination)
    for p in pending:
        team, pl = book.assign(p.name, p.color)
        if team is not None:
            stats["assigned"] += 1
            obs.append(db.Observation(match_id=match_id, t=p.t, team=team, player=pl.name if pl else "", x=p.x, y=p.y, conf=p.conf))
    flush()

    # elimination = first time alive bars read 0 and stayed 0 for the next two reads
    eliminated_at: dict[str, float] = {}
    for tag, hist in alive_hist.items():
        for k in range(len(hist) - 2):
            if hist[k][1] == 0 and hist[k + 1][1] == 0 and hist[k + 2][1] == 0:
                eliminated_at[tag] = hist[k][0]
                break

    # placements: survivors first, then reverse elimination order
    order = sorted(book.teams, key=lambda t: -(eliminated_at.get(t, 1e12)))
    with db.session() as s:
        for rank, tag in enumerate(order, start=1):
            players = sorted({p.name for p in book.players if p.team == tag})
            col = book.team_color(tag)
            s.add(
                db.TeamInMatch(
                    match_id=match_id,
                    tag=tag,
                    color=lab_to_hex(col) if col is not None else "",
                    players=",".join(players),
                    placement=rank if eliminated_at else None,
                    kills=kills_last.get(tag),
                    eliminated_at=eliminated_at.get(tag),
                )
            )
        s.commit()
    stats["map"] = map_name
    stats["seconds"] = round(time.time() - started, 1)
    return stats
