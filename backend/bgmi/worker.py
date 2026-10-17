"""Background job: stream URL -> matches -> per-match analysis (parallel processes)."""

from __future__ import annotations

import os
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed

from . import db, profile, source
from .scan import scan

MATCH_WORKERS = int(os.environ.get("BGMI_MATCH_WORKERS", "3"))


def _match_job(match_id: int, url: str, profile_name: str, t0: float, t1: float) -> dict:
    # each process: limit ONNX threads so parallel matches don't fight over cores
    os.environ.setdefault("BGMI_OCR_THREADS", str(max(2, (os.cpu_count() or 8) // MATCH_WORKERS)))
    from .process import process_match

    db.update(db.Match, match_id, status="processing")
    last = [0.0]

    def prog(p: float) -> None:
        if p - last[0] >= 0.02:
            last[0] = p
            db.update(db.Match, match_id, progress=round(p, 3))

    try:
        stats = process_match(match_id, url, profile_name, t0, t1, on_progress=prog)
        db.update(db.Match, match_id, status="done", progress=1.0, map=stats.get("map"))
        return stats
    except Exception as e:  # noqa: BLE001 - report any failure on the match row
        db.update(db.Match, match_id, status="failed", note=f"{type(e).__name__}: {e}")
        traceback.print_exc()
        return {"error": str(e)}


def run_stream(stream_id: int) -> None:
    with db.session() as s:
        st = s.get(db.Stream, stream_id)
        url, profile_name = st.url, st.profile
    try:
        db.update(db.Stream, stream_id, status="scanning", stage="resolving stream")
        info = source.resolve(url)
        db.update(db.Stream, stream_id, title=info.title, duration=info.duration, stage="finding matches")
        P = profile.load(profile_name)

        def scan_prog(p: float) -> None:
            db.update(db.Stream, stream_id, progress=round(0.2 * p, 3))

        spans = scan(info, P, on_progress=scan_prog)
        if not spans:
            db.update(db.Stream, stream_id, status="failed", error="No matches found in this stream (is it a map stream?)")
            return
        ids = []
        with db.session() as s:
            for k, sp in enumerate(spans):
                m = db.Match(
                    stream_id=stream_id,
                    idx=k,
                    day=sp.day,
                    match_no=sp.match_no,
                    t_start=sp.t_start,
                    t_end=sp.t_end,
                    confidence=sp.confidence,
                    note=sp.note,
                )
                s.add(m)
                s.commit()
                s.refresh(m)
                ids.append((m.id, sp))
        db.update(db.Stream, stream_id, status="processing", stage=f"analysing {len(ids)} matches", progress=0.2)

        done = 0
        with ProcessPoolExecutor(MATCH_WORKERS) as ex:
            futs = [ex.submit(_match_job, mid, url, profile_name, sp.t_start, sp.t_end) for mid, sp in ids]
            for f in as_completed(futs):
                f.result()
                done += 1
                db.update(db.Stream, stream_id, progress=round(0.2 + 0.8 * done / len(futs), 3), stage=f"analysed {done}/{len(futs)} matches")
        db.update(db.Stream, stream_id, status="done", stage="done", progress=1.0)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        db.update(db.Stream, stream_id, status="failed", error=f"{type(e).__name__}: {e}")
