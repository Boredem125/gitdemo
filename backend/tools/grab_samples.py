"""Dev helper: save frames from a stream at fixed timestamps.

usage: python tools/grab_samples.py URL OUT_DIR START END STEP
"""
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2

from bgmi.source import grab, resolve

url, out, start, end, step = sys.argv[1], Path(sys.argv[2]), *map(float, sys.argv[3:6])
out.mkdir(parents=True, exist_ok=True)
info = resolve(url)
print(info.title, info.duration)
ts = [start + i * step for i in range(int((end - start) / step) + 1)]


def job(t):
    img = grab(info.video_url, t)
    if img is not None:
        cv2.imwrite(str(out / f"t{int(t):05d}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return t, img is not None


with ThreadPoolExecutor(6) as ex:
    for t, ok in ex.map(job, ts):
        if not ok:
            print("miss", t)
print("done", len(ts))
