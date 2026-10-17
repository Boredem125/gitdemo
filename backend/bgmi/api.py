"""HTTP API (FastAPI). Run: uvicorn bgmi.api:app --port 8000"""

from __future__ import annotations

import re
import threading
from pathlib import Path

import cv2
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import analytics, db
from .db import select
from .maps.registry import MAPS

app = FastAPI(title="BGMI Esports Analyzer")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])

YOUTUBE_RE = re.compile(r"^https?://(www\.|m\.)?(youtube\.com/(watch\?v=|live/)|youtu\.be/)[\w-]{6,}")


class StreamIn(BaseModel):
    url: str
    profile: str = "bmsd2026"


def _start(stream_id: int) -> None:
    from .worker import run_stream

    threading.Thread(target=run_stream, args=(stream_id,), daemon=True).start()


@app.post("/api/streams")
def create_stream(body: StreamIn):
    url = body.url.strip()
    if not (YOUTUBE_RE.match(url) or Path(url).exists()):
        raise HTTPException(400, "Paste a YouTube stream/VOD link (youtube.com/watch?v=..., /live/..., youtu.be/...)")
    with db.session() as s:
        st = db.Stream(url=url, profile=body.profile)
        s.add(st)
        s.commit()
        s.refresh(st)
        sid = st.id
    _start(sid)
    return {"id": sid}


@app.get("/api/streams")
def list_streams():
    with db.session() as s:
        rows = s.exec(select(db.Stream).order_by(db.Stream.id.desc())).all()  # type: ignore[union-attr]
        return [r.model_dump() for r in rows]


@app.get("/api/streams/{sid}")
def get_stream(sid: int):
    with db.session() as s:
        st = s.get(db.Stream, sid)
        if st is None:
            raise HTTPException(404, "stream not found")
        matches = s.exec(select(db.Match).where(db.Match.stream_id == sid).order_by(db.Match.idx)).all()
        return {"stream": st.model_dump(), "matches": [m.model_dump() for m in matches]}


@app.post("/api/streams/{sid}/retry")
def retry_stream(sid: int):
    with db.session() as s:
        st = s.get(db.Stream, sid)
        if st is None:
            raise HTTPException(404, "stream not found")
        for m in s.exec(select(db.Match).where(db.Match.stream_id == sid)).all():
            for model in (db.Observation, db.ZoneObs, db.TeamStatus, db.TeamInMatch):
                for row in s.exec(select(model).where(model.match_id == m.id)).all():
                    s.delete(row)
            s.delete(m)
        st.status, st.error, st.progress = "queued", "", 0.0
        s.add(st)
        s.commit()
    _start(sid)
    return {"ok": True}


@app.get("/api/matches/{mid}")
def get_match(mid: int):
    f = analytics.match_facts(mid)
    if f["match"] is None:
        raise HTTPException(404, "match not found")
    return f


@app.get("/api/teams")
def teams(stream_id: int | None = None):
    return analytics.all_teams(stream_id)


@app.get("/api/teams/{tag}/report")
def team_report(tag: str, stream_id: int | None = None):
    return analytics.team_report(tag.upper(), stream_id)


@app.get("/api/maps")
def maps():
    return [
        {"name": m.name, "size_km": m.size_km, "has_image": m.image_path.exists(), "display": list(m.display)}
        for m in MAPS.values()
    ]


@app.get("/api/maps/{name}/image")
def map_image(name: str):
    m = MAPS.get(name)
    if m is None or not m.image_path.exists():
        raise HTTPException(404, "map image not available")
    small = m.image_path.with_name(m.image_path.stem + "_2048.jpg")
    if not small.exists():
        img = cv2.imread(str(m.image_path), cv2.IMREAD_REDUCED_COLOR_4)
        cv2.imwrite(str(small), img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return FileResponse(small, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


# built frontend (npm run build -> frontend/dist)
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
