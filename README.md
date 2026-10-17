# BGMI Esports Analyzer

Paste a BGMI tournament **[MAP STREAM]** link (e.g. Krafton India Esports' BMSD map streams) and get, for every team in every match:

- **Drop spot** (and whether it was contested)
- **Rotation path** over the match
- **Zone play**: inside / edge / outside when each new zone is revealed, and how long it took to get in
- Placement, kills, players, and cross-match **team reports** (drop heatmap, rotations, zone tendencies)

No manual timestamps or calibration: matches, maps and teams are detected from the broadcast overlay.

## How it works

| Step | Module | What |
|---|---|---|
| Video | `source.py` | yt-dlp resolves the stream; bundled ffmpeg decodes keyframes (~every 5 s) |
| Matches | `scan.py` | coarse frame sampling + overlay layout + "DAY 1 – MATCH 2" title OCR → match spans |
| Layout | `scene.py`, `profiles/` | fingerprints of the overlay (plane view, full map, zoomed map + table) |
| Map position | `grid.py`, `register.py` | the in-game 1 km / 100 m grid gives an exact px→km transform at any zoom; grid letters give absolute position; ORB motion tracks between frames |
| Players | `markers.py`, `roster.py` | OCR of team-coloured name tags; team from tag prefix (`WELTwShyam` → WELT), colour, or elimination (`BAx…` → V1BA) |
| Zone | `zone.py` | RANSAC circles: white next-zone ring, blue-zone edge |
| Facts | `analytics.py` | team tracks, drops, zone phases, inside/edge/outside, rotation timing |
| API / UI | `api.py`, `frontend/` | FastAPI + React |

Coordinates are km in the in-game grid (Erangel: 0–8). The PUBG reference map images (official [pubg/api-assets](https://github.com/pubg/api-assets)) are only used as the display background.

## Run locally

Requirements: Python 3.11+, Node 20+. No GPU needed.

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # Linux/macOS: .venv/bin/python
```

Map images (display background, ~500 MB, not committed):

```bash
mkdir -p data/maps
for m in Erangel Miramar Sanhok Vikendi Rondo; do
  curl -L -o data/maps/${m}_High_Res.png https://media.githubusercontent.com/media/pubg/api-assets/master/Assets/Maps/${m}_Main_High_Res.png
done
```

Start API and web UI:

```bash
cd backend && .venv/Scripts/python -m uvicorn bgmi.api:app --port 8000
cd frontend && npm install && npm run dev        # http://localhost:5173
```

Tests: `cd backend && .venv/Scripts/python -m pytest`

Processing a 7 h stream is CPU-heavy (OCR). Matches run in parallel processes (`BGMI_MATCH_WORKERS`, default 3).

## Supporting a new tournament overlay

Add `backend/bgmi/profiles/<name>/profile.json` with each layout's fingerprint crops, map viewport, title box and team table/cards (see `bmsd2026`). No code changes.

## Accuracy notes

- Player position = name-tag centre (tags sit next to the marker): ~200 m error at full-map zoom, a few metres when zoomed in. Team-level analysis uses the median of the team's tags.
- Every observation carries a confidence; low-confidence registration frames are dropped.

## Legal

Broadcast footage and map art belong to Krafton and tournament organisers. The tool stores only derived data (positions, circles, team facts), never video. Downloading from YouTube may violate YouTube's Terms of Service; for commercial use, get organiser permission or use VOD files supplied by the organiser.
