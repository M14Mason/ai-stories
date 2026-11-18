"""Render a story with the /video engine and check the output file."""
import json
import os
import subprocess

from . import common as C


def render(story):
    slug = story["slug"]
    os.makedirs(C.STORIES, exist_ok=True)
    sp = os.path.join(C.STORIES, f"{slug}.json")
    C.save(sp, story)
    env = dict(os.environ)
    r = subprocess.run(["python3", C.path("engine/build.py"), sp], cwd=C.ROOT, env=env,
                       capture_output=True, text=True, timeout=2400)
    out = os.path.join(C.OUT, f"{slug}.mp4")
    if r.returncode or not os.path.exists(out):
        tail = (r.stdout[-1500:] + "\n" + r.stderr[-1500:]).strip()
        raise C.PostError(f"render failed for {slug}: {tail[-600:]}")
    return out


def probe(mp4):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration,size:stream=codec_type,width,height",
                        "-of", "json", mp4], capture_output=True, text=True, check=True)
    j = json.loads(r.stdout)
    streams = j.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    return {"duration": round(float(j["format"]["duration"]), 2), "bytes": int(j["format"]["size"]),
            "width": v.get("width"), "height": v.get("height"),
            "audio": any(s.get("codec_type") == "audio" for s in streams)}


def check(info):
    errs = []
    if info["width"] != 1080 or info["height"] != 1920:
        errs.append(f"video is {info['width']}x{info['height']}, expected 1080x1920")
    if not 15 <= info["duration"] <= 90:
        errs.append(f"duration {info['duration']}s outside 15-90s")
    if not info["audio"]:
        errs.append("no audio track")
    if info["bytes"] > 250 * 1024 * 1024:
        errs.append("file over 250 MB")
    return errs


def contact_sheet(mp4, duration, frames=24):
    out = mp4[:-4] + "_sheet.jpg"
    fps = frames / max(duration, 1)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", mp4, "-vf",
                    f"fps={fps:.4f},scale=270:-1,tile=6x4", "-frames:v", "1", "-q:v", "4", out], check=True)
    return out


def thumbnail(mp4, at=1.5):
    out = mp4[:-4] + "_thumb.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(at), "-i", mp4, "-frames:v", "1",
                    "-vf", "scale=360:-1", "-q:v", "5", out], check=True)
    return out
