"""Dev: run match processing on cached keyframes (data/cache/<dir>/k<t>.jpg) into the DB."""
import glob, json, os, sys, time
import cv2
from bgmi import db, source
from bgmi.process import process_match
from bgmi import analytics

d = sys.argv[1]
files = sorted(glob.glob(os.path.join(d, "k*.jpg")))
ts = [float(os.path.basename(f)[1:-4]) for f in files]
frames = (source.Frame(t=t, image=cv2.imread(f)) for t, f in zip(ts, files))
with db.session() as s:
    st = db.Stream(url="cached:" + d, title="cached " + os.path.basename(d), status="done", progress=1.0)
    s.add(st); s.commit(); s.refresh(st)
    m = db.Match(stream_id=st.id, idx=0, day=1, match_no=2, t_start=ts[0], t_end=ts[-1], status="processing")
    s.add(m); s.commit(); s.refresh(m)
    mid, sid = m.id, st.id
t = time.time()
stats = process_match(mid, "", "bmsd2026", ts[0], ts[-1], frames=frames)
db.update(db.Match, mid, status="done", progress=1.0, map=stats.get("map"))
print("stats", stats, "took", round(time.time() - t), "s; stream", sid, "match", mid)
f = analytics.match_facts(mid)
print("phases", [(p["idx"], round(p["r"], 2)) for p in f["phases"]])
for tm in f["teams"]:
    print(tm["team"], "place", tm["placement"], "kills", tm["kills"], "drop", tm["drop"] and [round(v, 2) for v in tm["drop"]],
          "contested" if tm["drop_contested"] else "", "pts", len(tm["track"]), [p["status_at_reveal"][0] for p in tm["phases"]])
