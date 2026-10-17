"""Safe-zone circles on the broadcast map.

- next zone: thin white (dashed) ring
- current zone (blue zone edge): border between the blue-tinted outside and the natural
  colours inside

Both are found as circles by RANSAC on candidate edge points in frame px, then converted
to km with the frame transform. Circles may extend far outside the viewport (early game
when zoomed in), so only arcs are needed.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .grid import Transform


@dataclass
class Circle:
    cx: float  # frame px
    cy: float
    r: float
    support: float  # fraction of the visible circumference with evidence
    kind: str  # "white" | "blue"

    def to_km(self, T: Transform) -> tuple[float, float, float]:
        X, Y = T.to_map(self.cx, self.cy)
        return X, Y, self.r / T.s


def _ransac_circle(
    pts: np.ndarray,
    region: tuple[int, int, int, int],
    r_min: float,
    r_max: float,
    tol: float = 2.5,
    iters: int = 1500,
    rng: np.random.Generator | None = None,
    accept=None,
) -> tuple[float, float, float, float] | None:
    """Best circle (cx, cy, r, support) through 2D points; support = fraction of the
    circle arc inside `region` that has inlier points."""
    if len(pts) < 30:
        return None
    rng = rng or np.random.default_rng(0)
    best = None
    n = len(pts)
    for _ in range(iters):
        a, b, c = pts[rng.choice(n, 3, replace=False)]
        # circumcircle
        d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
        if abs(d) < 1e-6:
            continue
        ux = ((a @ a) * (b[1] - c[1]) + (b @ b) * (c[1] - a[1]) + (c @ c) * (a[1] - b[1])) / d
        uy = ((a @ a) * (c[0] - b[0]) + (b @ b) * (a[0] - c[0]) + (c @ c) * (b[0] - a[0])) / d
        r = float(np.hypot(a[0] - ux, a[1] - uy))
        if not r_min <= r <= r_max:
            continue
        if accept is not None and not accept(ux, uy, r):
            continue
        dist = np.abs(np.hypot(pts[:, 0] - ux, pts[:, 1] - uy) - r)
        inl = int((dist < tol).sum())
        if best is None or inl > best[0]:
            best = (inl, ux, uy, r)
    if best is None:
        return None
    _, ux, uy, r = best
    # refine with least squares on inliers
    dist = np.abs(np.hypot(pts[:, 0] - ux, pts[:, 1] - uy) - r)
    P = pts[dist < tol * 1.5]
    if len(P) >= 10:
        A = np.c_[2 * P[:, 0], 2 * P[:, 1], np.ones(len(P))]
        bb = (P**2).sum(1)
        sol, *_ = np.linalg.lstsq(A, bb, rcond=None)
        ux, uy = sol[0], sol[1]
        r = float(np.sqrt(max(sol[2] + ux**2 + uy**2, 1.0)))
    support = _arc_support(pts, ux, uy, r, region, tol * 1.5)
    return float(ux), float(uy), r, support


def _arc_support(pts, cx, cy, r, region, tol) -> float:
    """Fraction of the circle's visible arc (inside region) covered by inlier points."""
    x0, y0, x1, y1 = region
    angles = np.linspace(0, 2 * np.pi, 720, endpoint=False)
    ax, ay = cx + r * np.cos(angles), cy + r * np.sin(angles)
    vis = (ax > x0 + 3) & (ax < x1 - 3) & (ay > y0 + 3) & (ay < y1 - 3)
    if vis.sum() < 20:
        return 0.0
    d = np.abs(np.hypot(pts[:, 0] - cx, pts[:, 1] - cy) - r)
    inl = pts[d < tol]
    if len(inl) == 0:
        return 0.0
    th = (np.arctan2(inl[:, 1] - cy, inl[:, 0] - cx)) % (2 * np.pi)
    bins = np.zeros(720, bool)
    bins[(th / (2 * np.pi) * 720).astype(int) % 720] = True
    # dashed ring: count a bin as covered if a neighbour within 3 bins has points
    covered = np.convolve(bins.astype(int), np.ones(7, int), mode="same") > 0
    return float((covered & vis).sum() / vis.sum())


