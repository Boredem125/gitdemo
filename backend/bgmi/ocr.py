"""Thin wrapper around RapidOCR (ONNX, CPU).

Full detection is slow on CPU (~seconds per 1080p frame), so callers OCR small crops:
fixed overlay boxes with detection, or already-located name tags with recognition only
(~25 ms each).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np


@dataclass
class TextBox:
    text: str
    conf: float
    cx: float
    cy: float
    x0: float
    y0: float
    x1: float
    y1: float


@lru_cache(maxsize=1)
def engine():
    from rapidocr_onnxruntime import RapidOCR

    # default det config scales the *short* side up to 736 px, which makes thin strips huge;
    # cap the long side instead
    # BGMI_OCR_THREADS caps ONNX threads per process when several matches run in parallel
    threads = int(os.environ.get("BGMI_OCR_THREADS", "-1"))
    return RapidOCR(
        det_limit_type="max",
        det_limit_side_len=1280,
        intra_op_num_threads=threads,
        inter_op_num_threads=1 if threads > 0 else -1,
    )


def read(img: np.ndarray, offset: tuple[int, int] = (0, 0), min_conf: float = 0.5) -> list[TextBox]:
    """Detect + recognize text in an image crop. Coordinates are shifted by offset."""
    res, _ = engine()(img, use_cls=False)
    out = []
    ox, oy = offset
    for box, text, conf in res or []:
        if conf < min_conf:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        out.append(
            TextBox(
                text=text.strip(),
                conf=float(conf),
                cx=float(sum(xs) / 4 + ox),
                cy=float(sum(ys) / 4 + oy),
                x0=float(min(xs) + ox),
                y0=float(min(ys) + oy),
                x1=float(max(xs) + ox),
                y1=float(max(ys) + oy),
            )
        )
    return out


def read_rect(
    img: np.ndarray, rect: tuple[int, int, int, int], min_conf: float = 0.5, scale: float = 1.0, pad: int = 0
) -> list[TextBox]:
    """OCR a rectangle of the frame. `scale`/`pad` help with tiny glyphs (grid letters)."""
    x0, y0, x1, y1 = rect
    crop = img[y0:y1, x0:x1]
    if pad:
        crop = cv2.copyMakeBorder(crop, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
    if scale != 1.0:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    boxes = read(crop, min_conf=min_conf)
    for b in boxes:
        for a in ("cx", "x0", "x1"):
            setattr(b, a, getattr(b, a) / scale - pad + x0)
        for a in ("cy", "y0", "y1"):
            setattr(b, a, getattr(b, a) / scale - pad + y0)
    return boxes


def recognize(crop: np.ndarray) -> tuple[str, float]:
    """Recognition only, for a crop that holds a single line of text."""
    if crop.size == 0:
        return "", 0.0
    res, _ = engine()(crop, use_det=False, use_cls=False, use_rec=True)
    if not res:
        return "", 0.0
    text, conf = res[0]
    return str(text).strip(), float(conf)
