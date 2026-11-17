"""Stock footage from Pixabay (free for commercial use) with offline fallback.

Pixabay asks API users to cache searches for 24 hours and avoid mass
automated querying, so searches are cached on disk and in data/.
"""
from __future__ import annotations

import hashlib
import random
import subprocess
import time

import requests

from .core import OFFLINE, ROOT, env, load, save

CACHE = ROOT / "out" / "cache"
API = "https://pixabay.com/api/videos/"
MAX_BYTES = 80 * 1024 * 1024  # skip giant 4K files


def _search(query: str) -> list[dict]:
    cache = load("pixabay_cache.json", {})
    hit = cache.get(query)
    if hit and time.time() - hit["t"] < 86400:
        return hit["hits"]
    r = requests.get(API, params={"key": env("PIXABAY_API_KEY"), "q": query[:100],
                                  "video_type": "film", "safesearch": "true",
                                  "per_page": 30, "order": "popular"}, timeout=30)
    r.raise_for_status()
    hits = r.json().get("hits", [])
    cache = {k: v for k, v in cache.items() if time.time() - v["t"] < 86400}
    cache[query] = {"t": time.time(), "hits": hits}
    save("pixabay_cache.json", cache)
    return hits


def _pick_file(hit: dict, portrait: bool) -> dict | None:
    vids = hit.get("videos", {})
    # Portrait output is a center crop of landscape footage, so prefer the
    # 4K rendition when it is a sane size; otherwise the 1080p one.
    order = ["large", "medium"] if portrait else ["medium", "large"]
    for k in order:
        f = vids.get(k) or {}
        if f.get("url") and 0 < f.get("size", 0) <= MAX_BYTES and min(f["width"], f["height"]) >= 720:
            return f
    return None


def fetch(query: str, portrait: bool, min_seconds: float, avoid: set[int]) -> dict:
    """Returns {"path", "clip_id", "credit"}. Never reuses a clip in `avoid`."""
    CACHE.mkdir(parents=True, exist_ok=True)
    if OFFLINE:
        return _placeholder(query, portrait)
    hits = [h for h in _search(query)
            if h["id"] not in avoid and h.get("duration", 0) >= min(min_seconds, 4)]
    if portrait:  # true vertical clips first, when they exist
        hits.sort(key=lambda h: h["videos"]["medium"]["height"] > h["videos"]["medium"]["width"],
                  reverse=True)
    if not hits and " " in query:  # loosen the search
        return fetch(query.split()[-1], portrait, min_seconds, avoid)
    top, rest = hits[:6], hits[6:]
    random.shuffle(top)
    for h in top + rest[:6]:
        f = _pick_file(h, portrait)
        if not f:
            continue
        p = CACHE / f"pb_{h['id']}_{f['width']}x{f['height']}.mp4"
        if not p.exists():
            with requests.get(f["url"], stream=True, timeout=180) as d:
                d.raise_for_status()
                with open(p, "wb") as out:
                    for chunk in d.iter_content(1 << 20):
                        out.write(chunk)
        return {"path": p, "clip_id": h["id"], "credit": f"{h.get('user', 'Pixabay')} on Pixabay"}
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
    return {"path": p, "clip_id": -hue, "credit": None}


def recently_used() -> set[int]:
    return set(load("used_clips.json", [])[-400:])


def remember(ids: list[int]) -> None:
    used = load("used_clips.json", [])
    used.extend(i for i in ids if i > 0)
    save("used_clips.json", used[-1000:])
