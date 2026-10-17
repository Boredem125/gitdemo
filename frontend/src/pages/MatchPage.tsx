import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, fmtTime, matchLabel, type MapInfo, type MatchFacts, type TeamFacts } from "../api";
import { MapCanvas, teamColor, type Layer } from "../components/MapCanvas";

const STATUS_CLASS: Record<string, string> = { inside: "ok", edge: "mid", outside: "bad", unknown: "unk" };

export function MatchPage() {
  const id = Number(useParams().id);
  const [data, setData] = useState<MatchFacts | null>(null);
  const [maps, setMaps] = useState<MapInfo[]>([]);
  const [t, setT] = useState<number | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [focus, setFocus] = useState<string | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.match(id).then(setData).catch((e) => setErr(e.message));
    api.maps().then(setMaps).catch(() => {});
  }, [id]);

  const range = useMemo(() => {
    if (!data) return [0, 1];
    const ts = data.teams.flatMap((tm) => tm.track.map((p) => p.t));
    return ts.length ? [Math.min(...ts), Math.max(...ts)] : [data.match.t_start, data.match.t_end];
  }, [data]);
  const now = t ?? range[1];
  const map = maps.find((m) => m.name === data?.match.map);

  const layers = useMemo<Layer[]>(() => {
    if (!data) return [];
    const visible = data.teams.filter((tm) => !hidden.has(tm.team) && (!focus || focus === tm.team));
    const zoneLayer: Layer = (ctx, toPx, k) => {
      // current next-zone at time `now`: latest white circle before now
      const w = [...data.zones].filter((z) => z.kind === "white" && z.t <= now).pop();
      const b = [...data.zones].filter((z) => z.kind === "blue" && z.t <= now).pop();
      if (b) {
        const [x, y] = toPx(b.cx, b.cy);
        ctx.strokeStyle = "rgba(80,140,255,0.9)";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(x, y, b.r * k, 0, Math.PI * 2);
        ctx.stroke();
      }
      if (w) {
        const [x, y] = toPx(w.cx, w.cy);
        ctx.strokeStyle = "rgba(255,255,255,0.95)";
        ctx.setLineDash([6, 5]);
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(x, y, w.r * k, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    };
    const trackLayer: Layer = (ctx, toPx) => {
      for (const tm of visible) {
        const col = teamColor(tm.color);
        const pts = tm.track.filter((p) => p.t <= now);
        if (pts.length === 0) continue;
        ctx.strokeStyle = col;
        ctx.lineWidth = focus ? 3 : 2;
        ctx.globalAlpha = 0.85;
        ctx.beginPath();
        pts.forEach((p, i) => {
          const [x, y] = toPx(p.x, p.y);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        ctx.stroke();
        ctx.globalAlpha = 1;
        if (tm.drop) {
          const [dx, dy] = toPx(tm.drop[0], tm.drop[1]);
          ctx.fillStyle = col;
          ctx.strokeStyle = "#000";
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          ctx.rect(dx - 5, dy - 5, 10, 10);
          ctx.fill();
          ctx.stroke();
        }
        const last = pts[pts.length - 1];
        const dead = tm.eliminated_at !== null && now >= tm.eliminated_at;
        const [lx, ly] = toPx(last.x, last.y);
        ctx.fillStyle = dead ? "#555" : col;
        ctx.beginPath();
        ctx.arc(lx, ly, 7, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 1.5;
        ctx.stroke();
        ctx.font = "600 12px system-ui, sans-serif";
        ctx.fillStyle = "#fff";
        ctx.strokeStyle = "rgba(0,0,0,0.8)";
        ctx.lineWidth = 3;
        ctx.strokeText(tm.team, lx + 9, ly + 4);
        ctx.fillText(tm.team, lx + 9, ly + 4);
      }
    };
    return [zoneLayer, trackLayer];
  }, [data, now, hidden, focus]);

  if (err) return <div className="page error">{err}</div>;
  if (!data) return <div className="page muted">Loading…</div>;
  const m = data.match;

  return (
    <div className="page wide">
      <Link to={`/streams/${m.stream_id}`} className="back">
        ← Stream
      </Link>
      <h1>{matchLabel(m)}</h1>
      <p className="muted small">
        {fmtTime(m.t_start)} – {fmtTime(m.t_end)} in the stream · {data.phases.length} zone phases detected · squares = drop spot
      </p>
      <div className="split">
        <div>
          <MapCanvas map={map} layers={layers} />
          <div className="scrub">
            <input
              type="range"
              min={range[0]}
              max={range[1]}
              step={5}
              value={now}
              onChange={(e) => setT(Number(e.target.value))}
              aria-label="Match time"
            />
            <span className="mono">{fmtTime(now - range[0])}</span>
          </div>
        </div>
        <div className="side">
          <TeamTable teams={data.teams} hidden={hidden} setHidden={setHidden} focus={focus} setFocus={setFocus} streamId={m.stream_id} />
        </div>
      </div>

      <h2>Zone play</h2>
      <p className="muted small">Where each team stood when each new zone was revealed (inside / edge / outside), and how long they took to get in.</p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Team</th>
              {data.phases.map((p) => (
                <th key={p.idx}>Phase {p.idx}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.teams.map((tm) => (
              <tr key={tm.team}>
                <td>
                  <span className="dot" style={{ background: teamColor(tm.color) }} /> {tm.team}
                </td>
                {tm.phases.map((p) => (
                  <td key={p.phase} className={`zs ${STATUS_CLASS[p.status_at_reveal]}`}>
                    {p.status_at_reveal === "unknown" ? "–" : p.status_at_reveal}
                    {p.entered_after !== null && p.status_at_reveal !== "inside" && (
                      <span className="small"> · in {Math.round(p.entered_after)}s</span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TeamTable(props: {
  teams: TeamFacts[];
  hidden: Set<string>;
  setHidden: (s: Set<string>) => void;
  focus: string | null;
  setFocus: (t: string | null) => void;
  streamId: number;
}) {
  const { teams, hidden, setHidden, focus, setFocus, streamId } = props;
  return (
    <table className="teams">
      <thead>
        <tr>
          <th>#</th>
          <th>Team</th>
          <th>Kills</th>
          <th>Drop</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {teams.map((tm) => (
          <tr key={tm.team} className={focus === tm.team ? "sel" : ""}>
            <td className="mono">{tm.placement ?? "–"}</td>
            <td>
              <label className="row tight">
                <input
                  type="checkbox"
                  checked={!hidden.has(tm.team)}
                  onChange={() => {
                    const n = new Set(hidden);
                    if (n.has(tm.team)) n.delete(tm.team);
                    else n.add(tm.team);
                    setHidden(n);
                  }}
                />
                <span className="dot" style={{ background: teamColor(tm.color) }} />
                <button className="link" onClick={() => setFocus(focus === tm.team ? null : tm.team)} title={tm.players.join(", ")}>
                  {tm.team}
                </button>
              </label>
            </td>
            <td className="mono">{tm.kills ?? "–"}</td>
            <td className="small">{tm.drop ? (tm.drop_contested ? "contested" : "solo") : "–"}</td>
            <td>
              <Link to={`/teams/${tm.team}?stream=${streamId}`} className="small">
                report
              </Link>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
