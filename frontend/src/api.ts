export type Stream = {
  id: number;
  url: string;
  title: string;
  duration: number;
  status: "queued" | "scanning" | "processing" | "done" | "failed";
  stage: string;
  progress: number;
  error: string;
  created_at: number;
};

export type Match = {
  id: number;
  stream_id: number;
  idx: number;
  day: number | null;
  match_no: number | null;
  map: string | null;
  t_start: number;
  t_end: number;
  status: "pending" | "processing" | "done" | "failed";
  progress: number;
  confidence: number;
  note: string;
};

export type TrackPoint = { t: number; x: number; y: number; n: number };
export type Phase = { idx: number; t_start: number; t_end: number; cx: number; cy: number; r: number };
export type TeamPhase = {
  phase: number;
  status_at_reveal: "inside" | "edge" | "outside" | "unknown";
  status_at_close: "inside" | "edge" | "outside" | "unknown";
  dist_at_reveal: number | null;
  entered_after: number | null;
};
export type TeamFacts = {
  team: string;
  color: string;
  players: string[];
  placement: number | null;
  kills: number | null;
  eliminated_at: number | null;
  drop: [number, number] | null;
  drop_contested: boolean;
  track: TrackPoint[];
  phases: TeamPhase[];
  player_drops: Record<string, [number, number]>;
};
export type MatchFacts = {
  match: Match;
  phases: Phase[];
  zones: { t: number; kind: "white" | "blue"; cx: number; cy: number; r: number }[];
  teams: TeamFacts[];
};

export type TeamReport = {
  team: string;
  matches: {
    match_id: number;
    stream_id: number;
    day: number | null;
    match_no: number | null;
    map: string | null;
    placement: number | null;
    kills: number | null;
    drop: [number, number] | null;
    drop_contested: boolean;
    track: TrackPoint[];
    phases: TeamPhase[];
    color: string;
    players: string[];
  }[];
  zone_by_phase: {
    phase: number;
    inside: number;
    edge: number;
    outside: number;
    unknown: number;
    inside_pct: number | null;
    avg_entry_s: number | null;
  }[];
  summary: { matches: number; avg_placement: number | null; contested_drop_pct: number | null };
};

export type MapInfo = { name: string; size_km: number; has_image: boolean; display: [number, number, number] };

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) {
    let msg = r.statusText;
    try {
      msg = (await r.json()).detail ?? msg;
    } catch {
      /* not json */
    }
    throw new Error(msg);
  }
  return r.json();
}

export const api = {
  createStream: (url: string) => req<{ id: number }>("/api/streams", { method: "POST", body: JSON.stringify({ url }) }),
  streams: () => req<Stream[]>("/api/streams"),
  stream: (id: number) => req<{ stream: Stream; matches: Match[] }>(`/api/streams/${id}`),
  retry: (id: number) => req<{ ok: boolean }>(`/api/streams/${id}/retry`, { method: "POST" }),
  match: (id: number) => req<MatchFacts>(`/api/matches/${id}`),
  teams: (streamId?: number) => req<string[]>(`/api/teams${streamId ? `?stream_id=${streamId}` : ""}`),
  teamReport: (tag: string, streamId?: number) =>
    req<TeamReport>(`/api/teams/${encodeURIComponent(tag)}/report${streamId ? `?stream_id=${streamId}` : ""}`),
  maps: () => req<MapInfo[]>("/api/maps"),
};

export function fmtTime(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
}

export function matchLabel(m: Pick<Match, "day" | "match_no" | "idx" | "map">): string {
  const n = m.match_no ? `Match ${m.match_no}` : `Match #${m.idx + 1}`;
  return `${m.day ? `Day ${m.day} · ` : ""}${n}${m.map ? ` · ${m.map}` : ""}`;
}
