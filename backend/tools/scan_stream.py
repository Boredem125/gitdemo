"""Dev: run pass 1 on a stream and dump samples + detected matches to JSON."""
import json, sys, time
from dataclasses import asdict
from bgmi import profile, source
from bgmi.scan import scan

url, out = sys.argv[1], sys.argv[2]
P = profile.load("bmsd2026")
info = source.resolve(url)
t = time.time()
spans = scan(info, P)
json.dump({"title": info.title, "duration": info.duration,
           "matches": [asdict(m) for m in spans], "seconds": time.time() - t}, open(out, "w"), indent=1)
for m in spans:
    print(m)
print("took", round(time.time() - t), "s")
