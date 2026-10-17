import cv2
import numpy as np

from bgmi.zone import blue_edge, white_ring


def test_dashed_white_ring_found_with_clutter():
    rng = np.random.default_rng(3)
    img = (rng.normal(60, 10, (1080, 1920, 3))).clip(0, 255).astype(np.uint8)
    cx, cy, r = 980, 600, 310
    for a0 in np.arange(0, 360, 6):  # dashed ring
        cv2.ellipse(img, (cx, cy), (r, r), 0, a0, a0 + 3.5, (255, 255, 255), 2)
    for i in range(12):  # white text-like clutter
        cv2.putText(img, "WELTwShyam", (rng.integers(450, 1300), rng.integers(50, 1000)), 0, 0.7, (255, 255, 255), 2)
    c = white_ring(img, (430, 0, 1490, 1080))
    assert c is not None
    assert abs(c.cx - cx) < 4 and abs(c.cy - cy) < 4 and abs(c.r - r) < 4


def test_blue_edge_contains_white():
    img = np.zeros((1080, 1920, 3), np.uint8)
    img[:] = (200, 90, 40)  # blue tint (BGR) outside
    cv2.circle(img, (960, 540), 400, (60, 120, 70), -1)  # natural colours inside
    cv2.line(img, (430, 300), (1490, 320), (200, 200, 200), 25)  # a road through everything
    w = white_ring(img, (430, 0, 1490, 1080))
    b = blue_edge(img, (430, 0, 1490, 1080), contains=w)
    assert b is not None
    assert abs(b.cx - 960) < 8 and abs(b.cy - 540) < 8 and abs(b.r - 400) < 10
