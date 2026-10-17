"""Map registration from the in-game map grid.

The broadcast map draws a 1 km grid plus a fainter 100 m sub-grid at every zoom level.
Frame -> map is an axis-aligned similarity (no rotation):

    x_px = ox + s * X_km        y_px = oy + s * Y_km

so we only need the scale `s` (px per km) and the offsets. Line spacing gives `s`
(up to the 100 m / 1 km ambiguity) and line phase gives the offsets modulo 100 m.
The absolute position comes from a prediction (previous frame + optical motion, or the
known full-view layout) and is snapped onto the detected lines.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class Transform:
    s: float  # px per km
    ox: float  # px of X_km = 0
    oy: float  # px of Y_km = 0

    def to_map(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.ox) / self.s, (y - self.oy) / self.s

    def to_px(self, X: float, Y: float) -> tuple[float, float]:
        return self.ox + self.s * X, self.oy + self.s * Y

    def compose_motion(self, scale: float, tx: float, ty: float) -> "Transform":
        """Apply frame motion p' = scale * p + t."""
        return Transform(self.s * scale, self.ox * scale + tx, self.oy * scale + ty)


@dataclass
class GridFit:
    period: float  # px between detected (minor) lines
    phase_x: float
    phase_y: float
    coherence: float  # 0..1, how well lines fit a single period
    n_lines: int
    # phase of the 1 km lines when they stand out from the 100 m sub-grid (frame px)
    major_x: float | None = None
    major_y: float | None = None


