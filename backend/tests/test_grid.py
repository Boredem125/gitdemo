import cv2
import numpy as np
import pytest

from bgmi import grid
from bgmi.grid import Transform


def synth(T: Transform, size=(1080, 1920), noise=8, seed=0) -> np.ndarray:
    """Textured background with a 1 km grid (thick) and 100 m sub-grid (thin)."""
    rng = np.random.default_rng(seed)
    img = (rng.normal(70, noise, size + (3,))).clip(0, 255).astype(np.uint8)
    img = cv2.GaussianBlur(img, (5, 5), 0)
    H, W = size
    k0 = int(np.floor(-T.ox / T.s * 10)) - 1
    k1 = int(np.ceil((W - T.ox) / T.s * 10)) + 1
    for k in range(k0, k1):
        x = int(round(T.ox + k * T.s / 10))
        cv2.line(img, (x, 0), (x, H), (200, 210, 200), 3 if k % 10 == 0 else 1)
    k0 = int(np.floor(-T.oy / T.s * 10)) - 1
    k1 = int(np.ceil((H - T.oy) / T.s * 10)) + 1
    for k in range(k0, k1):
        y = int(round(T.oy + k * T.s / 10))
        cv2.line(img, (0, y), (W, y), (200, 210, 200), 3 if k % 10 == 0 else 1)
    return img


@pytest.mark.parametrize("s", [136.3, 260.0, 650.0, 1600.0])
def test_detect_and_snap_recovers_transform(s):
    true = Transform(s=s, ox=430.0 - 2.37 * s, oy=10.0 - 3.61 * s)
    img = synth(true)
    region = (430, 0, 1490, 1080)
    det = grid.detect(img, region, s_hint=s * 1.15)
    assert det is not None
    fit, is_sub = det
    # prediction: view centre off by 30 m, scale off by 12% (as from frame-to-frame motion)
    cx, cy = 960, 540
    Xt, Yt = true.to_map(cx, cy)
    ps = s * 1.12
    pred = Transform(s=ps, ox=cx - ps * (Xt + 0.03), oy=cy - ps * (Yt - 0.03))
    T = grid.snap(fit, is_sub, pred, use_major=False)
    X, Y = T.to_map(cx, cy)
    Xt, Yt = true.to_map(cx, cy)
    assert abs(T.s - s) / s < 0.01
    assert abs(X - Xt) < 0.01 and abs(Y - Yt) < 0.01  # within 10 m


def test_major_lines_found():
    true = Transform(s=300.0, ox=430 - 1.5 * 300, oy=-0.2 * 300)
    fit, is_sub = grid.detect(synth(true), (430, 0, 1490, 1080), s_hint=300)
    assert is_sub
    assert fit.major_x is not None
    # major phase must coincide with a 1 km line
    k = (fit.major_x - true.ox) / true.s
    assert abs(k - round(k)) < 0.02