def _mask_out(mask: np.ndarray, boxes: list[tuple[float, float, float, float]], pad: int = 6) -> None:
    for x0, y0, x1, y1 in boxes:
        mask[max(0, int(y0) - pad) : int(y1) + pad, max(0, int(x0) - pad) : int(x1) + pad] = 0


def white_ring(
    img: np.ndarray, region: tuple[int, int, int, int], ignore: list[tuple[float, float, float, float]] = ()
) -> Circle | None:
    x0, y0, x1, y1 = region
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    white = ((hsv[:, :, 2] > 200) & (hsv[:, :, 1] < 45)).astype(np.uint8)
    roi = np.zeros_like(white)
    roi[y0:y1, x0:x1] = white[y0:y1, x0:x1]
    _mask_out(roi, list(ignore))
    # the ring is thin: remove blobs (text, icons) by keeping pixels with few white
    # neighbours in a 7x7 window
    dens = cv2.boxFilter(roi.astype(np.float32), -1, (9, 9), normalize=True)
    thin = (roi > 0) & (dens < 0.30)
    ys, xs = np.nonzero(thin)
    if len(xs) < 40:
        return None
    pts = np.c_[xs, ys].astype(np.float64)
    if len(pts) > 6000:
        pts = pts[np.random.default_rng(1).choice(len(pts), 6000, replace=False)]
    res = _ransac_circle(pts, region, r_min=40, r_max=6000)
    if res is None or res[3] < 0.35:
        return None
    return Circle(*res[:3], support=res[3], kind="white")


def blue_edge(
    img: np.ndarray,
    region: tuple[int, int, int, int],
    ignore: list[tuple[float, float, float, float]] = (),
    contains: Circle | None = None,
) -> Circle | None:
    """`contains`: the white (next-zone) ring, which must lie inside the blue edge."""
    x0, y0, x1, y1 = region
    hsv = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0].astype(int), hsv[:, :, 1].astype(int), hsv[:, :, 2].astype(int)
    blue = ((h >= 105) & (h <= 130) & (s > 80) & (v > 50)).astype(np.uint8)
    frac = blue.mean()
    if frac < 0.05 or frac > 0.97:
        return None
    # inside the zone = not tinted. Open with a big disk so roads, labels and tags (thin,
    # desaturated) inside the tinted area don't count as "inside".
    k = max(15, int(min(x1 - x0, y1 - y0) * 0.035)) | 1
    inside = cv2.morphologyEx(1 - blue, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    blue = 1 - inside
    edges = cv2.morphologyEx(blue, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    full = np.zeros(img.shape[:2], np.uint8)
    full[y0:y1, x0:x1] = edges
    # viewport border is not a zone edge
    full[y0 : y0 + 4, :] = 0
    full[y1 - 4 : y1, :] = 0
    full[:, x0 : x0 + 4] = 0
    full[:, x1 - 4 : x1] = 0
    _mask_out(full, list(ignore))
    ys, xs = np.nonzero(full)
    if len(xs) < 40:
        return None
    pts = np.c_[xs, ys].astype(np.float64)
    if len(pts) > 6000:
        pts = pts[np.random.default_rng(2).choice(len(pts), 6000, replace=False)]
    diag = float(np.hypot(x1 - x0, y1 - y0))

    def accept(cx: float, cy: float, r: float) -> bool:
        if contains is None:
            return r < 3 * diag
        d = float(np.hypot(cx - contains.cx, cy - contains.cy))
        return d + contains.r <= r + 8 and r < max(3 * diag, 4 * contains.r)

    res = _ransac_circle(pts, region, r_min=40, r_max=8000, tol=3.0, accept=accept)
    if res is None or res[3] < 0.35:
        return None
    return Circle(*res[:3], support=res[3], kind="blue")
