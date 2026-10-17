import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, fmtTime, matchLabel, type Match, type Stream } from "../api";
import { Bar, StatusPill } from "../components/StatusPill";

export function StreamPage() {
  const id = Number(useParams().id);
  const [data, setData] = useState<{ stream: Stream; matches: Match[] } | null>(null);
  const [teams, setTeams] = useState<string[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    let stop = false;
    const load = async () => {
      try {
        const d = await api.stream(id);
        if (stop) return;
        setData(d);
        if (d.matches.some((m) => m.status === "done")) setTeams(await api.teams(id));
        if (d.stream.status !== "done" && d.stream.status !== "failed") setTimeout(load, 3000);
      } catch (e) {
        setErr((e as Error).message);
      }
    };
    load();
    return () => {
      stop = true;
    };
  }, [id]);

  if (err) return <div className="page error">{err}</div>;
  if (!data) return <div className="page muted">Loading…</div>;
  const { stream, matches } = data;

  return (
    <div className="page">
      <Link to="/" className="back">
        ← Streams
      </Link>
      <div className="row head">
        <div className="grow">
          <h1>{stream.title || "Stream"}</h1>
          <a href={stream.url} target="_blank" rel="noreferrer" className="muted small">
            {stream.url}
          </a>
        </div>
        <StatusPill status={stream.status} progress={stream.progress} />
      </div>
      {stream.status !== "done" && stream.status !== "failed" && (
        <div className="card">
          <div className="small muted">{stream.stage || "starting"}</div>
          <Bar value={stream.progress} />
        </div>
      )}
      {stream.status === "failed" && (
        <div className="card error">
          {stream.error}{" "}
          <button className="link" onClick={() => api.retry(id).then(() => location.reload())}>
            Retry
          </button>
        </div>
      )}

      <h2>Matches {matches.length > 0 && <span className="muted">({matches.length} found)</span>}</h2>
      <div className="grid">
        {matches.map((m) => (
          <div key={m.id} className="card">
            <div className="row">
              <div className="grow title">{matchLabel(m)}</div>
              <StatusPill status={m.status} />
            </div>
            <div className="muted small">
              {fmtTime(m.t_start)} – {fmtTime(m.t_end)} · {Math.round((m.t_end - m.t_start) / 60)} min
              {m.confidence < 0.8 && " · low confidence"}
            </div>
            {m.note && <div className="small warn">{m.note}</div>}
            {m.status === "processing" && <Bar value={m.progress} />}
            {m.status === "done" && (
              <Link to={`/matches/${m.id}`} className="btn small">
                Open match →
              </Link>
            )}
          </div>
        ))}
      </div>

      {teams.length > 0 && (
        <>
          <h2>Team reports</h2>
          <div className="chips">
            {teams.map((t) => (
              <Link key={t} to={`/teams/${t}?stream=${id}`} className="chip">
                {t}
              </Link>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
