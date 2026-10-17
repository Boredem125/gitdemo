"""Frame -> map registration across a match.

Combines three signals:
  1. grid letters (A..H across, I..P down) when the full map is shown -> absolute km
  2. optical motion between consecutive frames (ORB + RANSAC similarity) -> prediction
  3. the grid itself (grid.detect + grid.snap) -> exact scale and offsets

Coordinates are km from the map's top-left corner, matching the in-game grid
(cell 'A','I' = [0,1) x [0,1)).
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from . import grid, ocr
from .grid import Transform
from .profile import Layout

FULL_VIEW_SCALE_GUESS = 140.0  # px per km when the whole 8 km map fits 1080 px


@dataclass
class RegResult:
    transform: Transform | None
    method: str  # letters | grid | motion | hold | none
    confidence: float


def _map_mask(shape: tuple[int, int], region: tuple[int, int, int, int]) -> np.ndarray:
    m = np.zeros(shape, np.uint8)
    x0, y0, x1, y1 = region
    m[y0:y1, x0:x1] = 255
    return m


class Registrar:
    def __init__(self) -> None:
        self.T: Transform | None = None
        self.prev_gray: np.ndarray | None = None
        self.prev_region: tuple[int, int, int, int] | None = None
        self.orb = cv2.ORB_create(nfeatures=1500, fastThreshold=12)
        self.since_letters = 10**9

    def reset(self) -> None:
        self.T = None
        self.prev_gray = None
        self.prev_region = None

    # -- motion ------------------------------------------------------------------
    def _motion(self, gray: np.ndarray, region) -> tuple[float, float, float] | None:
        """Similarity (scale, tx, ty) mapping previous frame px -> current frame px."""
        if self.prev_gray is None or self.prev_region is None:
            return None
        kp1, d1 = self.orb.detectAndCompute(self.prev_gray, _map_mask(gray.shape, self.prev_region))
        kp2, d2 = self.orb.detectAndCompute(gray, _map_mask(gray.shape, region))
        if d1 is None or d2 is None or len(kp1) < 20 or len(kp2) < 20:
            return None
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        pairs = matcher.knnMatch(d1, d2, k=2)
        good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < 0.8 * n.distance]
        if len(good) < 15:
            return None
        a = np.float32([kp1[m.queryIdx].pt for m in good])
        b = np.float32([kp2[m.trainIdx].pt for m in good])
        M, inl = cv2.estimateAffinePartial2D(a, b, method=cv2.RANSAC, ransacReprojThreshold=3.0)
        if M is None or inl is None or inl.sum() < 12:
            return None
        scale = float(np.hypot(M[0, 0], M[1, 0]))
        rot = abs(float(np.arctan2(M[1, 0], M[0, 0])))
        if rot > 0.02 or not 0.3 < scale < 3.5:
            return None
        return scale, float(M[0, 2]), float(M[1, 2])

    # -- letters -----------------------------------------------------------------
    def _letters(self, img: np.ndarray, layout: Layout, fit: grid.GridFit, s: float) -> Transform | None:
        """Read column / row letters next to each 1 km line and solve the absolute offsets."""
        if fit.major_x is None or fit.major_y is None or layout.col_letters_rect is None:
            return None
        mx0, my0, mx1, my1 = layout.map_region
        votes_x: list[float] = []
        votes_y: list[float] = []
        # columns: letter sits just right of each vertical 1 km line, in the top strip
        cy0, cy1 = layout.col_letters_rect[1], layout.col_letters_rect[3]
        x = fit.major_x + np.ceil((mx0 - fit.major_x) / s) * s
        while x < mx1 - 10:
            x0, x1 = int(x + 2), int(min(x + 0.45 * s, mx1))
            ch = _read_letter(img[cy0:cy1, x0:x1])
            if ch and "A" <= ch <= "H":
                votes_x.append(x - (ord(ch) - ord("A")) * s)
            x += s
        # rows: letter sits just below each horizontal 1 km line, in the left strip
        if layout.row_letters_rect is not None:
            rx0, rx1 = layout.row_letters_rect[0], layout.row_letters_rect[2] + 12
            y = fit.major_y + np.ceil((my0 - fit.major_y) / s) * s
            while y < my1 - 10:
                y0, y1 = int(y + 2), int(min(y + 0.4 * s, my1))
                ch = _read_letter(img[y0:y1, rx0:rx1])
                if ch and "I" <= ch <= "P":
                    votes_y.append(y - (ord(ch) - ord("I")) * s)
                y += s
        ox = _consensus(votes_x, s)
        if ox is None:
            return None
        oy = _consensus(votes_y, s)
        if oy is None:
            # rows unreadable: in the full view the map spans the viewport height
            if layout.full_view is not None:
                oy = layout.full_view[2] * s / layout.full_view[0]
            else:
                return None
        return Transform(s=s, ox=ox, oy=oy)

    # -- main --------------------------------------------------------------------
    def update(self, img: np.ndarray, layout: Layout) -> RegResult:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        region = layout.map_region
        motion = self._motion(gray, region)
        self.prev_gray, self.prev_region = gray, region

        pred: Transform | None = None
        method = "none"
        if self.T is not None:
            pred = self.T.compose_motion(*motion) if motion else self.T
            method = "motion" if motion else "hold"

        s_hint = pred.s if pred else (layout.full_view[0] if layout.full_view else FULL_VIEW_SCALE_GUESS)
        det = grid.detect(img, region, s_hint)
        if det is None and pred is None:
            # unknown zoom: try a few scales
            for s_try in (140.0, 260.0, 600.0, 1500.0):
                det = grid.detect(img, region, s_try)
                if det is not None and det[0].coherence > 0.5:
                    break
        if det is None:
            if pred is None:
                return RegResult(None, "none", 0.0)
            self.T = pred
            return RegResult(pred, method, 0.4 if motion else 0.2)

        fit, is_sub = det
        s = fit.period * 10 if is_sub else fit.period
        # absolute fix from grid letters when the whole map is in view
        self.since_letters += 1
        want_letters = layout.col_letters_rect is not None and s < 220 and (pred is None or self.since_letters > 15)
        if want_letters:
            T_abs = self._letters(img, layout, fit, s)
            if T_abs is not None:
                pred = T_abs
                method = "letters"
                self.since_letters = 0
        if pred is None:
            return RegResult(None, "none", 0.0)
        cx, cy = (region[0] + region[2]) / 2, (region[1] + region[3]) / 2

        def jump_of(T: Transform) -> float:
            return float(np.hypot(*np.subtract(T.to_map(cx, cy), pred.to_map(cx, cy))))

        # A good motion prediction is accurate to well under 50 m, so snap to the nearest
        # 100 m line. The 1 km line guess is only needed when we have no motion (it can
        # pick the wrong line class at deep zoom and shift the view by whole sub-steps).
        motion_ok = method in ("motion", "letters")
        T = grid.snap(fit, is_sub, pred, use_major=not motion_ok)
        jump = jump_of(T)
        if jump > 0.12 and not motion_ok:
            alt = grid.snap(fit, is_sub, pred, use_major=False)
            if jump_of(alt) < jump:
                T, jump = alt, jump_of(alt)
        conf = float(min(1.0, fit.coherence + 0.2))
        if jump > 0.12:
            # grid and prediction disagree: keep the prediction's position, take the grid's
            # scale, and flag the frame as unsure
            X, Y = pred.to_map(cx, cy)
            T = Transform(s=T.s, ox=cx - T.s * X, oy=cy - T.s * Y)
            conf *= 0.4
        self.T = T
        return RegResult(T, "letters" if method == "letters" else "grid", conf)


def _consensus(votes: list[float], s: float) -> float | None:
    """Most agreed-on offset (votes within 0.3 km of each other)."""
    if not votes:
        return None
    v = np.array(votes)
    best = max(v, key=lambda c: int((np.abs(v - c) < 0.3 * s).sum()))
    agree = v[np.abs(v - best) < 0.3 * s]
    if len(agree) < max(2, len(v) // 2):
        return None
    return float(agree.mean())


def _read_letter(crop: np.ndarray) -> str | None:
    if crop.size == 0 or crop.shape[0] < 6 or crop.shape[1] < 6:
        return None
    big = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    big = cv2.copyMakeBorder(big, 10, 10, 10, 10, cv2.BORDER_REPLICATE)
    text, conf = ocr.recognize(big)
    text = "".join(c for c in text.upper() if c.isalpha())
    if len(text) != 1 or conf < 0.5:
        return None
    return text
