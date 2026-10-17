"""Player name tags on the broadcast map.

Every player is drawn as a numbered circle filled with the team colour plus a name tag
(team-coloured box, white text, e.g. "WELTwShyam"). Circles are often hidden under
other tags and look like vehicle icons, so the tag is the detection and its centre is
the player position (tags sit next to their marker: error ~30 px, i.e. ~200 m at full
view and a few metres zoomed in - fine for team-level drops, rotations and zone play).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import cv2
import numpy as np

from . import ocr
from .grid import Transform


@dataclass
class Tag:
    text: str
    conf: float
    box: tuple[float, float, float, float]  # x0, y0, x1, y1 frame px
    color: tuple[float, float, float]  # Lab of the tag background
    color_std: float
    anchor: tuple[float, float]  # player position, frame px
    km: tuple[float, float] | None = None


_NAME_RE = re.compile(r"[A-Za-z0-9]")


def _bg_color(img: np.ndarray, box) -> tuple[tuple[float, float, float], float] | None:
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    H, W = img.shape[:2]
    x0, y0, x1, y1 = max(0, x0 - 2), max(0, y0 - 3), min(W, x1 + 2), min(H, y1 + 3)
    patch = img[y0:y1, x0:x1]
    if patch.size == 0:
        return None
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.float32)
    px = patch.reshape(-1, 3)
    # drop white text pixels
    keep = ~((hsv[:, 2] > 185) & (hsv[:, 1] < 70))
    if keep.sum() < 20:
        return None
    lab = cv2.cvtColor(px[keep].reshape(-1, 1, 3), cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
    med = np.median(lab, axis=0)
    std = float(np.median(np.abs(lab - med)) * 1.4826)  # robust spread
    return (float(med[0]), float(med[1]), float(med[2])), std


def _is_town(text: str, towns: set[str]) -> bool:
    """Map labels get cut by the viewport or merged with digits ('ospital', '4Primorsk')."""
    from rapidfuzz import fuzz

    t = re.sub(r"[^a-z]", "", text.lower())
    if len(t) < 3:
        return True
    return any(fuzz.partial_ratio(t, town) >= 85 and len(t) <= len(town) + 2 for town in towns)


def detect_tags(
    img: np.ndarray,
    region: tuple[int, int, int, int],
    T: Transform | None = None,
    town_names: set[str] | None = None,
) -> list[Tag]:
    x0, y0, x1, y1 = region
    boxes = ocr.read(img[y0:y1, x0:x1], offset=(x0, y0), min_conf=0.55)
    towns = {re.sub(r"[^a-z]", "", t.lower()) for t in (town_names or set())}
    tags: list[Tag] = []
    for b in boxes:
        text = b.text.replace(" ", "")
        if len(text) < 3 or not _NAME_RE.search(text):
            continue
        h = b.y1 - b.y0
        if h > 40:  # big map labels (town names when zoomed in)
            continue
        if towns and _is_town(text, towns):
            continue
        bg = _bg_color(img, (b.x0, b.y0, b.x1, b.y1))
        if bg is None:
            continue
        color, std = bg
        if std > 18:  # tags are flat colour boxes; map labels sit on textured terrain
            continue
        anchor = ((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2)
        tag = Tag(
            text=text,
            conf=b.conf,
            box=(b.x0, b.y0, b.x1, b.y1),
            color=color,
            color_std=std,
            anchor=anchor,
        )
        if T is not None:
            tag.km = T.to_map(*anchor)
        tags.append(tag)
    return tags
