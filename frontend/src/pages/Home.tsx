import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, fmtTime, type Stream } from "../api";
import { StatusPill } from "../components/StatusPill";

export function Home() {
  const [url, setUrl] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [streams, setStreams] = useState<Stream[]>([]);
  const nav = useNavigate();

  useEffect(() => {
    const load = () => api.streams().then(setStreams).catch(() => {});
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      const { id } = await api.createStream(url);
      nav(`/streams/${id}`);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <section className="hero">
        <h1>Scout every team from the map stream</h1>
        <p className="muted">
          Paste a BGMI tournament <b>[MAP STREAM]</b> link. Matches, maps and teams are found automatically, and you get each team's
          drop spots, rotations and how they play every zone.
        </p>
        <form onSubmit={submit} className="url-form">
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://www.youtube.com/live/…"
            aria-label="Map stream link"
            required
          />
          <button disabled={busy}>{busy ? "Starting…" : "Analyse"}</button>
        </form>
        {err && <p className="error">{err}</p>}
      </section>

      <section>
        <h2>Streams</h2>
        {streams.length === 0 && <p className="muted">Nothing analysed yet.</p>}
        <div className="list">
          {streams.map((s) => (
            <Link key={s.id} to={`/streams/${s.id}`} className="card row">
              <div className="grow">
                <div className="title">{s.title || s.url}</div>
                <div className="muted small">
                  {s.duration ? fmtTime(s.duration) : ""} {s.stage && `· ${s.stage}`}
                </div>
              </div>
              <StatusPill status={s.status} progress={s.progress} />
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
