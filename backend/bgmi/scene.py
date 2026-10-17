"""Which overlay layout is on screen (or 'other' for desk, breaks, replays)."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .profile import Layout, Profile

MATCH_THRESHOLD = 0.6
SEARCH_MARGIN = 10  # px the overlay may shift between encodes


@dataclass
class SceneResult:
    layout: Layout | None
    score: float  # best mean fingerprint score

    @property
    def name(self) -> str:
        return self.layout.name if self.layout else "other"


def _fp_score(gray: np.ndarray, rect, ref: np.ndarray) -> float:
    x0, y0, x1, y1 = rect
    m = SEARCH_MARGIN
    H, W = gray.shape
    win = gray[max(0, y0 - m) : min(H, y1 + m), max(0, x0 - m) : min(W, x1 + m)]
    if win.shape[0] < ref.shape[0] or win.shape[1] < ref.shape[1]:
        return 0.0
    r = cv2.matchTemplate(win, ref, cv2.TM_CCOEFF_NORMED)
    return float(r.max())


def classify(img: np.ndarray, profile: Profile) -> SceneResult:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    best: tuple[float, Layout | None] = (0.0, None)
    for layout in profile.layouts:
        scores = [_fp_score(gray, fp.rect, fp.ref) for fp in layout.fingerprints if fp.ref is not None]
        if not scores:
            continue
        s = min(scores)  # every fingerprint must be present
        if s > best[0]:
            best = (s, layout)
    if best[0] < MATCH_THRESHOLD:
        return SceneResult(layout=None, score=best[0])
    return SceneResult(layout=best[1], score=best[0])
