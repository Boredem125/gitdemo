"""SQLite storage (SQLModel). Only derived data is stored - never video."""

from __future__ import annotations

import os
import time
from pathlib import Path

from sqlmodel import Field, Session, SQLModel, create_engine, select

DATA_DIR = Path(os.environ.get("BGMI_DATA", Path(__file__).resolve().parents[2] / "data"))
DB_PATH = DATA_DIR / "bgmi.db"


class Stream(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    url: str
    title: str = ""
    duration: float = 0.0
    profile: str = "bmsd2026"
    status: str = "queued"  # queued | scanning | processing | done | failed
    stage: str = ""
    progress: float = 0.0  # 0..1
    error: str = ""
    created_at: float = Field(default_factory=time.time)


class Match(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    stream_id: int = Field(index=True)
    idx: int  # order within the stream
    day: int | None = None
    match_no: int | None = None
    map: str | None = None
    t_start: float = 0.0
    t_end: float = 0.0
    status: str = "pending"  # pending | processing | done | failed
    progress: float = 0.0
    confidence: float = 1.0
    note: str = ""


class TeamInMatch(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    match_id: int = Field(index=True)
    tag: str
    color: str = ""  # hex of tag colour
    players: str = ""  # comma separated canonical names
    placement: int | None = None  # 1 = winner
    kills: int | None = None
    eliminated_at: float | None = None


class Observation(SQLModel, table=True):
    """One player name tag seen on the map."""

    id: int | None = Field(default=None, primary_key=True)
    match_id: int = Field(index=True)
    t: float
    team: str = Field(index=True)
    player: str = ""
    x: float  # km
    y: float
    conf: float = 1.0


class ZoneObs(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    match_id: int = Field(index=True)
    t: float
    kind: str  # white (next zone) | blue (current zone edge)
    cx: float  # km
    cy: float
    r: float
    support: float = 1.0


class TeamStatus(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    match_id: int = Field(index=True)
    t: float
    team: str
    alive: int | None = None
    kills: int | None = None


_engine = None


def engine():
    global _engine
    if _engine is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False, "timeout": 30})
        with _engine.connect() as c:
            c.exec_driver_sql("PRAGMA journal_mode=WAL")
        SQLModel.metadata.create_all(_engine)
    return _engine


def session() -> Session:
    return Session(engine())


def update(model, id_: int, **fields) -> None:
    with session() as s:
        obj = s.get(model, id_)
        if obj is None:
            return
        for k, v in fields.items():
            setattr(obj, k, v)
        s.add(obj)
        s.commit()


__all__ = [
    "Stream",
    "Match",
    "TeamInMatch",
    "Observation",
    "ZoneObs",
    "TeamStatus",
    "engine",
    "session",
    "update",
    "select",
]
