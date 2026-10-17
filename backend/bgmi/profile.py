"""Overlay profiles: where things are on screen for a given broadcast package.

A profile lists the layouts the map stream switches between. Each layout has
fingerprint crops (static overlay graphics used to recognise it), the map viewport, and
where the match title / team table live. Supporting a new tournament overlay means adding
a profile folder, not code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

PROFILES_DIR = Path(__file__).parent / "profiles"

Rect = tuple[int, int, int, int]  # x0, y0, x1, y1 in 1920x1080 frame px


@dataclass
class Fingerprint:
    rect: Rect
    image: str  # file name inside the profile folder (grayscale png)
    ref: np.ndarray | None = None


@dataclass
class Layout:
    name: str
    map_region: Rect
    fingerprints: list[Fingerprint]
    title_rect: Rect | None = None  # e.g. "GRAND FINALS // DAY 1 - MATCH 2"
    # grid letters strip (top) and row letters strip (left) for absolute calibration
    col_letters_rect: Rect | None = None
    row_letters_rect: Rect | None = None
    # layout B ranked table: first row rect + row pitch + count
    table_first_row: Rect | None = None
    table_row_pitch: float = 0.0
    table_rows: int = 0
    # layout A side panels: list of team card rects (tag box + alive bars)
    team_cards: list[Rect] = field(default_factory=list)
    # optional known full-view transform (s, ox, oy) used as a starting guess
    full_view: tuple[float, float, float] | None = None


@dataclass
class Profile:
    name: str
    layouts: list[Layout]
    folder: Path

    def layout(self, name: str) -> Layout:
        return next(l for l in self.layouts if l.name == name)


def _rect(v) -> Rect:
    return tuple(int(x) for x in v)  # type: ignore[return-value]


def load(name: str) -> Profile:
    folder = PROFILES_DIR / name
    data = json.loads((folder / "profile.json").read_text())
    layouts = []
    for L in data["layouts"]:
        fps = []
        for fp in L["fingerprints"]:
            f = Fingerprint(rect=_rect(fp["rect"]), image=fp["image"])
            f.ref = cv2.imread(str(folder / fp["image"]), cv2.IMREAD_GRAYSCALE)
            fps.append(f)
        layouts.append(
            Layout(
                name=L["name"],
                map_region=_rect(L["map_region"]),
                fingerprints=fps,
                title_rect=_rect(L["title_rect"]) if L.get("title_rect") else None,
                col_letters_rect=_rect(L["col_letters_rect"]) if L.get("col_letters_rect") else None,
                row_letters_rect=_rect(L["row_letters_rect"]) if L.get("row_letters_rect") else None,
                table_first_row=_rect(L["table_first_row"]) if L.get("table_first_row") else None,
                table_row_pitch=float(L.get("table_row_pitch", 0)),
                table_rows=int(L.get("table_rows", 0)),
                team_cards=[_rect(r) for r in L.get("team_cards", [])],
                full_view=tuple(L["full_view"]) if L.get("full_view") else None,  # type: ignore[arg-type]
            )
        )
    return Profile(name=data["name"], layouts=layouts, folder=folder)


def available() -> list[str]:
    return sorted(p.name for p in PROFILES_DIR.iterdir() if (p / "profile.json").exists())
