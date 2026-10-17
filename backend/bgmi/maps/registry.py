"""Known maps: size, town names (for map identification and label filtering), and the
reference image used as a display background.

Reference images come from PUBG's official developer assets
(https://github.com/pubg/api-assets, Assets/Maps/*_Main_High_Res.png) and are kept in
data/maps/ (not committed). Analysis coordinates come from the in-game grid on the
broadcast, not from these images.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

DATA_MAPS = Path(__file__).resolve().parents[3] / "data" / "maps"


@dataclass(frozen=True)
class MapInfo:
    name: str
    size_km: int
    towns: frozenset[str] = field(default_factory=frozenset)
    image: str = ""
    # broadcast km grid -> reference image, as fractions of the image size:
    # u = km_x / size * scale + du, v = km_y / size * scale + dv  (fitted with SIFT)
    display: tuple[float, float, float] = (1.0, 0.0, 0.0)

    @property
    def image_path(self) -> Path:
        return DATA_MAPS / self.image


MAPS: dict[str, MapInfo] = {
    "Erangel": MapInfo(
        "Erangel",
        8,
        frozenset(
            "Zharki, Severny, Stalber, Kameshki, Georgopol, Rozhok, Yasnaya Polyana, Lipovka, Hospital, "
            "Ruins, School, Gatka, Pochinki, Mylta, Prison, Shelter, Mansion, Farm, Quarry, Primorsk, "
            "Novorepnoye, Sosnovka Military Base, Sosnovka Island, Boatyard, Shooting Range, Ferry Pier, "
            "Mylta Power, Water Town".split(", ")
        ),
        "Erangel_High_Res.png",
        (0.984, 0.0008, -0.0022),
    ),
    "Miramar": MapInfo(
        "Miramar",
        8,
        frozenset(
            "La Cobreria, Torre Ahumada, Campo Militar, Tierra Bronca, Cruz del Valle, Hacienda del Patron, "
            "San Martin, El Pozo, Pecado, Monte Nuevo, Chumacera, Los Leones, Valle del Mar, Prison, "
            "Impala, Puerto Paraiso, El Azahar, Graveyard, Minas Generales, Ladrillera, Los Higos, "
            "Water Treatment, Power Grid, Junkyard, La Bendita, Minas del Sur, Oasis".split(", ")
        ),
        "Miramar_High_Res.png",
    ),
    "Sanhok": MapInfo(
        "Sanhok",
        4,
        frozenset(
            "Paradise Resort, Bootcamp, Ruins, Pai Nan, Camp Alpha, Camp Bravo, Camp Charlie, Ha Tinh, "
            "Tat Mok, Khao, Docks, Lakawi, Kampong, Na Kham, Sahmee, Bhan, Ban Tai, Mongnai, Quarry, "
            "Cave, Tambang, Training Center".split(", ")
        ),
        "Sanhok_High_Res.png",
    ),
    "Vikendi": MapInfo(
        "Vikendi",
        8,
        frozenset(
            "Castle, Dino Park, Volnova, Cosmodrome, Podvosto, Goroka, Villa, Trevno, Krichas, "
            "Hot Springs, Cement Factory, Peshkova, Abbey, Dobro Mesto, Port, Mosko, Coal Mine, Milnar, "
            "Tovar, Vihar, Zabava, Sawmill, Winery, Lumber Yard".split(", ")
        ),
        "Vikendi_High_Res.png",
    ),
    "Rondo": MapInfo(
        "Rondo",
        8,
        frozenset(
            "Jadena City, NEOX Factory, Tin Long Garden, Rin Jiang, Yu Lin, Stadium, Bok, Hung Lan, "
            "Su Ma, Long Shan, Test Field, Mey Ran, Jao Tin, Jiu Quan, Dragon Gate".split(", ")
        ),
        "Rondo_High_Res.png",
    ),
}

ALL_TOWNS: frozenset[str] = frozenset(t for m in MAPS.values() for t in m.towns)


def identify(words: list[str]) -> str | None:
    """Pick the map whose town names best match OCR'd map labels."""
    from rapidfuzz import fuzz

    scores = {}
    for name, m in MAPS.items():
        hits = 0
        for w in words:
            w = w.strip()
            if len(w) < 4:
                continue
            if any(fuzz.ratio(w.lower().replace(" ", ""), t.lower().replace(" ", "")) >= 82 for t in m.towns):
                hits += 1
        scores[name] = hits
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else None
