"""Video input: resolve a YouTube (or local file) source and iterate frames.

Frames come from ffmpeg piped as raw BGR24. For long streams we decode keyframes only
(`-skip_frame nokey`), which YouTube emits every ~2 s - cheap and plenty for tracking
team movement.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import imageio_ffmpeg
import numpy as np

WIDTH, HEIGHT = 1920, 1080


@dataclass
class StreamInfo:
    title: str
    duration: float  # seconds
    video_url: str  # direct media URL (or local path)
    source: str  # original input


@dataclass
class Frame:
    t: float  # seconds from stream start
    image: np.ndarray  # HxWx3 BGR, 1920x1080


def is_local(src: str) -> bool:
    return Path(src).exists()


def resolve(src: str, max_height: int = 1080) -> StreamInfo:
    """Resolve a YouTube URL to a direct video-only URL via yt-dlp, or accept a local file."""
    if is_local(src):
        return StreamInfo(title=Path(src).name, duration=probe_duration(src), video_url=src, source=src)

    import yt_dlp

    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": f"bv*[height<={max_height}][vcodec^=avc1]/bv*[height<={max_height}]",
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(src, download=False)
    url = info.get("url") or info["requested_formats"][0]["url"]
    return StreamInfo(title=info.get("title", ""), duration=float(info.get("duration") or 0), video_url=url, source=src)


def probe_duration(path: str) -> float:
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    out = subprocess.run([ff, "-i", path], capture_output=True, text=True).stderr
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("Duration:"):
            h, m, s = line.split(",")[0].split()[1].split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return 0.0


def _ffmpeg_cmd(url: str, start: float, end: float | None, keyframes_only: bool, fps: float | None) -> list[str]:
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ff, "-loglevel", "error", "-nostdin"]
    if keyframes_only:
        cmd += ["-skip_frame", "nokey"]
    cmd += ["-ss", f"{start:.3f}", "-i", url]
    if end is not None:
        cmd += ["-t", f"{max(0.0, end - start):.3f}"]
    vf = [f"scale={WIDTH}:{HEIGHT}"]
    if fps:
        vf.insert(0, f"fps={fps}")
    # -copyts + showinfo would give exact pts; frame_pts via -vsync passthrough is enough here
    cmd += ["-vsync", "passthrough", "-vf", ",".join(vf), "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    return cmd


def iter_frames(
    url: str,
    start: float = 0.0,
    end: float | None = None,
    keyframes_only: bool = True,
    fps: float | None = None,
) -> Iterator[Frame]:
    """Yield frames between start and end.

    Timestamps: with keyframes only we can't read exact pts from rawvideo, so we use
    ffprobe-free estimation via a parallel `-show_entries` pass would be costly; instead
    request pts through a second output (showinfo) is complex. We use `fps` for exact
    spacing when given, else read pts from the stderr of `-vf showinfo`.
    """
    ff_cmd = _ffmpeg_cmd(url, start, end, keyframes_only, fps)
    if fps is None:
        # add showinfo to get pts_time for each emitted frame
        i = ff_cmd.index("-vf")
        ff_cmd[i + 1] = ff_cmd[i + 1] + ",showinfo"
        ff_cmd[2] = "info"  # loglevel info so showinfo prints
    proc = subprocess.Popen(ff_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=WIDTH * HEIGHT * 3)
    frame_bytes = WIDTH * HEIGHT * 3
    times: list[float] = []

    def read_pts() -> float | None:
        # pull showinfo lines until we have one more timestamp
        assert proc.stderr is not None
        while len(times) == 0:
            line = proc.stderr.readline()
            if not line:
                return None
            s = line.decode("utf-8", "ignore")
            if "pts_time:" in s:
                v = s.split("pts_time:")[1].split()[0]
                try:
                    times.append(float(v))
                except ValueError:
                    pass
        return times.pop(0)

    n = 0
    try:
        assert proc.stdout is not None
        while True:
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            img = np.frombuffer(buf, np.uint8).reshape(HEIGHT, WIDTH, 3)
            if fps:
                t = start + n / fps
            else:
                pts = read_pts()
                t = start + (pts if pts is not None else n * 2.0)
            n += 1
            yield Frame(t=t, image=img)
    finally:
        proc.kill()
        proc.wait()


def grab(url: str, t: float) -> np.ndarray | None:
    """Single frame at time t (fast keyframe seek)."""
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ff, "-loglevel", "error", "-nostdin", "-ss", f"{t:.3f}", "-i", url, "-frames:v", "1",
           "-vf", f"scale={WIDTH}:{HEIGHT}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    out = subprocess.run(cmd, capture_output=True).stdout
    if len(out) < WIDTH * HEIGHT * 3:
        return None
    return np.frombuffer(out[: WIDTH * HEIGHT * 3], np.uint8).reshape(HEIGHT, WIDTH, 3)


def info_json(info: StreamInfo) -> str:
    return json.dumps({"title": info.title, "duration": info.duration, "source": info.source})
