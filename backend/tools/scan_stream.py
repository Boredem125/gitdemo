"""Dev: run pass 1 on a stream and dump samples + detected matches to JSON."""
import json, sys, time
from dataclasses import asdict
from bgmi import profile, source
from bgmi.scan import sample_stream, find_matches

url, out = sys.argv[1], sys.argv[2]
P = profile.load("bmsd2026")
info = source.resolve(url)
t = time.time()
samples = sample_stream(info, P, step=20, workers=6, on_progress=lambda p: print(f"{p:.0%}", flush=True))
spans = find_matches(samples, 20)
json.dump({"title": info.title, "duration": info.duration, "samples": [asdict(s) for s in samples],
           "matches": [asdict(m) for m in spans], "seconds": time.time() - t}, open(out, "w"), indent=1)
for m in spans:
    print(m)
print("took", round(time.time() - t), "s")
