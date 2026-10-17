import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, matchLabel, type MapInfo, type TeamReport } from "../api";
import { MapCanvas, teamColor, type Layer } from "../components/MapCanvas";

const PALETTE = ["#ff7a59", "#4fc3f7", "#ffd54f", "#81c784", "#ba68c8", "#f06292", "#4db6ac", "#e57373", "#9575cd", "#aed581"];

export function TeamPage() {
  const tag = useParams().tag!;
  const [sp] = useSearchParams();
  const streamId = sp.get("stream") ? Number(sp.get("stream")) : undefined;
  const [rep, setRep] = useState<TeamReport | null>(null);
  const [maps, setMaps] = useState<MapInfo[]>([]);
  const [mapName, setMapName] = useState<string>("");
  const [err, setErr] = useState("");

  useEffect(() => {
    api.teamReport(tag, streamId).then(setRep).catch((e) => setErr(e.message));
    api.maps().then(setMaps).catch(() => {});
  }, [tag, streamId]);

  const mapsPlayed = useMemo(() => [...new Set((rep?.matches ?? []).map((m) => m.map).filter(Boolean))] as string[], [rep]);
  useEffect(() => {
    if (!mapName && mapsPlayed.length) setMapName(mapsPlayed[0]);
  }, [mapsPlayed, mapName]);

  const onMap = (rep?.matches ?? []).filter((m) => m.map === mapName);
  const map = maps.find((m) => m.name === mapName);

  const layers = useMemo<Layer[]>(() => {
    const draw: Layer = (ctx, toPx) => {
      onMap.forEach((m, i) => {
        const col = PALETTE[i % PALETTE.length];
        ctx.strokeStyle = col;
        ctx.lineWidth = 2;
        ctx.globalAlpha = 0.75;
        ctx.beginPath();
        m.track.forEach((p, j) => {
          const [x, y] = toPx(p.x, p.y);
          if (j === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        ctx.stroke();
        ctx.globalAlpha = 1;
        if (m.drop) {
          const [x, y] = toPx(m.drop[0], m.drop[1]);
          ctx.fillStyle = col;
          ctx.strokeStyle = "#000";
          ctx.beginPath();
          ctx.arc(x, y, 8, 0, Math.PI * 2);
          ctx.fill();
          ctx.stroke();
          ctx.fillStyle = "#000";
          ctx.font = "700 10px system-ui";
          ctx.textAlign = "center";
          ctx.fillText(String(m.match_no ?? i + 1), x, y + 3.5);
          ctx.textAlign = "start";
        }
      });
    };
    return [draw];
  }, [onMap]);

  if (err) return <div className="page error">{err}</div>;
  if (!rep) return <div className="page muted">Loading…</div>;
  const color = teamColor(rep.matches[0]?.color ?? "");

  return (
    <div className="page wide">
      <Link to={streamId ? `/streams/${streamId}` : "/"} className="back">
        ← Back
      </Link>
      <div className="row head">
        <span className="dot big" style={{ background: color }} />
        <h1 className="grow">{rep.team}</h1>
      </div>
      <div className="stats">
        <Stat label="Matches" value={rep.summary.matches} />
        <Stat label="Avg placement" value={rep.summary.avg_placement ?? "–"} />
        <Stat label="Contested drops" value={rep.summary.contested_drop_pct !== null ? `${rep.summary.contested_drop_pct}%` : "–"} />
        <Stat label="Players" value={rep.matches[0]?.players.join(", ") || "–"} wide />
      </div>

      <div className="split">
        <div>
          <div className="chips">
            {mapsPlayed.map((m) => (
              <button key={m} className={`chip ${m === mapName ? "on" : ""}`} onClick={() => setMapName(m)}>
                {m}
              </button>
            ))}
          </div>
          <MapCanvas map={map} layers={layers} />
          <p className="muted small">Circles = drop spot (number = match), lines = rotation path, one colour per match.</p>
        </div>
        <div className="side">
          <h3>Zone play by phase</h3>
          <table>
            <thead>
              <tr>
                <th>Phase</th>
                <th>Inside</th>
                <th>Edge</th>
                <th>Outside</th>
                <th>Avg entry</th>
              </tr>
            </thead>
            <tbody>
              {rep.zone_by_phase.map((p) => (
                <tr key={p.phase}>
                  <td>{p.phase}</td>
                  <td className="zs ok">{p.inside}</td>
                  <td className="zs mid">{p.edge}</td>
                  <td className="zs bad">{p.outside}</td>
                  <td className="mono">{p.avg_entry_s !== null ? `${p.avg_entry_s}s` : "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3>Matches</h3>
          <table>
            <thead>
              <tr>
                <th>Match</th>
                <th>#</th>
                <th>Kills</th>
                <th>Drop</th>
              </tr>
            </thead>
            <tbody>
              {rep.matches.map((m, i) => (
                <tr key={m.match_id}>
                  <td>
                    <span className="dot" style={{ background: m.map === mapName ? PALETTE[onMap.indexOf(m) % PALETTE.length] : "#444" }} />{" "}
                    <Link to={`/matches/${m.match_id}`}>{matchLabel({ ...m, idx: i })}</Link>
                  </td>
                  <td className="mono">{m.placement ?? "–"}</td>
                  <td className="mono">{m.kills ?? "–"}</td>
                  <td className="small">{m.drop ? (m.drop_contested ? "contested" : "solo") : "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, wide }: { label: string; value: string | number; wide?: boolean }) {
  return (
    <div className={`stat ${wide ? "wide" : ""}`}>
      <div className="muted small">{label}</div>
      <div className="val">{value}</div>
    </div>
  );
}
