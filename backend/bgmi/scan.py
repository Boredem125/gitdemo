"""Pass 1: find the matches in a long map stream.

Grab one frame every `step` seconds (parallel seeks), classify the overlay layout and read
the match title ("DAY 1 - MATCH 2"). Continuous runs of map layouts become matches.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

import numpy as np

from . import ocr, scene, source
from .profile import Profile

TITLE_RE = re.compile(r"DAY\s*(\d{1,2})\s*\W*\s*MATCH\s*(\d{1,2})", re.I)
MAP_LAYOUTS = {"plane", "A", "B"}


@dataclass
class Sample:
    t: float
    layout: str
    day: int | None = None
    match_no: int | None = None


@dataclass
class MatchSpan:
    t_start: float
    t_end: float
    day: int | None
    match_no: int | None
    confidence: float
    note: str = ""


def read_title(img: np.ndarray, rect) -> tuple[int | None, int | None]:
    boxes = ocr.read_rect(img, rect, min_conf=0.5)
    m = TITLE_RE.search(" ".join(b.text for b in boxes).upper())
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def sample_stream(
    info: source.StreamInfo,
    profile: Profile,
    step: float = 60.0,
    workers: int = 6,
    on_progress: Callable[[float], None] | None = None,
    times: list[float] | None = None,
    read_titles: bool = True,
) -> list[Sample]:
    ts = times if times is not None else list(np.arange(0.0, max(info.duration - 1, 0), step))

    def job(t: float) -> Sample:
        img = source.grab(info.video_url, float(t))
        if img is None:
            return Sample(float(t), "missing")
        sc = scene.classify(img, profile)
        smp = Sample(float(t), sc.name)
        if read_titles and sc.layout is not None and sc.layout.title_rect is not None:
            smp.day, smp.match_no = read_title(img, sc.layout.title_rect)
        return smp

    out: list[Sample] = []
    with ThreadPoolExecutor(workers) as ex:
        for i, smp in enumerate(ex.map(job, ts)):
            out.append(smp)
            if on_progress and i % 10 == 0:
                on_progress(i / max(len(ts), 1))
    missing = sum(s.layout == "missing" for s in out)
    if missing > 0.5 * len(out):
        raise RuntimeError(f"could not read {missing}/{len(out)} frames from the video")
    return out


def find_matches(samples: list[Sample], step: float, max_gap: float = 150.0, min_len: float = 480.0) -> list[MatchSpan]:
    """Group map-layout samples into matches."""
    runs: list[list[Sample]] = []
    cur: list[Sample] = []
    last_map_t = -1e9
    for smp in samples:
        if smp.layout not in MAP_LAYOUTS:
            continue
        new_run = not cur or smp.t - last_map_t > max_gap
        if cur and not new_run and smp.match_no is not None:
            known = [c.match_no for c in cur if c.match_no is not None]
            if known and max(set(known), key=known.count) != smp.match_no and _stable_change(samples, smp):
                new_run = True
        if new_run and cur:
            runs.append(cur)
            cur = []
        cur.append(smp)
        last_map_t = smp.t
    if cur:
        runs.append(cur)

    spans = []
    for run in runs:
        t0, t1 = run[0].t, run[-1].t
        if t1 - t0 < min_len:
            continue
        days = [s.day for s in run if s.day is not None]
        nos = [s.match_no for s in run if s.match_no is not None]
        day = max(set(days), key=days.count) if days else None
        no = max(set(nos), key=nos.count) if nos else None
        agree = (nos.count(no) / len(nos)) if nos else 0.0
        has_start = any(s.layout in ("plane", "A") for s in run[:6])
        conf = 0.5 + 0.3 * agree + 0.2 * has_start
        note = "" if has_start else "start of match not seen (joined mid-match?)"
        spans.append(MatchSpan(max(0.0, t0 - step), t1 + step, day, no, round(conf, 2), note))
    return spans


def _stable_change(samples: list[Sample], at: Sample, k: int = 2) -> bool:
    """A match number change counts only if the next k titled samples agree (OCR noise)."""
    after = [s for s in samples if s.t > at.t and s.match_no is not None][:k]
    return len(after) == k and all(s.match_no == at.match_no for s in after)


def scan(
    info: source.StreamInfo,
    profile: Profile,
    coarse: float = 60.0,
    fine: float = 10.0,
    on_progress: Callable[[float], None] | None = None,
) -> list[MatchSpan]:
    """Coarse pass every `coarse` s, then refine each match's start/end at `fine` s."""
    samples = sample_stream(info, profile, step=coarse, on_progress=lambda p: on_progress and on_progress(0.8 * p))
    spans = find_matches(samples, coarse, max_gap=2.5 * coarse)
    extra: list[float] = []
    for sp in spans:
        # true start lies in (t_start, t_start + coarse]; true end in [t_end - coarse, t_end)
        extra += list(np.arange(sp.t_start + fine, sp.t_start + coarse, fine))
        extra += list(np.arange(sp.t_end - coarse + fine, sp.t_end, fine))
    if extra:
        more = sample_stream(info, profile, times=extra, read_titles=False)
        samples = sorted(samples + more, key=lambda s: s.t)
    if on_progress:
        on_progress(1.0)
    refined = []
    for sp in spans:
        inside = [s for s in samples if sp.t_start <= s.t <= sp.t_end and s.layout in MAP_LAYOUTS]
        if inside:
            sp.t_start = max(0.0, inside[0].t - fine)
            sp.t_end = inside[-1].t + fine
        refined.append(sp)
    return refined
