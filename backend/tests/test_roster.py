import numpy as np

from bgmi.roster import Book, prefix_score

TEAMS = ["WELT", "GENS", "WF", "TAG", "MYTH", "BLEG", "NBE", "GODL", "GDR", "NINZ", "SOUL", "K9", "8BIT", "OR", "RNTX", "V1BA"]


def best(name):
    return max(TEAMS, key=lambda t: prefix_score(name, t))


def test_prefix_matching_handles_sponsors_and_ocr_noise():
    assert best("WELTwShyam") == "WELT"
    assert best("BlitzEGEggy666") == "BLEG"
    assert best("NebulaPhOeNix") == "NBE"
    assert best("GORXNEYOO") == "GDR"  # D read as O must not go to OR
    assert best("iOOORNTXPAINO9") == "RNTX"
    assert best("i0008bitJUICY") == "8BIT"
    assert best("iQOOSouLlegitt") == "SOUL"
    assert best("K9xSnowJ") == "K9"


def test_fragments_do_not_match_by_subsequence():
    assert prefix_score("ELTwGokulwnl", "GODL") < 0.85
    assert prefix_score("LtaPG", "TAG") < 0.85


def test_elimination_assigns_last_team():
    b = Book()
    b.set_teams(TEAMS)
    b.set_teams(TEAMS)  # tags count after two roster reads
    rng = np.random.default_rng(0)
    # every team but V1BA seen with a distinct colour
    for i, t in enumerate(TEAMS[:-1]):
        name = {"8BIT": "iQOO8bitX", "SOUL": "iQOOSouLX", "RNTX": "iQOORNTXX", "BLEG": "BlitzEGX", "NBE": "NebulaPhoeNix"}.get(t, t + "xPlayer")
        b.assign(name, (40 + 10 * i, 120 + 3 * i, 120 - 3 * i))
    pink = (150.0, 175.0, 110.0)
    for k in range(6):
        team, _ = b.assign(f"BAx{['Termix', 'Omega', 'Punk', 'Shay'][k % 4]}VRI", tuple(np.add(pink, rng.normal(0, 1, 3))))
    team, player = b.assign("BAxTermixVRI", pink)
    assert team == "V1BA"
    assert b.aliases.get("BAX") == "V1BA"


def test_misread_tags_do_not_become_teams():
    b = Book()
    b.set_teams(TEAMS)
    b.set_teams(TEAMS)
    assert b.set_teams(["8BIL", "K92", "WF7", "8BI"]) == ["8BIT", "K9", "WF", "8BIT"]
    b.set_teams(["OB"] + TEAMS[1:])
    b.set_teams(["OB"] + TEAMS[1:])
    assert len(b.teams) == 16 and "OB" not in b.teams
