"""Teams and players.

Teams come from the overlay (layout A side cards / layout B ranked table): tag text
("WELT", "8BIT") and alive bars. Players are learned from map name tags: a player name
usually starts with something like the team tag ("WELTwShyam", "iQOO8bitJUICY",
"BlitzEGEggy" for BLEG). Names that match no tag ("BAxTermix" for V1BA) are grouped by
shared prefix + tag colour and given to the team left over by elimination.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import cv2
import numpy as np
from rapidfuzz import fuzz

from . import ocr
from .profile import Layout

# OCR confusions between look-alike glyphs, folded before comparing
_FOLD = str.maketrans({"0": "O", "1": "I", "L": "I", "5": "S", "8": "B", "6": "G", "Q": "O", "D": "O", "U": "O"})


def fold(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper()).translate(_FOLD)


# ---------------------------------------------------------------------------
# reading the overlay
# ---------------------------------------------------------------------------


@dataclass
class TeamRow:
    tag: str
    alive: int | None  # 0..4, None if unreadable
    kills: int | None = None


def _alive_from_bars(crop: np.ndarray, slots: int = 4) -> int | None:
    """Alive players drawn as 4 bars/slashes: bright = alive, dim = dead."""
    if crop.size == 0:
        return None
    v = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[:, :, 2].astype(np.float32)
    w = v.shape[1] / slots
    lit = []
    for i in range(slots):
        col = v[:, int(i * w) : int((i + 1) * w)]
        lit.append(float(np.percentile(col, 95)))
    lit = np.array(lit)
    if lit.max() < 120:
        return 0
    return int((lit > 200).sum())


def read_team_cards(img: np.ndarray, layout: Layout) -> list[TeamRow]:
    """Layout A: 16 cards (logo + tag box + '////' alive bars)."""
    rows = []
    for x0, y0, x1, y1 in layout.team_cards:
        tag_crop = img[y1 - 26 : y1 - 2, x0 : x0 + 86]
        bars = img[y1 - 26 : y1 - 2, x0 + 98 : x1 - 2]
        text, conf = ocr.recognize(cv2.resize(tag_crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC))
        tag = re.sub(r"[^A-Za-z0-9]", "", text).upper()
        if conf < 0.5 or not tag:
            continue
        rows.append(TeamRow(tag=tag, alive=_alive_from_bars(bars)))
    return rows


def read_table(img: np.ndarray, layout: Layout) -> list[TeamRow]:
    """Layout B: ranked table rows '# | logo | TAG | FIN | status bars'."""
    if layout.table_first_row is None:
        return []
    x0, y0, x1, y1 = layout.table_first_row
    h = y1 - y0
    rows = []
    for i in range(layout.table_rows):
        oy = int(round(y0 + i * layout.table_row_pitch))
        row = img[oy : oy + h, x0:x1]
        tag_crop = row[int(h * 0.2) : int(h * 0.8), 140:260]
        fin_crop = row[int(h * 0.2) : int(h * 0.8), 265:320]
        bars = row[int(h * 0.15) : int(h * 0.85), 330:400]
        text, conf = ocr.recognize(cv2.resize(tag_crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC))
        tag = re.sub(r"[^A-Za-z0-9]", "", text).upper()
        if conf < 0.5 or not tag:
            continue
        kt, kc = ocr.recognize(cv2.resize(fin_crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC))
        kills = int(kt) if kt.isdigit() and kc > 0.6 else None
        rows.append(TeamRow(tag=tag, alive=_alive_from_bars(bars), kills=kills))
    return rows


def read_roster(img: np.ndarray, layout: Layout) -> list[TeamRow]:
    if layout.team_cards:
        return read_team_cards(img, layout)
    if layout.table_first_row:
        return read_table(img, layout)
    return []


# ---------------------------------------------------------------------------
# players -> teams
# ---------------------------------------------------------------------------


def prefix_score(name: str, tag: str) -> float:
    """How well `tag` appears, in order, near the start of `name`.

    1.0+ when the tag appears as-is ('WELTwShyam'/WELT, 'iQOO8bitJUICY'/8BIT), ~0.9 for an
    in-order subsequence ('BlitzEGEggy'/BLEG, 'NebulaPhOeNix'/NBE), lower otherwise.
    Longer tags and earlier matches score slightly higher, so 'GDRxNEYOO' prefers GDR over
    OR and 'iQOORNTXPAIN' prefers RNTX over OR.
    """
    n, t = fold(name), fold(tag)
    if not t or not n:
        return 0.0
    window = n[: len(t) + 6]
    pos = window.find(t)
    if pos >= 0:
        return 1.0 + 0.04 * len(t) - 0.01 * pos
    i = 0
    first = -1
    for k, ch in enumerate(n[: len(t) + 8]):
        if i < len(t) and ch == t[i]:
            if i == 0:
                first = k
            i += 1
    if i == len(t) and len(t) >= 3 and first == 0:
        return 0.9
    return i / len(t) * 0.7


@dataclass
class Player:
    team: str
    name: str  # most frequent spelling
    spellings: dict[str, int] = field(default_factory=dict)

    def add(self, s: str) -> None:
        self.spellings[s] = self.spellings.get(s, 0) + 1
        self.name = max(self.spellings, key=self.spellings.get)


@dataclass
class Book:
    """Per-match registry of teams, their colours and players."""

    teams: list[str] = field(default_factory=list)
    colors: dict[str, list[np.ndarray]] = field(default_factory=dict)
    players: list[Player] = field(default_factory=list)
    # names not yet attributable: folded prefix -> list of (name, color)
    pending: dict[str, list[tuple[str, np.ndarray]]] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)  # folded name prefix -> team

    def set_teams(self, tags: list[str]) -> None:
        for t in tags:
            if t not in self.teams:
                self.teams.append(t)
                self.colors.setdefault(t, [])

    def team_color(self, team: str) -> np.ndarray | None:
        c = self.colors.get(team)
        if not c:
            return None
        return np.median(np.array(c[-40:]), axis=0)

    def _by_prefix(self, name: str) -> tuple[str | None, float]:
        f = fold(name)
        for pre, team in self.aliases.items():
            if f.startswith(pre):
                return team, 1.0
        scored = sorted(((prefix_score(name, t), t) for t in self.teams), reverse=True)
        if not scored:
            return None, 0.0
        best, second = scored[0], scored[1] if len(scored) > 1 else (0.0, "")
        if best[0] >= 0.85 and best[0] - second[0] >= 0.03:
            return best[1], best[0]
        return None, best[0]

    def _by_color(self, color: np.ndarray, max_dist: float = 12.0) -> str | None:
        """Team whose learned colour is close AND clearly closer than any other team's
        (two teams with similar tag colours, e.g. two greys, never match by colour)."""
        ds = []
        for t in self.teams:
            c = self.team_color(t)
            if c is not None:
                ds.append((float(np.linalg.norm(c - color)), t))
        if not ds:
            return None
        ds.sort()
        if ds[0][0] >= max_dist:
            return None
        if len(ds) > 1 and ds[1][0] < 2.0 * ds[0][0] + 6:
            return None
        return ds[0][1]

    def _match_player(self, team: str, name: str, create: bool) -> Player | None:
        cands = [p for p in self.players if p.team == team]
        f = fold(name)
        best = max(cands, key=lambda p: fuzz.ratio(fold(p.name), f), default=None)
        if best is not None and fuzz.ratio(fold(best.name), f) >= 75:
            best.add(name)
            return best
        # fragments of a known name ('kipZ' of 'iQOO8bitSkipZ')
        if len(f) >= 4:
            part = max(cands, key=lambda p: fuzz.partial_ratio(f, fold(p.name)), default=None)
            if part is not None and fuzz.partial_ratio(f, fold(part.name)) >= 90:
                return part
        if not create or len(cands) >= 4:
            return None
        p = Player(team=team, name=name)
        p.add(name)
        self.players.append(p)
        return p

    def assign(self, name: str, color: tuple[float, float, float]) -> tuple[str | None, Player | None]:
        """Team (needed for analytics) and, when identifiable, the player."""
        col = np.array(color, np.float32)
        f = fold(name)
        # 1. a known player spelled similarly
        known = max(self.players, key=lambda p: fuzz.ratio(fold(p.name), f), default=None)
        if known is not None and fuzz.ratio(fold(known.name), f) >= 85:
            known.add(name)
            self.colors[known.team].append(col)
            return known.team, known
        # 2. team tag (or a learned alias) at the start of the name
        team, score = self._by_prefix(name)
        if team is not None:
            self.colors[team].append(col)
            return team, self._match_player(team, name, create=True)
        # 3. distinctive colour of an already-learned team
        team = self._by_color(col)
        if team is not None:
            return team, self._match_player(team, name, create=False)
        # 4. park it; resolved by elimination later (grouped by the team-ish 3-char prefix)
        key = f[:3]
        if len(key) == 3:
            self.pending.setdefault(key, []).append((name, col))
            self._eliminate()
        return None, None

    def _eliminate(self) -> None:
        """When exactly one team has never been seen, the one consistent group of
        unexplained names (same 3-char prefix, same colour, seen >= 5 times) is that team."""
        free = [t for t in self.teams if not self.colors.get(t)]
        if len(free) != 1:
            return
        groups = []
        for key, obs in self.pending.items():
            if len(obs) < 5:
                continue
            cols = np.array([c for _, c in obs])
            if np.median(np.linalg.norm(cols - np.median(cols, axis=0), axis=1)) > 8:
                continue
            groups.append((len(obs), key))
        if not groups:
            return
        groups.sort(reverse=True)
        if len(groups) > 1 and groups[1][0] > groups[0][0] * 0.5:
            return  # ambiguous
        key = groups[0][1]
        team = free[0]
        self.aliases[key] = team
        for n, c in self.pending.pop(key):
            self.colors[team].append(c)
            self._match_player(team, n, create=True)