def line_profiles(gray: np.ndarray, mask: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Column / row profiles of long, thin, bright lines (scale tolerant)."""
    g = gray
    if mask is not None:
        g = np.where(mask > 0, gray, 0).astype(np.uint8)
    # white top-hat removes broad bright areas, keeps thin bright structures up to ~21 px wide
    th_v = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (21, 1)))
    th_h = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 21)))
    # keep only long structures: vertical lines survive a tall opening, horizontal a wide one
    v = cv2.morphologyEx(th_v, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 61)))
    h = cv2.morphologyEx(th_h, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (61, 1)))
    col = (v > 6).mean(axis=0)
    row = (h > 6).mean(axis=1)
    return col, row


def peaks(profile: np.ndarray, min_frac: float = 0.12) -> np.ndarray:
    """Centers of runs where the profile exceeds an adaptive threshold."""
    return peaks_with_height(profile, min_frac)[0]


def peaks_with_height(profile: np.ndarray, min_frac: float = 0.12) -> tuple[np.ndarray, np.ndarray]:
    """Run centers and run strength (sum of profile over the run, ~ line width x length)."""
    if profile.size == 0:
        return np.array([]), np.array([])
    thr = max(min_frac, float(np.percentile(profile, 60)) * 2.0)
    on = profile > thr
    out, hs = [], []
    i = 0
    n = len(profile)
    while i < n:
        if on[i]:
            j = i
            while j + 1 < n and on[j + 1]:
                j += 1
            w = profile[i : j + 1]
            out.append(i + float((np.arange(len(w)) * w).sum() / max(w.sum(), 1e-9)))
            hs.append(float(w.sum()))
            i = j + 1
        else:
            i += 1
    return np.array(out), np.array(hs)


def _axis_inliers(a: np.ndarray, period: float, tol: float) -> tuple[int, float]:
    """Best phase for one axis: max lines within tol of phase + k*period."""
    if len(a) == 0:
        return 0, 0.0
    best_n, best_ph = 0, 0.0
    for ph0 in a % period:
        d = (a - ph0) % period
        d = np.minimum(d, period - d)
        inl = d < tol
        n = int(inl.sum())
        if n > best_n:
            # refine phase as circular mean of inliers
            z = np.exp(2j * np.pi * a[inl] / period).mean()
            best_n, best_ph = n, float((np.angle(z) % (2 * np.pi)) / (2 * np.pi) * period)
    return best_n, best_ph


def fit_period(
    xs: np.ndarray, ys: np.ndarray, span_x: float, span_y: float, pmin: float, pmax: float
) -> GridFit | None:
    """Period in [pmin, pmax] that explains the most detected lines (spurious lines from
    roads, text or the zone ring are simply outliers)."""
    if len(xs) + len(ys) < 3:
        return None
    best: tuple[float, float, float, float, int] | None = None  # score, p, phx, phy, n
    total = len(xs) + len(ys)
    for p in np.arange(pmin, pmax, max(0.05, pmin * 0.004)):
        tol = max(2.0, 0.07 * p)
        nx, phx = _axis_inliers(xs, p, tol)
        ny, phy = _axis_inliers(ys, p, tol)
        slots = span_x / p + span_y / p  # lines that should be visible
        n = nx + ny
        if n < 3:
            continue
        recall = min(1.0, n / max(slots, 1.0))  # expected lines that were found
        precision = n / total  # detected lines the grid explains
        score = 2 * recall * precision / (recall + precision)
        if best is None or score > best[0]:
            best = (score, float(p), phx, phy, n)
    if best is None:
        return None
    score, p, phx, phy, n = best
    return GridFit(period=p, phase_x=phx, phase_y=phy, coherence=score, n_lines=n)


def detect(
    img: np.ndarray, region: tuple[int, int, int, int], s_hint: float, sub: int = 10
) -> tuple[GridFit, bool] | None:
    """Detect the grid in region (x0, y0, x1, y1) given an approximate scale (px/km).

    Tries both interpretations (sub-grid visible -> period ~ s/10; only 1 km lines -> ~ s)
    and returns (fit, is_sub_grid). Phases are in frame coordinates.
    """
    x0, y0, x1, y1 = region
    gray = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    col, row = line_profiles(gray)
    xs, hx = peaks_with_height(col)
    ys, hy = peaks_with_height(row)
    xs, ys = xs + x0, ys + y0
    out = []
    for is_sub, p0 in ((True, s_hint / sub), (False, s_hint)):
        if p0 < 7 or p0 > max(x1 - x0, y1 - y0) * 0.8:
            continue
        f = fit_period(xs, ys, x1 - x0, y1 - y0, p0 * 0.7, p0 * 1.45)
        if f is not None and f.n_lines >= 4:
            out.append((f, is_sub))
    if not out:
        return None
    fit, is_sub = max(out, key=lambda o: (o[0].coherence, o[0].n_lines))
    if is_sub:
        fit.major_x = _major_phase(xs, hx, fit.period, fit.phase_x, sub)
        fit.major_y = _major_phase(ys, hy, fit.period, fit.phase_y, sub)
    return fit, is_sub


def _major_phase(a: np.ndarray, h: np.ndarray, period: float, phase: float, sub: int) -> float | None:
    """1 km lines are drawn thicker/brighter: find the residue class (k mod sub) whose
    lines are clearly stronger than the rest."""
    if len(a) == 0:
        return None
    k = np.round((a - phase) / period)
    d = np.abs(a - (phase + k * period))
    inl = d < max(2.0, 0.07 * period)
    if inl.sum() < 2:
        return None
    k, h = k[inl].astype(int), h[inl]
    res = k % sub
    means = {r: float(h[res == r].mean()) for r in set(res.tolist())}
    if len(means) < 2:
        return None
    best = max(means, key=means.get)
    others = [v for r, v in means.items() if r != best]
    if means[best] < 1.6 * float(np.median(others)):
        return None
    return float(phase + best * period)


def snap(fit: GridFit, is_sub: bool, pred: Transform, sub: int = 10) -> Transform:
    """Snap a predicted transform onto the detected grid.

    Scale comes from the line period; each offset moves to the detected line phase nearest
    to the prediction. The prediction only has to be right to within half a line spacing
    (50 m when the sub-grid is visible).
    """
    s = fit.period * sub if is_sub else fit.period

    def snap_axis(o_pred: float, phase: float, major: float | None) -> float:
        # a visible 1 km line pins the offset exactly; the prediction only picks which km
        if major is not None:
            return major + round((o_pred - major) / s) * s
        k = round((o_pred - phase) / fit.period)
        return phase + k * fit.period

    # keep the predicted map point at the frame center fixed while the scale corrects
    cx, cy = 960.0, 540.0
    X, Y = pred.to_map(cx, cy)
    ox_pred, oy_pred = cx - s * X, cy - s * Y
    return Transform(
        s=s,
        ox=snap_axis(ox_pred, fit.phase_x, fit.major_x),
        oy=snap_axis(oy_pred, fit.phase_y, fit.major_y),
    )
