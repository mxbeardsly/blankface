"""Stock footage from Pexels (free for commercial use) with offline fallback."""
from __future__ import annotations

import hashlib
import random
import subprocess
from pathlib import Path

import requests

from .core import OFFLINE, ROOT, env, load, save

CACHE = ROOT / "out" / "cache"


def _pick_file(video: dict, portrait: bool) -> dict | None:
    files = [f for f in video.get("video_files", []) if f.get("width") and f.get("height") and f.get("file_type") == "video/mp4"]
    want = (lambda f: f["height"] > f["width"]) if portrait else (lambda f: f["width"] >= f["height"])
    files = [f for f in files if want(f) and min(f["width"], f["height"]) >= 720]
    if not files:
        return None
    # smallest file that is still at least 1080 on the short side, else biggest
    good = sorted((f for f in files if min(f["width"], f["height"]) >= 1080),
                  key=lambda f: f["width"] * f["height"])
    return good[0] if good else max(files, key=lambda f: f["width"] * f["height"])


def fetch(query: str, portrait: bool, min_seconds: float, avoid: set[int]) -> dict:
    """Returns {"path", "pexels_id", "credit"}. Never reuses a clip in `avoid`."""
    CACHE.mkdir(parents=True, exist_ok=True)
    if OFFLINE:
        return _placeholder(query, portrait)
    r = requests.get("https://api.pexels.com/v1/videos/search",
                     headers={"Authorization": env("PEXELS_API_KEY")},
                     params={"query": query, "orientation": "portrait" if portrait else "landscape",
                             "per_page": 30, "size": "medium"}, timeout=30)
    r.raise_for_status()
    vids = [v for v in r.json().get("videos", [])
            if v["id"] not in avoid and v.get("duration", 0) >= min(min_seconds, 4)]
    if not vids and " " in query:  # loosen the search
        return fetch(query.split()[-1], portrait, min_seconds, avoid)
    random.shuffle(vids)
    for v in vids[:8]:
        f = _pick_file(v, portrait)
        if not f:
            continue
        p = CACHE / f"px_{v['id']}_{f['width']}x{f['height']}.mp4"
        if not p.exists():
            with requests.get(f["link"], stream=True, timeout=120) as d:
                d.raise_for_status()
                with open(p, "wb") as out:
                    for chunk in d.iter_content(1 << 20):
                        out.write(chunk)
        return {"path": p, "pexels_id": v["id"],
                "credit": f"{v.get('user', {}).get('name', 'Pexels')} on Pexels"}
    return _placeholder(query, portrait)


def _placeholder(query: str, portrait: bool) -> dict:
    """Animated gradient so the pipeline never dies on a missing clip."""
    w, h = (1080, 1920) if portrait else (1920, 1080)
    hue = int(hashlib.md5(query.encode()).hexdigest()[:2], 16) * 360 // 255
    p = CACHE / f"ph_{hue}_{w}x{h}.mp4"
    if not p.exists():
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
            f"gradients=s={w}x{h}:c0=0x1b1f3a:c1=0x3a2f6b:x0=0:y0=0:x1={w}:y1={h}:speed=0.02:d=20",
            "-vf", f"hue=h={hue}", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            str(p)], check=True)
    return {"path": p, "pexels_id": -hue, "credit": None}


def recently_used() -> set[int]:
    return set(load("used_clips.json", [])[-400:])


def remember(ids: list[int]) -> None:
    used = load("used_clips.json", [])
    used.extend(i for i in ids if i > 0)
    save("used_clips.json", used[-1000:])
