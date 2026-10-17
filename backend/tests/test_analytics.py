from bgmi import db
from bgmi.analytics import _status, team_tracks, zone_phases, Phase


def Z(t, r, cx=4.0, cy=4.0):
    return db.ZoneObs(match_id=1, t=t, kind="white", cx=cx, cy=cy, r=r, support=0.9)


def test_zone_phases_split_on_shrink_and_ignore_outliers():
    zs = [Z(t, 2.0) for t in range(0, 300, 15)] + [Z(130, 0.7)]  # one bad detection
    zs += [Z(t, 1.2, 4.3, 4.1) for t in range(300, 500, 15)]
    zs += [Z(t, 0.6, 4.4, 4.2) for t in range(500, 650, 15)]
    ph = zone_phases(zs)
    assert [round(p.r, 1) for p in ph] == [2.0, 1.2, 0.6]
    assert ph[0].t_end == ph[1].t_start == 300


def test_status_bands():
    p = Phase(1, 0, 100, 4.0, 4.0, 1.0)
    assert _status(4.5, 4.0, p)[0] == "inside"
    assert _status(5.0, 4.0, p)[0] == "edge"
    assert _status(5.5, 4.0, p)[0] == "outside"


def test_tracks_despike():
    obs = [db.Observation(match_id=1, t=t, team="K9", x=1 + t / 1000, y=1, conf=1) for t in range(0, 200, 10)]
    obs.append(db.Observation(match_id=1, t=100, team="K9", x=7, y=7, conf=1))  # wrong for its bin? median handles
    obs += [db.Observation(match_id=1, t=105, team="K9", x=7, y=7, conf=1), db.Observation(match_id=1, t=106, team="K9", x=7, y=7, conf=1)]
    tr = team_tracks(obs)["K9"]
    assert all(p.x < 2 for p in tr)
